# syntax=docker/dockerfile:1
#
# workload-unitree-g1 — packages the Unitree G1 EDU "PC4" user-workload stack
# (master_service + ota_pipe + unitree_patch + video_hub camera module) as an
# Admiral OCI workload for the G1's second Jetson Orin NX (the user-workload
# board — the other Jetson on the robot, running motion/locomotion control, is
# locked down and out of scope here).
#
# This is a CAPTURE build, not a from-scratch reconstruction: the Unitree
# binaries (/unitree/**, /etc/init.d/master_service, /etc/init.d/ota_pipe) are
# proprietary and are not fetched from a public URL here. You must first run
# capture/capture-unitree-g1.sh on a board already flashed with
# https://github.com/legion1581/unitree-jetpack (g1 branch, -j 7.2) with the
# unitree_patch + video_hub modules installed via the OTA uploader, per
# docs/unitree-stack.md in that repo. That script produces
# capture/unitree-g1-rootfs.tar.zst, which this Dockerfile ADDs. See
# capture/README.md.
#
# Runtime library gaps between the vendor stack and a stock Ubuntu 24.04
# (L4T 39.2.0) rootfs, reproduced here the same way
# legion1581/unitree-jetpack's versions/7.2/patches/{71,72,74}-*.sh do it —
# pinned artifact + sha256, no bare `apt install` of unpinned packages:
#
#   - libssl1.1 (libcrypto.so.1.1 + libssl.so.1.1): master_service was built
#     against OpenSSL 1.1 (JetPack 5.1 / 20.04 era); 24.04 ships only 3.0.
#   - libddsc.so.0 (CycloneDDS): video_hub_pc4 links Eclipse CycloneDDS for
#     its DDS topics (camera frames published over multicast 230.1.1.1 on
#     eth0). We build it from source instead of vendoring a third party's
#     binary blob. IMPORTANT: CycloneDDS jumped its versioning straight from
#     0.10.x to 11.0.0 — the SONAME libddsc.so.0 only exists on the 0.x
#     branch, so we pin 0.10.5 (last 0.x release), not latest. This is a
#     best-effort ABI match; verify against the real video_hub_pc4 binary
#     (ldd / dlopen) on hardware — see capture/README.md.
#   - nvidia-l4t-gstreamer (nvvidconv/nvv4l2h264enc/nvjpegenc): video_hub's
#     GStreamer pipeline hard-codes these HW-accelerated elements. Pinned to
#     the same L4T 39.2.0 .deb legion1581/unitree-jetpack uses. Admiral's
#     Jetson Orin driver injection (docs: /core-concepts/jetson-orin-cuda)
#     covers libcuda.so.1 + companion driver libs, NOT the L4T multimedia
#     API — this package is what's missing from that contract.
#
# Admiral launch contract this image assumes (see README.md for the full
# Configuration recipe):
#   - isolateDevices: false   (V4L2 camera, /dev/nvhost*, /dev/nvmap, /dev/dri)
#   - hostNetwork:    true    (static 192.168.123.164/24 on the physical NIC,
#                              set at the Admiral OS/network layer — NOT by
#                              this container — plus DDS multicast discovery)
#   - interactive:    false   (headless service, no kiosk/VT)
#   - Custom Volumes for /unitree/robot/data (or wherever the capture shows
#     mutable module state living) so it survives image updates.
#
# ARCHITECTURE: linux/arm64 only. This never runs on x86.

ARG BUILD_IMAGE=ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3
ARG RUNTIME_IMAGE=ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3

# ---------------------------------------------------------------------------
# Stage: cyclonedds-build — build libddsc.so.0 from source (0.x branch, the
# last release line whose SONAME is libddsc.so.0; 11.0+ renamed the SONAME).
# ---------------------------------------------------------------------------
FROM ${BUILD_IMAGE} AS cyclonedds-build
ARG TARGETARCH
RUN test "$TARGETARCH" = arm64
ARG CYCLONEDDS_TAG=0.10.5
ARG CYCLONEDDS_SHA256=ec3ec898c52b02f939a969cd1a276e219420e5e8419b21cea276db35b4821848
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential cmake ninja-build ca-certificates curl binutils \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fSL --retry 5 "https://github.com/eclipse-cyclonedds/cyclonedds/archive/refs/tags/${CYCLONEDDS_TAG}.tar.gz" -o /tmp/cyclonedds.tar.gz \
    && echo "${CYCLONEDDS_SHA256}  /tmp/cyclonedds.tar.gz" | sha256sum -c - \
    && mkdir /src && tar -xzf /tmp/cyclonedds.tar.gz -C /src --strip-components=1 \
    && rm /tmp/cyclonedds.tar.gz
# Minimal runtime lib only: no idlc/tools, no security plugins, no shared-mem
# (iceoryx) — video_hub only needs the ddsc DCPS API surface at runtime.
RUN cmake -S /src -B /build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
        -DBUILD_TESTING=OFF -DBUILD_IDLC=OFF -DBUILD_DDSPERF=OFF \
        -DENABLE_SECURITY=OFF -DENABLE_SHM=OFF -DENABLE_SSL=OFF \
    && cmake --build /build --target ddsc --parallel "$(nproc)"
RUN mkdir -p /out/lib /out/licenses \
    && cp -a /build/lib/libddsc.so* /out/lib/ \
    && cp /src/LICENSE.md /out/licenses/cyclonedds-LICENSE 2>/dev/null || true \
    # Hard assertion: fail the build now, not at robot boot, if the SONAME
    # this produced isn't the one video_hub_pc4 is going to dlopen.
    && _soname="$(readelf -d /out/lib/libddsc.so* 2>/dev/null | grep -m1 SONAME | sed -E 's/.*\[(.*)\].*/\1/')" \
    && echo "built libddsc SONAME: ${_soname}" \
    && test "${_soname}" = "libddsc.so.0" \
    && ldd /out/lib/libddsc.so* | tee /out/licenses/../cyclonedds-ldd.txt

# ---------------------------------------------------------------------------
# Stage: final — Ubuntu 24.04 userspace matching JetPack 7.2 / L4T 39.2.0,
# plus the captured Unitree PC4 stack and its missing runtime libs.
# ---------------------------------------------------------------------------
FROM ${RUNTIME_IMAGE}
ARG TARGETARCH
RUN test "$TARGETARCH" = arm64
ARG IMAGE_VERSION=2026-09-26-pc4-r39.2.0-r1
LABEL org.opencontainers.image.title="unitree-g1" \
      org.opencontainers.image.description="Unitree G1 EDU PC4 stack (master_service/ota_pipe/video_hub) on Admiral, Jetson Orin NX user-workload board" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      co.admrl.workload="unitree-g1"

ARG NVIDIA_GST_DEB_URL=https://repo.download.nvidia.com/jetson/common/pool/main/n/nvidia-l4t-gstreamer/nvidia-l4t-gstreamer_39.2.0-20260601141651_arm64.deb
ARG NVIDIA_GST_DEB_SHA256=008c8c2821be7fe8d4e5d8f41d1cebd38801e3dddf7912aeaf63da22a6cd7482
ARG OPENSSL11_DEB_URL=http://ports.ubuntu.com/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2_arm64.deb
ARG OPENSSL11_DEB_SHA256=a697e5826bdbed1324f3cce1335ef162bf49eed433eb662c6d43e69ebc4807b2

ENV LANG=C.UTF-8 DDS_MCAST_IFACE=eth0 DDS_MCAST_GROUP=230.1.1.1

# Base packages:
#  - tini: PID 1 / signal forwarding, matches the cuda-debug workload pattern.
#  - openssh-server: diagnostic SSH access (mirrors workload-cuda-debug).
#  - lsb-base: /lib/lsb/init-functions, sourced by the vendor's LSB init.d
#    scripts (master_service, ota_pipe) — those scripts run standalone fine
#    without a real init system as long as this is present.
#  - unzip/jq/curl/ca-certificates: diagnostics + capture-tarball handling.
#  - v4l-utils: v4l2-ctl for camera diagnostics (unitree-g1-status).
#  - iproute2/iputils-ping/procps/less/nano/strace: parity with cuda-debug's
#    diagnostic toolset.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tini openssh-server lsb-base ca-certificates curl jq unzip zstd \
        iproute2 iputils-ping procps less nano strace v4l-utils \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && groupadd --gid 28 admiral-video \
    && useradd --create-home --shell /bin/bash --groups admiral-video,dialout,plugdev unitree-ssh \
    && mkdir -p /root/.ssh /home/unitree-ssh/.ssh /run/sshd /var/log/unitree-g1 \
    && chmod 0700 /root/.ssh /home/unitree-ssh/.ssh

# --- The captured vendor stack (see capture/README.md) ----------------------
# unitree-g1-rootfs.tar.zst is produced ON HARDWARE by
# capture/capture-unitree-g1.sh and is NOT checked into this repo (contains
# Unitree's proprietary binaries) — build fails loudly if it's missing.
COPY capture/unitree-g1-rootfs.tar.zst /tmp/unitree-g1-rootfs.tar.zst
RUN tar --zstd -xf /tmp/unitree-g1-rootfs.tar.zst -C / \
    && rm /tmp/unitree-g1-rootfs.tar.zst \
    && test -x /unitree/module/master_service/master_service \
    && test -f /etc/init.d/master_service && test -f /etc/init.d/ota_pipe \
    && chmod 0755 /etc/init.d/master_service /etc/init.d/ota_pipe

# --- Runtime library gaps, pinned + verified (see header comment) ----------
# libssl1.1 is a clean standalone install: dpkg -i is fine, no transitive
# NVIDIA dependencies.
RUN curl -fSL --retry 5 "${OPENSSL11_DEB_URL}" -o /tmp/libssl1.1.deb \
    && echo "${OPENSSL11_DEB_SHA256}  /tmp/libssl1.1.deb" | sha256sum -c - \
    && dpkg -i /tmp/libssl1.1.deb && rm /tmp/libssl1.1.deb

# nvidia-l4t-gstreamer's declared dependency graph pulls in the ENTIRE L4T
# BSP multimedia family (nvidia-l4t-core/-multimedia/-multimedia-utils/
# -camera/-nvsci) *and*, critically, offers `libcuda.so.1` as one of the
# alternatives satisfying its nvidia-l4t-cuda-nvgpu dependency — i.e. a
# naive `dpkg -i` (or `apt-get install .deb`) here would either fail (no
# apt source configured for the transitive nvidia-l4t-* packages, as found
# when reproducing this build) or, if it succeeded, risk pulling in a
# *second*, build-time GPU driver stub that conflicts with the one Admiral
# injects at runtime — exactly what
# https://docs.admrl.co/core-concepts/jetson-orin-cuda explicitly warns
# against ("Omit competing NVIDIA driver packages from the final image").
#
# So: `dpkg -x` (extract file contents only — no dependency resolution, no
# maintainer scripts, no driver package pulled in) for the NVIDIA package,
# and plain Ubuntu archive packages (no pinning drama, generic userspace
# libs) for gstreamer-core/DRM/EGL/Wayland/X11.
#
# KNOWN GAP (see docs/admiral-mapping.md risk #1): this installs the
# nvv4l2h264enc/nvvidconv/nvjpegenc *GStreamer element* .so files, but NOT
# their nvidia-l4t-multimedia dependency (libnvbufsurface.so,
# libnvbuf_utils.so — the NVMM buffer allocator those elements call into)
# or nvidia-l4t-camera (libnvargus — ISP/CSI capture). Those packages are
# not published in NVIDIA's public "jetson/common" apt pool the way
# nvidia-l4t-gstreamer is; they ship inside the BSP tarball itself
# (Jetson_Linux_R39.2.0_aarch64.tbz2 → Linux_for_Tegra/nv_tegra/
# l4t_deb_packages/*.deb — the same BSP_URL legion1581/unitree-jetpack
# pins in versions/7.2/version.env). Extracting the right subset of THAT
# (again explicitly excluding nvidia-l4t-cuda-nvgpu/-cuda-openrm — Admiral
# owns the compute driver) is the next step before video_hub_pc4 can be
# expected to actually produce frames; until then, expect
# `nvv4l2h264enc`/`nvvidconv` to load but fail at buffer-allocation time.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libdrm2 libegl1 libgles2 libglib2.0-0t64 libpcre3 libexpat1 libasound2t64 \
        libwayland-client0 libwayland-egl1 libx11-6 libxcb1 libxext6 \
        libgstreamer1.0-0 gstreamer1.0-plugins-base gstreamer1.0-plugins-bad gstreamer1.0-tools \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fSL --retry 5 "${NVIDIA_GST_DEB_URL}" -o /tmp/nvidia-l4t-gstreamer.deb \
    && echo "${NVIDIA_GST_DEB_SHA256}  /tmp/nvidia-l4t-gstreamer.deb" | sha256sum -c - \
    && dpkg -x /tmp/nvidia-l4t-gstreamer.deb / && rm /tmp/nvidia-l4t-gstreamer.deb \
    && ldconfig

COPY --from=cyclonedds-build /out/lib/ /usr/lib/aarch64-linux-gnu/
COPY --from=cyclonedds-build /out/licenses/ /usr/share/licenses/unitree-g1/cyclonedds/

COPY scripts/ /usr/local/bin/
COPY ssh/sshd_config /etc/ssh/sshd_config
COPY ssh/authorized_keys /root/.ssh/authorized_keys
COPY ssh/authorized_keys /home/unitree-ssh/.ssh/authorized_keys
COPY README.md /opt/unitree-g1/README.md

RUN chmod 0755 /usr/local/bin/start-unitree-g1 /usr/local/bin/unitree-g1-status \
    && chmod 0600 /root/.ssh/authorized_keys /home/unitree-ssh/.ssh/authorized_keys \
    && chown -R unitree-ssh:unitree-ssh /home/unitree-ssh/.ssh \
    && ldconfig \
    # This never leaves the image: driver injection is Admiral's job, not
    # ours (see docs/admiral-mapping.md). If either shows up here the build
    # is accidentally bundling a competing driver and must fail.
    && test -z "$(find /usr -name 'libcuda.so*' -print -quit)" \
    && test -z "$(find /usr -type d -name stubs -print -quit)" \
    && dpkg-query -W > /opt/unitree-g1/runtime-packages.txt \
    && printf 'Base: JetPack 7.2 / L4T 39.2.0 userspace (Ubuntu 24.04 aarch64)\nImage version: %s\n' "$IMAGE_VERSION" > /opt/unitree-g1/build-info.txt \
    && printf '\nunitree-g1 diagnostics: unitree-g1-status inspect\nBoot log: /var/log/unitree-g1/boot.log\n' > /etc/motd

WORKDIR /opt/unitree-g1
# 8888 (the vendor OTA uploader) is deliberately NOT exposed — module set is
# frozen at image-build time; see docs/admiral-mapping.md for why.
EXPOSE 22/tcp
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/start-unitree-g1"]
