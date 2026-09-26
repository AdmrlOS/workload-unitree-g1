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
those services via a tiny entrypoint instead of running systemd.

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
