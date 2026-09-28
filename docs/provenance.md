# Binary provenance and inspected UPKs

## Unitree's base ZIP

[Unitree's G1 developer FAQ](https://support.unitree.com/home/en/G1_developer/FAQ)
links a public [NX patch ZIP](https://oss-global-cdn.unitree.com/static/ad3297c5c9bb40368c3e0c9febefa375.zip),
`g1plus_pc4_unitree_install.zip`, SHA256
`9bb545ba6b90d4477843044c780d4646fb8a543467082ae910fc83d598962765`.
It includes `/unitree/module/master_service/master_service`,
`/unitree/ota/pipe/ota_pipe_service`, `/unitree/sbin/{mscli,ota_pipe_cli}`,
`/etc/init.d/{master_service,ota_pipe}`, module metadata and config. These
are AArch64 ELF binaries; `master_service` needs `libcrypto.so.1.1`.
The original `install` script installs SysV services via `update-rc.d` and
calls `systemctl daemon-reload`. The OCI image stages its files and runs
the retained service manager via a tiny entrypoint instead of running systemd.
The final image strips the OTA executable/CLI/configuration and its update hooks;
the list above describes the source archive, not the deployed component set.

## Community PC4 UPKs supplied in this repo's ignored directory

The [unitree-jetpack instructions](https://github.com/legion1581/unitree-jetpack/blob/g1/docs/unitree-stack.md)
link [this public Yandex share](https://disk.yandex.com/d/hDJ2DQMlDnoB2g).
The user's copies live locally under `Upks for unitree_jetpack `; neither
the UPKs nor decrypted binaries are added to git. Two files are selected:

| Module | File in share | SHA256 |
|---|---|---|
| Patch 1.0.0.6 for Ubuntu 24.04 | `7.2-noble/unitree_patch_pc4_1.0.0.6-g1jp-noble.upk` | `33c08e002fce0273b729bd24706614aa2221cef5481dc7d8a2ff6c0d344f605d` |
| Video hub 1.0.1.1 | `common/video_hub_pc4_1.0.1.1-g1jp.upk` | `de8b0815297bf5556b6fd7b2bed58d8a229f608b4227c1908bdebe48dbe23ea9` |

They are Unitree `UTPK` containers: a 112-byte header naming the package,
`TEA\0` marker, and encrypted tar payload with an MD5 **checksum**. The
header's checksum is not a signature/authentication mechanism; the pinned
whole-file SHA256 is used to ensure we build from the specific inspected
artifacts. `scripts/unpack-upk.py` implements the format using Python's
standard library, based on the key schedule documented by
[attify's UTPK parser](https://github.com/attify/firmware-analysis-toolkit/blob/14bb33554cdd996a96d3ef252ab0986e3d67765c/crates/fat_package/src/unitree_upk.rs)
and [UniTEABag](https://github.com/Bin4ry/UniTEABag). It checks that the
archive's files correspond to the declared *module.json* file list and
only copies the declared payload, never runs install commands from it.

**What's in the video UPK:** `videohub_pc4` AArch64 executable,
`start_videohub.sh` with a D435i camera warmup loop, a CycloneDDS XML
binding to `eth0`, a master_service service JSON, the real
`libddsc.so.0` (~7.6 MB), and a udev rule for `/dev/rlsen0`. The embedded
pipeline uses `v4l2src` and NVIDIA `nvvidconv`/`nvv4l2h264enc`/`nvjpegenc`;
H.264 also goes to `230.1.1.1:1720`.

**What's in the Noble patch UPK:** updated CLI and OTA files, supervisor
config and a chrony setup script/service. One upstream `module.json`
FileList byte-count is stale: `chrony_setup.sh` is **1998 bytes** in this
specific pinned archive but its metadata says **1629**. The unpacker
permits only this known exception; the entire UPK is still SHA256 checked.

The module packages are provided by a community mirror, not Unitree's
official FAQ (which says contact support for newer Patch/Video Hub PC4).
The GitHub repository and GHCR image are private. On-device capture
(`capture/README.md`) can later compare these files against a real G1.

## Admiral Clean slate adaptation (2026-09-27)

The deployed rootfs now uses Ubuntu **26.04**, pinned in `Dockerfile` to the
official OCI index digest
`sha256:da6fc2be547864451aa253836dd926da33623312df4a9a243e35dc877c378a78`.
The community **Noble** patch is retained as the pinned source of the vendor
binaries/configuration; its name is not the target Ubuntu version. Its chrony
installer is not executed. ARM64 startup and loader tests validate the migrated
userspace, with hardware acceptance tracked separately.

`config/nvidia-packages.json` is the authoritative NVIDIA application-package
lock: R39.2.1 GStreamer, multimedia, multimedia-utils, NvSci, Ada runtime,
selected core multimedia helpers, and the nvJPEG/CUDA runtime dependencies.
The SHA256 values come from NVIDIA's official
[common package index](https://repo.download.nvidia.com/jetson/common/dists/r39.2/main/binary-arm64/Packages.gz)
and [Orin SOM package index](https://repo.download.nvidia.com/jetson/som/dists/r39.2/main/binary-arm64/Packages.gz).
These packages are available separately; a full BSP tarball is unnecessary.
CUDA 13.2 packages in the Jetson index use the `targets/sbsa-linux` archive
layout. Only their runtime libraries are copied, not driver/development packages.

`stage-nvidia.py` checks hashes and Debian package identity, extracts into a
staging directory, then copies an explicit userspace subset plus package
licenses. It never executes NVIDIA package scripts. The three required
GStreamer plugins are selected, excluding unrelated CSI/Argus/SIPL plugins.
The NVIDIA V4L2 dispatcher is selected through the loader configuration.
`nvidia-l4t-multimedia-nvgpu` supplies `libtegrav4l2.so`,
`libv4l2_nvvideocodec.so`, and its discovery link under `libv4l/plugins/nv`.
These are needed for encoding even when `gst-inspect` registers the encoder.
The pinned `nvidia-l4t-init` package contributes only license material and
`99-tegra-devices.rules` as a reference under `/opt/unitree-g1`; its systemd
services, host rules and maintainer scripts are not installed or executed.
The workload explicitly implements its guarded NVENC dispatch-node rule.

Local modifications remove the entire runtime OTA path (service, CLI, update
payloads, live and backup configuration, and startup hooks), replace camera
startup with our supervisor wrapper, and retain the original udev rule as
provenance instead of installing it as a host rule. Build-only UPK extraction
tools are not copied to the final image.
Module metadata continues to record the original module versions; the OCI
image version and repository revision identify these adaptations.

`tests/nvidia-driver-packages.json` locks four driver-containing packages for
**test fixtures only**. `tests/stage-driver.py` selects the 25 libraries from
Admiral's inspected driver manifest and mounts them in a disposable container
to exercise actual plugin loading. Those fixture files are excluded from the
build context and never copied into the released rootfs.

The inherited OpenSSL 1.1 dependency is a pinned legacy compatibility package.
It is not a supported replacement for Ubuntu's OpenSSL 3 or evidence that the
closed Unitree binaries receive current security fixes. Keep its provenance
visible and seek a vendor rebuild when updating the stock module set.
