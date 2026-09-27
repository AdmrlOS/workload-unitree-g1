# Unitree G1 Clean slate for Admiral

A reusable **Ubuntu 26.04 / linux/arm64** base for the G1 EDU user-workload
Jetson Orin NX (PC4), targeting an **Admiral G1 BSP with NVIDIA L4T R39.2.1**.
It supplies the PC4 service manager and stock camera userspace, plus a supervised
entrypoint for your application. Applications extend a released image **by
immutable digest** and deploy their resulting OCI image through Admiral.

**Start here: [Building applications on the Clean slate](docs/clean-slate.md).**
This covers `FROM`, dependencies, robot communication, computer vision, local
development, publishing, deployment, persistence and base-image upgrades.

## Included

- Unitree `master_service`, patch **1.0.0.6**, video hub **1.0.1.1**,
  and the exact vendor CycloneDDS runtime. Runtime OTA has been removed;
  Admiral deploys and rolls back complete OCI images.
- Workload-owned D435i RGB discovery and `/dev/rlsen0` naming, frame warmup,
  USB reconnect handling and video-process recovery. No host udev rule or
  second udev daemon is required.
- Pinned R39.2.1 GStreamer, multimedia, NvSci and VIC libraries, plus the
  CUDA runtime/nvJPEG libraries needed by the JPEG plugin. Admiral injects
  the GPU driver; no competing GPU driver is bundled.
- Service supervision, optional user-application `CMD`, graceful shutdown,
  startup checks and diagnostics. A failed app exits the primary process so
  Admiral can restart it. No movement commands run at boot.
- Key-only SSH on port 22, with **empty authorized-key files by default**.
  Add your own keys in a child image; the repository's legacy example keys
  are no longer copied into the shared base.

## Build and test

```sh
python3 scripts/fetch-unitree-assets.py
# Or use the existing downloaded UPKs:
# python3 scripts/fetch-unitree-assets.py --source-dir 'Upks for unitree_jetpack '

docker buildx build --platform linux/arm64 --load -t unitree-g1:local .
python3 -m unittest discover -s tests -v
bash tests/smoke-image.sh unitree-g1:local
```

Unitree artifacts and NVIDIA packages are verified by SHA256. The Ubuntu
base is digest-pinned. Ubuntu apt dependencies are resolved at base-build time
and recorded in `/opt/unitree-g1/runtime-packages.txt`; base builds are **not
claimed to be byte-for-byte reproducible**. Promote one tested base digest,
then reuse that exact artifact for application builds. See
[provenance](docs/provenance.md) and the [review record](docs/review.md).

CI builds on native ARM64 and publishes the image; it does not start the
workload or run readiness tests. Optional local checks, including a disposable
NVIDIA driver fixture, are described in [validation](docs/validation.md).

## Deploy

Use [the Admiral configuration](docs/admiral-mapping.md), keeping Command
empty, `isolateDevices: false`, `hostNetwork: true`, `interactive: false`, and
`readOnlyRoot: false`. The robot NIC must be `eth0`, `192.168.123.164/24`.
See the [G1 BSP contract](docs/bsp-handoff.md) for hardware, firmware and time.

`unitree-g1-status` is supplied by this image at `/usr/local/bin/unitree-g1-status`.
Run it **inside the deployed workload**, using a workload shell or its SSH service.
It is not a kernel utility and need not exist on the Admiral host:

```sh
unitree-g1-status inspect
unitree-g1-status check
```

**Hardware acceptance is still required.** A successful build or plugin-load
test does not prove NVENC/VIC/JPEG execution, D435i cold boot/reconnect, robot
app video reception, PC1 DDS interoperability, audio or clock synchronization.
Use the [acceptance procedure](docs/validation.md) before promoting a base as
an approved golden master. No robot was connected during this review.
