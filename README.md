# workload-unitree-g1

Admiral OCI userspace for the **G1 EDU's user-workload Jetson Orin NX**:
Unitree PC4 `master_service`, `ota_pipe`, patch 1.0.0.6 and
`video_hub_pc4` 1.0.1.1. Built from published binary packages; **no G1
board is needed to assemble the image**. Admiral supplies the kernel,
device tree, firmware, GPU driver and host device nodes; this image
supplies the application userspace.

## Where the software comes from

- Unitree's [official G1 developer FAQ](https://support.unitree.com/home/en/G1_developer/FAQ)
  links the [PC4 base bootstrap ZIP](https://oss-global-cdn.unitree.com/static/ad3297c5c9bb40368c3e0c9febefa375.zip)
  (`master_service`, `ota_pipe`, CLIs and init scripts).
- The [unitree-jetpack G1 stack guide](https://github.com/legion1581/unitree-jetpack/blob/g1/docs/unitree-stack.md)
  links a [community-hosted UPK share](https://disk.yandex.com/d/hDJ2DQMlDnoB2g).
  For JetPack 7.2 this image selects `7.2-noble/unitree_patch_pc4_1.0.0.6-g1jp-noble.upk`
  and `common/video_hub_pc4_1.0.1.1-g1jp.upk`. The locally downloaded folder
  `Upks for unitree_jetpack ` (including its trailing space) is **ignored by
  git**. `scripts/fetch-unitree-assets.py` verifies SHA256 before staging
  either local copies or fresh downloads; CI downloads the same files.
- `scripts/unpack-upk.py` validates UTPK header, encrypted-payload checksum,
  package name and module file list before installing the declared module
  files. It does not run the UPKs' `systemctl` or `udevadm` install commands;
  those target a different OS layout. The UPK itself supplies the exact
  `libddsc.so.0` that `videohub_pc4` uses; no substitute DDS build is needed.

See [provenance](docs/provenance.md) for hashes, archive contents and format.

## Build locally

```sh
# Use the downloaded folder already in this repo (note the trailing space):
python3 scripts/fetch-unitree-assets.py --source-dir 'Upks for unitree_jetpack '
# Or fetch the same SHA256-pinned UPKs from the public share:
# python3 scripts/fetch-unitree-assets.py

docker buildx build --platform linux/arm64 --load -t unitree-g1:local .

# Verify module metadata and direct ELF dependencies without any robot:
docker run --rm --platform linux/arm64 --entrypoint /bin/sh unitree-g1:local \
  -c 'cat /unitree/robot/pkg/version/version.json && ldd /unitree/module/video_hub_pc4/videohub_pc4'
```

The bootstrap ZIP, `.upk` files and staging directory `artifacts/` are
ignored by git. The Dockerfile checks their hashes *again*. A private
GitHub Actions [CI build](.github/workflows/ci.yml) builds the **real**
image; [publish](.github/workflows/publish.yml) pushes linux/arm64 images
to `ghcr.io/admrlos/workload-unitree-g1`. Neither workflow requires a board
or capture secrets. The registry package must remain **private**; verify
package visibility before sharing the image with anyone else.

## What the G1 needs from Admiral / BSP

- BSP: load USB3/`uvcvideo` for the **Intel RealSense D435i** (`8086:0b3a`)
  and install the UPK's **host udev** rule that makes `/dev/rlsen0` from
  its RGB capture `/dev/videoN`. The camera is USB/UVC, **not CSI/Argus**.
  The UPK's rule is deliberately excluded from the workload rootfs: a
  container's `/etc/udev` does not configure Admiral's host udev.
- BSP: present the Orin NX NVMM/VIC/NVENC/JPEG kernel drivers, firmware and
  device nodes for accelerated GStreamer encode. Admiral: pass host `/dev`
  through (`isolateDevices: false`). No `nvidia-smi` or `/dev/nvidia0`.
- Network: provide the wired robot NIC as `eth0`, configured
  `192.168.123.164/24` on the **host**. Use `hostNetwork: true`: the bundled
  CycloneDDS config and the H.264 UDP multicast output hardcode `eth0`, and
  the latter sends to **230.1.1.1:1720**.

The exact host rule, device checks and division of BSP versus image
responsibilities are in [docs/bsp-handoff.md](docs/bsp-handoff.md).
The [Admiral configuration](docs/admiral-mapping.md) covers deployment.

## Current validation boundary

**The real UPKs build and the base Unitree services start in a local arm64
container**: `master_service`, `ota_pipe` and `mscli listservice` respond,
and the service manager registers `video_hub_pc4`. That does **not** prove
camera streaming. Today, `gst-inspect-1.0 nvvidconv` / `nvv4l2h264enc` /
`nvjpegenc` report missing plugins because vanilla Ubuntu plus the pinned
`nvidia-l4t-gstreamer` package lacks its matching NVIDIA L4T **multimedia,
camera and NvSci userspace dependencies**. These must be supplied in the
image from the R39.2 BSP, without adding a competing GPU driver; see
[the current gaps](docs/admiral-mapping.md#remaining-hardware-validation).
No hardware encoder/USB camera test has yet been run on Admiral OS.

An optional [on-device capture](capture/README.md) remains available to
compare a vendor-flashed board against the package-built image once a G1
is available.
