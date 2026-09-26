# Capturing the Unitree PC4 stack

The Unitree binaries under `/unitree/**` and the two LSB init scripts
(`/etc/init.d/master_service`, `/etc/init.d/ota_pipe`) are proprietary —
they come from Unitree's own CDN bootstrap (see
`legion1581/unitree-jetpack`'s `versions/7.2/patches/70-rootfs-unitree-base.sh`
and `version.env` for the exact fetch URL/hash it uses), plus whatever
module `.upk` packages (notably `video_hub_pc4`, the camera streamer) you
installed afterwards through the on-device OTA uploader. None of that is
fetched or vendored by this repo — it's captured from a real, already-booted
board instead.

## 1. Flash + provision the board (once)

Follow `legion1581/unitree-jetpack` (branch `g1`) end to end:

1. `./g1_custom_jetpack.sh -j 7.2 flash all` — flashes JetPack 7.2 / L4T
   39.2.0 (kernel `6.8.12-1021-tegra`, Ubuntu 24.04), matching what Admiral
   builds for the Tegra 6.8 kernel.
2. Boot, browse to `http://192.168.123.164:8888/`, and follow
   [`docs/unitree-stack.md`](https://github.com/legion1581/unitree-jetpack/blob/g1/docs/unitree-stack.md)
   in that repo: install `unitree_patch_pc4_<version>.upk`, then
   `video_hub_pc4_<version>.upk`. Confirm `video_hub_pc4` shows `running` in
   the uploader's Services panel and the camera stream is actually up.

Do this on the real G1 user-workload Jetson (or an identical off-robot Orin
NX dev unit) — the whole point of a capture build is that we're snapshotting
a board that Unitree's own tooling has already verified is working, not
re-deriving it from documentation.

## 2. Capture

```bash
scp capture-unitree-g1.sh unitree@192.168.123.164:~
ssh unitree@192.168.123.164
sudo ./capture-unitree-g1.sh
exit
scp unitree@192.168.123.164:~/unitree-g1-rootfs.tar.zst .
scp unitree@192.168.123.164:~/MANIFEST.txt .
```

This produces `unitree-g1-rootfs.tar.zst` (the `/unitree` tree + the two
init scripts) and `MANIFEST.txt` (dpkg list, module versions, `mscli
listservice` output — provenance for the image, and your first thing to
check if a rebuilt image behaves differently than the captured board did).

Both files are git-ignored — never commit Unitree's proprietary binaries.

## 3. Build

```bash
docker buildx build --platform linux/arm64 --load \
  -t <you>/workload-unitree-g1:2026-09-26-pc4-r39.2.0-r1 .
```

The Dockerfile fails fast (`test -x .../master_service`) if the tarball is
missing or empty.

## 4. Verify before trusting the image

`docker run` on non-arm64 hardware **cannot** validate this end to end —
there's no camera, no `/dev/nvhost*`, no CycloneDDS peer on the far side of
`eth0`. At minimum, locally:

- `unitree-g1-status inspect` runs without `ldd`-reported missing libraries
  (`libcrypto.so.1.1`, `libssl.so.1.1`, `libddsc.so.0` should all resolve).
- The `cyclonedds-build` stage's SONAME assertion passed (build fails loudly
  otherwise) — but that only proves *we* built the right SONAME, not that
  the wire protocol/ABI matches whatever CycloneDDS revision Unitree
  actually linked `video_hub_pc4` against. Confirm on real hardware that
  `video_hub_pc4` starts cleanly and a DDS subscriber on
  `192.168.123.161` (or wherever the locked motion computer sits on this
  robot's DDS domain) actually receives frames.
- `mscli listservice` inside the container matches the `MANIFEST.txt`
  captured from the source board.

Then deploy through Admiral to the real board and re-run
`unitree-g1-status inspect` there — see `docs/admiral-mapping.md` for the
Configuration this needs (`isolateDevices: false`, `hostNetwork: true`,
etc.) and `README.md` for the full risk list.
