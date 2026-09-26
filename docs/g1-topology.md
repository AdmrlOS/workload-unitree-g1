# G1 hardware topology (as understood for this workload)

The Unitree G1 EDU carries **two Jetsons**, and this workload targets only
one of them:

| Board | Role | Locked down? | This workload? |
|---|---|---|---|
| Main onboard computer | Motion control, locomotion, low-level sport/state services, safety-critical loops | Yes — Unitree-locked, not user-flashable | **No** — out of scope, never touched |
| Second Jetson Orin NX ("user workload board") | Runs the Unitree **PC4** service stack (`master_service`/`ota_pipe`/`video_hub` camera) out of the box; intended for user extension | No — this is exactly what `legion1581/unitree-jetpack` (branch `g1`) flashes | **Yes** — this repo captures and re-hosts that board's stack as an Admiral OCI workload |

This matches JetPack **7.2** / L4T **39.2.0** / kernel **6.8.12-tegra**,
Ubuntu 24.04 — the point release `legion1581/unitree-jetpack` ships for the
G1 carrier, and the same 6.8 Tegra kernel line Admiral builds. Admiral's
device-tree/kernel/firmware for the Orin NX needs to match this generation
(`tegra234`, R39.2.x) for the driver injection contract described in
[Jetson Orin CUDA](https://docs.admrl.co/core-concepts/jetson-orin-cuda) and
the L4T multimedia libraries this image pins to line up.

## Network

- The user-workload board gets a static **`192.168.123.164/24`** on its
  wired NIC (`enP8p1s0` under stock JetPack 7.2, renamed `eth0` by
  `unitree-jetpack`'s `80-rootfs-ifnames.sh` patch). This is the same
  point-to-point LAN segment the locked motion computer and any operator
  station sit on (Unitree's convention puts the main computer around
  `192.168.123.161`).
- `video_hub_pc4` publishes camera frames over **CycloneDDS**, multicast
  group **`230.1.1.1`** on that same `eth0` — confirmed live in
  `legion1581/unitree-jetpack`'s `74-rootfs-cyclonedds.sh` patch notes.
- **Neither of these is something this container configures.** The static
  IP is an Admiral OS / fleet network setting on the physical NIC (host
  network namespace); the container just needs `hostNetwork: true` to see
  it and to multicast on it. See `admiral-mapping.md`.

## Camera

`video_hub_pc4` drives the G1 head camera through NVIDIA's L4T hardware
GStreamer plugins (`nvv4l2h264enc`/`nvvidconv`/`nvjpegenc`) against V4L2 /
NVMM buffers — standard Jetson ISP pipeline, not a USB UVC webcam. Exact
`/dev` nodes needed (V4L2 `/dev/video*`, plus whatever ISP/VI device nodes
the L4T camera driver stack uses) should be confirmed against
`unitree-g1-status camera` output on the real board; this is one of the
open risk items in the top-level README.
