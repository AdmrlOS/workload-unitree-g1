# syntax=docker/dockerfile:1
#
# Unitree G1 EDU PC4 user-board userspace for Admiral (linux/arm64 only).
# Before building: python3 scripts/fetch-unitree-assets.py
# This stages the official Unitree bootstrap and the two JetPack 7.2 UPKs,
# each verified against a pinned sha256. No robot or private capture needed.

ARG BUILD_IMAGE=ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3
ARG RUNTIME_IMAGE=ubuntu:24.04@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3

# Stage vendor bootstrap and exact binary payloads from the two UPKs.
FROM ${BUILD_IMAGE} AS unitree-files
ARG TARGETARCH
RUN test "$TARGETARCH" = arm64
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 unzip \
    && rm -rf /var/lib/apt/lists/*
COPY artifacts/ /assets/
COPY scripts/unpack-upk.py /usr/local/bin/unpack-upk.py
COPY scripts/prepare-runtime.py /usr/local/bin/prepare-runtime.py
RUN echo '9bb545ba6b90d4477843044c780d4646fb8a543467082ae910fc83d598962765  /assets/g1plus_pc4_unitree_install.zip' | sha256sum -c - \
    && mkdir -p /base /out/etc/init.d \
    && unzip -q /assets/g1plus_pc4_unitree_install.zip -d /base \
    && cp -a /base/g1plus_pc4_unitree_install/unitree /out/unitree \
    && cp -a /base/g1plus_pc4_unitree_install/etc/init.d/. /out/etc/init.d/ \
    && python3 /usr/local/bin/unpack-upk.py /assets/unitree_patch_pc4.upk \
       --sha256 33c08e002fce0273b729bd24706614aa2221cef5481dc7d8a2ff6c0d344f605d \
       --name unitree_patch_pc4_1.0.0.6 --install-root /out \
    && python3 /usr/local/bin/unpack-upk.py /assets/video_hub_pc4.upk \
       --sha256 de8b0815297bf5556b6fd7b2bed58d8a229f608b4227c1908bdebe48dbe23ea9 \
       --name video_hub_pc4_1.0.1.1 --install-root /out \
    && chmod 0755 /out/etc/init.d/master_service /out/etc/init.d/ota_pipe \
       /out/unitree/module/master_service/master_service /out/unitree/ota/pipe/ota_pipe_service \
       /out/unitree/sbin/mscli /out/unitree/sbin/ota_pipe_cli \
       /out/unitree/sbin/start-stop-daemon /out/unitree/module/video_hub_pc4/start_videohub.sh \
       /out/unitree/module/video_hub_pc4/videohub_pc4 \
    && test -s /out/usr/lib/aarch64-linux-gnu/libddsc.so.0 \
    && python3 /usr/local/bin/prepare-runtime.py

# ---------------------------------------------------------------------------
# Ubuntu 24.04 userspace for L4T 39.2.0 (Admiral supplies kernel and GPU driver).
# ---------------------------------------------------------------------------
FROM ${RUNTIME_IMAGE}
ARG TARGETARCH
RUN test "$TARGETARCH" = arm64
ARG IMAGE_VERSION=2026-09-26-pc4-r39.2.0-r2
LABEL org.opencontainers.image.title="unitree-g1" \
      org.opencontainers.image.description="Unitree G1 EDU PC4 stack (master_service/ota_pipe/video_hub) on Admiral, Jetson Orin NX user-workload board" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      co.admrl.workload="unitree-g1"

ARG NVIDIA_GST_DEB_URL=https://repo.download.nvidia.com/jetson/common/pool/main/n/nvidia-l4t-gstreamer/nvidia-l4t-gstreamer_39.2.0-20260601141651_arm64.deb
ARG NVIDIA_GST_DEB_SHA256=008c8c2821be7fe8d4e5d8f41d1cebd38801e3dddf7912aeaf63da22a6cd7482
ARG OPENSSL11_DEB_URL=http://ports.ubuntu.com/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2_arm64.deb
ARG OPENSSL11_DEB_SHA256=a697e5826bdbed1324f3cce1335ef162bf49eed433eb662c6d43e69ebc4807b2

ENV LANG=C.UTF-8

# Base packages:
#  - tini: PID 1 / signal forwarding, matches the cuda-debug workload pattern.
#  - openssh-server: diagnostic SSH access (mirrors workload-cuda-debug).
#  - lsb-base/init-system-helpers: vendor SysV init scripts source
#    /lib/lsb/init-functions and /lib/init/vars.sh.
#  - unzip/jq/curl/ca-certificates: diagnostics + capture-tarball handling.
#  - v4l-utils: v4l2-ctl for camera diagnostics (unitree-g1-status).
#  - iproute2/iputils-ping/procps/less/nano/strace: parity with cuda-debug's
#    diagnostic toolset.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tini openssh-server lsb-base init-system-helpers ca-certificates curl jq \
        iproute2 iputils-ping procps less nano strace v4l-utils alsa-utils \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && groupadd --gid 28 admiral-video \
    && useradd --create-home --shell /bin/bash --groups admiral-video,dialout,plugdev unitree-ssh \
    && mkdir -p /root/.ssh /home/unitree-ssh/.ssh /run/sshd /var/log/unitree-g1 \
    && chmod 0700 /root/.ssh /home/unitree-ssh/.ssh

# Install vendor files directly, including the exact libddsc.so.0 supplied
# alongside videohub_pc4 in its UPK. Do not compile a substitute ABI.
COPY --from=unitree-files /out/ /
# The module's udev rule must run in Admiral's host udev, not inside an
# OCI mount namespace. See docs/bsp-handoff.md for the BSP-side rule.
RUN rm /etc/udev/rules.d/70-unitree-realsense-rlsen0.rules

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
        libgstreamer1.0-0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad gstreamer1.0-tools \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fSL --retry 5 "${NVIDIA_GST_DEB_URL}" -o /tmp/nvidia-l4t-gstreamer.deb \
    && echo "${NVIDIA_GST_DEB_SHA256}  /tmp/nvidia-l4t-gstreamer.deb" | sha256sum -c - \
    && dpkg -x /tmp/nvidia-l4t-gstreamer.deb / && rm /tmp/nvidia-l4t-gstreamer.deb \
    && ldconfig

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
