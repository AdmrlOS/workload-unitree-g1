# syntax=docker/dockerfile:1
#
# Unitree G1 EDU PC4 user-board userspace for Admiral (linux/arm64 only).
# Before building: python3 scripts/fetch-unitree-assets.py
# This stages the official Unitree bootstrap and the two JetPack 7.2 UPKs,
# each verified against a pinned sha256. No robot or private capture needed.

ARG BUILD_IMAGE=ubuntu:26.04@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78
ARG RUNTIME_IMAGE=ubuntu:26.04@sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78

# Stage vendor bootstrap and exact binary payloads from the two UPKs.
FROM ${BUILD_IMAGE} AS unitree-files
ARG TARGETARCH
RUN test "$TARGETARCH" = arm64
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3 unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY artifacts/g1plus_pc4_unitree_install.zip artifacts/unitree_patch_pc4.upk artifacts/video_hub_pc4.upk /assets/
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

# Multimedia libraries are extracted independently of the Unitree payload.
FROM ${BUILD_IMAGE} AS nvidia-files
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY config/nvidia-packages.json /lock.json
COPY scripts/stage-nvidia.py /stage-nvidia.py
RUN --mount=type=cache,target=/downloads \
    python3 /stage-nvidia.py --lock /lock.json --assets /downloads --output /out

# Ubuntu 26.04 application userspace, paired with Admiral's R39.2.1 G1 BSP.
FROM ${RUNTIME_IMAGE}
ARG TARGETARCH
RUN test "$TARGETARCH" = arm64
ARG IMAGE_VERSION=2026-09-28-pc4-ubuntu26.04-r39.2.1-r8
LABEL org.opencontainers.image.title="unitree-g1" \
      org.opencontainers.image.description="Unitree G1 EDU PC4 userspace on Admiral, Ubuntu 26.04 / L4T R39.2.1" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      co.admrl.workload="unitree-g1"
ENV LANG=C.UTF-8

# Install Ubuntu application dependencies only. NVIDIA package maintainer
# scripts and their dependency resolver must never install a second driver.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tini openssh-server lsb-base init-system-helpers ca-certificates curl jq python3 \
        iproute2 iputils-ping procps less nano strace v4l-utils alsa-utils usbutils \
        libdrm2 libegl1 libgles2 libglib2.0-0t64 libexpat1 libasound2t64 \
        libwayland-client0 libwayland-egl1 libx11-6 libxcb1 libxext6 \
        libgstreamer1.0-0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad gstreamer1.0-tools \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && groupadd --gid 28 admiral-video \
    && useradd --create-home --shell /bin/bash --groups admiral-video,dialout,plugdev unitree-ssh \
    && mkdir -p /root/.ssh /home/unitree-ssh/.ssh /run/sshd /var/log/unitree-g1 /opt/unitree-g1 \
    && chmod 0700 /root/.ssh /home/unitree-ssh/.ssh

COPY --from=unitree-files /out/ /
COPY --from=nvidia-files /out/ /
# Retain the vendor rule as provenance only: our camera helper implements it
# against sysfs + V4L2, including coldplug/hotplug, without a second udev daemon.
RUN mv /etc/udev/rules.d/70-unitree-realsense-rlsen0.rules /opt/unitree-g1/vendor-camera.rules

# Legacy Unitree binaries require OpenSSL 1.1; coexist with Ubuntu's OpenSSL 3.
ARG OPENSSL11_DEB_URL=https://ports.ubuntu.com/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2_arm64.deb
ARG OPENSSL11_DEB_SHA256=a697e5826bdbed1324f3cce1335ef162bf49eed433eb662c6d43e69ebc4807b2
RUN curl -fSL --retry 5 "${OPENSSL11_DEB_URL}" -o /tmp/libssl1.1.deb \
    && echo "${OPENSSL11_DEB_SHA256}  /tmp/libssl1.1.deb" | sha256sum -c - \
    && dpkg -i /tmp/libssl1.1.deb && rm /tmp/libssl1.1.deb

COPY scripts/start-unitree-g1 scripts/unitree-g1-status scripts/unitree-g1-camera.py scripts/unitree-g1-check.py scripts/unitree-g1-network.py /usr/local/bin/
COPY config/ /opt/unitree-g1/config/
COPY config/000-admiral-nvidia.conf /etc/ld.so.conf.d/000-admiral-nvidia.conf
COPY ssh/sshd_config /etc/ssh/sshd_config
# Snapshot of https://github.com/alexanderturner.keys, requested by the owner.
COPY ssh/authorized_keys /root/.ssh/authorized_keys
COPY ssh/authorized_keys /home/unitree-ssh/.ssh/authorized_keys
COPY README.md /opt/unitree-g1/README.md
COPY docs/ /opt/unitree-g1/docs/
RUN touch /root/.ssh/authorized_keys /home/unitree-ssh/.ssh/authorized_keys \
    && chmod 0755 /usr/local/bin/start-unitree-g1 /usr/local/bin/unitree-g1-status \
        /usr/local/bin/unitree-g1-camera.py /usr/local/bin/unitree-g1-check.py \
        /usr/local/bin/unitree-g1-network.py \
    && printf '#!/bin/sh\nexec /usr/local/bin/unitree-g1-camera.py run >>/var/log/videohub-warmup.log 2>&1\n' > /unitree/module/video_hub_pc4/start_videohub.sh \
    && chmod 0755 /unitree/module/video_hub_pc4/start_videohub.sh \
    && chmod 0600 /root/.ssh/authorized_keys /home/unitree-ssh/.ssh/authorized_keys \
    && chown -R unitree-ssh:unitree-ssh /home/unitree-ssh/.ssh \
    && ldconfig \
    && dpkg-query -W > /opt/unitree-g1/runtime-packages.txt \
    && printf 'Ubuntu 26.04 aarch64 / NVIDIA L4T 39.2.1 multimedia\nImage version: %s\n' "$IMAGE_VERSION" > /opt/unitree-g1/build-info.txt \
    && printf '\nDiagnostics: unitree-g1-status inspect\nReadiness: unitree-g1-status check\n' > /etc/motd

WORKDIR /opt/unitree-g1
EXPOSE 22/tcp
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/start-unitree-g1"]
