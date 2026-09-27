# Building G1 applications on the Clean slate

## The recommended model

Maintain this repository as the **Clean slate platform base**. After G1
hardware acceptance, promote its image digest as an approved golden master.
Each application lives in its own repository and has a small Dockerfile
starting with `FROM ghcr.io/admrlos/workload-unitree-g1@sha256:...`.

Build that application's image in CI, push it to a registry, and select the
new image digest in Admiral. The G1 receives one complete userspace containing
both the robot integration and the application. Developers do not maintain a
Jetson rootfs, install robot drivers, run Docker on the robot, or SSH-copy code
into a deployed container. Admiral continues to own the immutable platform.

```text
G1 Admiral BSP: carrier + kernel + firmware + R39.2.1 GPU driver
    ↓ hardware access and driver injection
Clean slate image: Ubuntu 26.04 + PC4 services + camera/multimedia + supervisor
    ↓ FROM <approved digest>
Application image: your code + locked libraries/models + CMD
    ↓ push image, deploy its digest in Admiral
One supervised userspace on the G1 user-workload Jetson
```

The base changes infrequently. Application images can change on every commit.
Registry layers are shared, so small application changes need not reproduce
the integration layer. A base update becomes an explicit application dependency
update, with tests and a rollout, rather than changing under existing robots.

## What PC4 means, and what replaces UPK updates

PC4 is the physical user-workload Jetson Orin NX. It still runs camera/video
services and your application. Admiral replaces its original host OS; the OCI
image supplies its application userspace. This does not replace PC1 or its
motion-control firmware. Your application talks to PC1 over the robot Ethernet
network using Unitree SDK2 / CycloneDDS (see the movement section below).

UPKs are now **build inputs only**: checksum-pinned archives from which CI
extracts the vendor binaries and configuration. We build the complete image
ourselves, but Unitree's proprietary camera and service-manager binaries are
not rebuilt from source. A future vendor update means reviewing new pinned
inputs, rebuilding the base, then rebuilding and deploying the application.
No UPK installer, OTA server or OTA CLI is shipped in the runtime image.
Unitree-app PC4 update/version-query features that rely on that OTA service
are intentionally unavailable. Local version provenance remains available via
`unitree-g1-status modules`; robot control and video acceptance are separate.

## Contract provided by the base

| Area | Contract |
|---|---|
| CPU / userspace | `linux/arm64`, Ubuntu 26.04, glibc, system Python 3.14 |
| Platform pairing | G1-specific Admiral BSP, L4T 39.2.1 NVGPU |
| PC4 modules | master_service, patch 1.0.0.6, video hub 1.0.1.1; no runtime OTA |
| Camera | D435i RGB, workload-owned `/dev/rlsen0`, warmup and reconnect handling |
| NVIDIA video | `nvvidconv`, `nvv4l2h264enc`, `nvjpegenc`; matching multimedia/NvSci/VIC and JPEG runtime |
| Robot LAN | Host networking, `eth0`, PC4 `192.168.123.164/24` |
| Entry process | `tini` → `start-unitree-g1` → vendor services and optional application |
| Application command | Child Dockerfile exec-form `CMD`; inherited `ENTRYPOINT` remains |
| Default application directory | `/opt/app`, explicitly selected at startup |
| Application identity | Optional `UNITREE_APP_USER`; actual privilege drop uses setpriv/initgroups |
| Durable data convention | `/var/lib/robot-app`, on an Admiral custom volume |
| Diagnostics | `unitree-g1-status inspect`, `platform`, `check`; camera JSON under `/run/unitree-g1` |

The base is a **PC4 software foundation**, not the motion-control computer's
firmware, a complete ROS distribution, a development SDK image, or a promise
that all G1 accessories are supported. Depth/IMU capture, ROS, CUDA frameworks,
model runtimes and your control policy belong in application layers. Keep the
stock color-camera stream available unless your application deliberately
replaces its ownership and passes a different acceptance test.

## Create your first application

The working starter is [examples/camera-receiver](../examples/camera-receiver).
It joins the stock H.264 multicast stream and reports packet counts. It does
not access the USB camera directly or command the robot. It uses only Python's
standard library, so there are no floating Python dependencies.

Its Dockerfile is deliberately small:

```dockerfile
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
RUN useradd --uid 10001 --create-home --groups admiral-video robot-app \
    && mkdir -p /opt/app /var/lib/robot-app \
    && chown robot-app:robot-app /var/lib/robot-app
COPY --chown=robot-app:robot-app app.py /opt/app/app.py
ENV UNITREE_APP_USER=robot-app UNITREE_APP_DIR=/opt/app
CMD ["/usr/bin/python3", "-u", "/opt/app/app.py"]
```

Use the actual approved registry digest, not the illustrative placeholder:

```sh
BASE_IMAGE='ghcr.io/admrlos/workload-unitree-g1@sha256:REPLACE_WITH_APPROVED_DIGEST'
APP_IMAGE='ghcr.io/YOUR_ORG/g1-camera:git-REPLACE_WITH_COMMIT'
docker login ghcr.io

docker buildx build --platform linux/arm64 \
  --build-arg BASE_IMAGE="$BASE_IMAGE" \
  --tag "$APP_IMAGE" --push examples/camera-receiver

docker buildx imagetools inspect "$APP_IMAGE"
```

Record the published application digest from the output. Deploy that digest
through Admiral using [the configuration guide](admiral-mapping.md). Leave the
Admiral **Command field empty**: it must use the base entrypoint plus your CMD.
A Command override replaces both and bypasses the robot startup sequence.

For routine development, the only recurring steps are: edit code, test it,
build/push a new commit-tagged image, then update the Admiral configuration to
its digest. The robot needs registry access, not a source checkout or compiler.
A GitHub Actions build can use `docker/build-push-action` with the same
`platforms`, `build-args`, and tag; registry credentials belong in CI secrets
and Admiral registry configuration, never in the Dockerfile.

## How application startup behaves

The base verifies the platform and starts Unitree's service manager. It
then executes your CMD in its own process group. The camera manager may still
be waiting for USB or warming up: apps must retry connections and tolerate
camera gaps. Use the camera state or your first received frame when a feature
requires vision; do not interpret process startup as frame readiness.

Keep your main process in the foreground. If it exits, including exit code
zero, the entrypoint exits with failure so Admiral restarts the complete
userspace. On SIGTERM, the base signals the application process group and
stops the vendor services. Your app should close cameras/sockets, flush state
and stop promptly; it has about five seconds before the base forces its exit.
Allow about 25 seconds for the full userspace shutdown.

Application configuration:

| Variable | Default | Use |
|---|---|---|
| `UNITREE_APP_DIR` | `/opt/app` | Working directory for the child CMD |
| `UNITREE_APP_USER` | unset (root) | Named/numeric existing account to run the app as |
| `UNITREE_CAMERA_SERIAL` | unset | Select one D435i if several match |
| `UNITREE_WATCHDOG_INTERVAL` | `5` | Positive integer seconds between service checks |
| `UNITREE_HARDWARE_CHECKS` | `1` | `0` permits hardware-free development; never a production readiness setting |

Prefer an unprivileged application account. The base's `admiral-video` group
has numeric GID **28**, matching Admiral's GPU permissions. Dockerfile `USER`
does not set Admiral's entry-process identity, so use `UNITREE_APP_USER` to
perform the actual drop. Add other numeric device groups only if the app
needs them. DDS and camera multicast do not need direct motor/serial devices.

Do not replace `ENTRYPOINT` with your app or start another copy of the
vendor services. To run several application processes, use a small foreground
application supervisor as CMD and propagate failures and SIGTERM correctly.

## Deterministic application dependencies

Pin the base digest in a committed file or your application Dockerfile. Also
lock your application source revision, packages, model weights and SDK source.
A complete release record contains base digest, app commit, dependency lock,
model hashes, application image digest and compatible BSP release.

For Python, create an application-specific venv and install a lockfile with
exact versions and wheel/source SHA256 values. Build wheels ahead of time for
ARM64/Python 3.14 and store them in your controlled artifact repository. Install
with `pip --require-hashes` (and `--no-index` with that wheelhouse) during the
image build. Include transitive dependencies in the lock. Never `pip install`
on the robot at startup. Keep venv paths under `/opt/app`, and invoke its Python
explicitly in CMD. Install the required venv/build tooling in a build stage.

For C++, compile in a build stage pinned to the same Ubuntu/base release. Copy
only the executable and required private libraries into the final application
stage. Pin SDK2 to a full commit and verify any downloaded archives by hash.
Use a private prefix such as `/opt/app/sdk` and an application RPATH or wrapper
for its library directory. Do not install an SDK's CycloneDDS over the base's
`/usr/lib/aarch64-linux-gnu/libddsc.so.0`: the vendor video hub needs its exact
binary. An app-specific library path must be set in the app wrapper, **not**
as a global Dockerfile `LD_LIBRARY_PATH` affecting all Unitree processes.

The [official Python SDK](https://github.com/unitreerobotics/unitree_sdk2_python)
currently declares CycloneDDS 0.10.2. That does not establish support for
Ubuntu 26.04's Python 3.14. Test and lock that combination before publishing
a Python robotics profile; alternatively package a supported Python interpreter
privately for that app. The dependency-free starter is tested; a Unitree SDK,
ROS, PyTorch or TensorRT application is a separate integration to validate.

For computer vision/AI, use Jetson-compatible application libraries matched
to the BSP. The base contains the CUDA runtime required by its JPEG path,
not a full CUDA toolkit/cuDNN/TensorRT/PyTorch environment. Adding a framework
must not pull in libcuda, NVIDIA kernel packages, a toolkit driver stub, or
a second driver injector. Run `unitree-g1-check.py image` during your child
build to detect driver collisions and regressions in the base video libraries.

The base's Ubuntu digest and vendor/NVIDIA artifacts are pinned. Its Ubuntu
apt packages are recorded but resolved from the live archive at base-build
time. Thus **using the approved base digest is deterministic; rebuilding the
base from source at an arbitrary later date is not bit-reproducible**. Use an
apt snapshot and package lock if exact base reconstruction is required.

## Movement control: IP, DDS and SDK2

Yes: applications on this Jetson reach the robot control computer through
the internal wired **Ethernet/IP network**. Unitree SDK2 exposes
CycloneDDS channels and DDS-backed request/response clients. The application's
normal interface is an SDK client or DDS topic, not a direct CAN/UART motor
connection and not an HTTP endpoint at PC1.

The vendor PC4 address is `.164`; its time configuration identifies PC1 at
`192.168.123.161`. Confirm the board addressing for your robot revision. SDK2
initializes DDS **domain 0 on `eth0`**, discovers peers, and addresses named
services/topics. Preserve multicast and unicast UDP connectivity on that LAN.
NAT, binding the SDK to Wi-Fi/loopback, or mismatched DDS/domain settings can
break discovery despite a successful ping.

Two interfaces serve different applications:

| Interface | Intended use | Integration |
|---|---|---|
| G1 `LocoClient` | High-level locomotion requests; PC1 retains its locomotion controller | SDK methods including state queries, stand and velocity requests |
| G1 low-level DDS | Applications implementing joint-level control | `rt/lowstate` / `rt/lowcmd`, G1 `unitree_hg` message types; control-mode ownership, timing and CRC obligations |

Start by reading state. This is the essential shape of a C++ SDK2 connectivity
check, to compile against your pinned SDK2 version:

```cpp
#include <iostream>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/loco/g1_loco_client.hpp>

int main() {
    unitree::robot::ChannelFactory::Instance()->Init(0, "eth0");
    unitree::robot::g1::LocoClient client;
    client.Init();
    client.SetTimeout(5.0f);
    int state = 0;
    const auto result = client.GetFsmId(state);
    if (result != 0) return 1;
    std::cout << "G1 FSM: " << state << '\n';
}
```

This example queries state only; it does not activate motion. Available APIs
and required robot modes depend on the G1 firmware/EDU configuration. For
movement applications, use an explicit operator activation step, finite command
durations and a tested stop-on-loss-of-input policy. Do not automatically replay
movement after Admiral restarts an application. Low-level control must follow
Unitree's documented controller handoff; it is not a drop-in replacement for
high-level locomotion. No controller handoff or movement is performed by the base.

Primary references: [SDK2](https://github.com/unitreerobotics/unitree_sdk2),
[G1 locomotion example](https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/g1/high_level/g1_loco_client_example.cpp),
[LocoClient API](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/g1/loco/g1_loco_client.hpp),
[G1 low-level example](https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/g1/low_level/g1_ankle_swing_example.cpp).
Some upstream examples actively move the robot; they are source references,
not acceptance commands to run indiscriminately.

## Camera and computer vision applications

The stock video hub owns D435i RGB capture through `/dev/rlsen0`. It uses
YUY2 1920×1080 at 15 fps, NVIDIA conversion/encoding, and sends H.264 over
**UDP multicast `230.1.1.1:1720`** on `eth0`. That multicast group is the
video stream, not the DDS discovery address. JPEG is also part of the vendor
pipeline; use the G1-specific SDK/API that matches the robot firmware when
consuming it.

Prefer subscribing to the existing video output so the robot's stock app and
your perception app can coexist. The starter verifies UDP arrival only. For
actual vision, add a decoder and feed decoded frames to your model. Verify
the actual payload framing/caps on hardware before assuming RTP versus raw
H.264, and measure decoded frame rate, latency and camera reconnect recovery.
Same-board multicast reception also depends on the vendor sender's loopback
behavior; confirm it on the G1 before relying on local subscription.

Opening `/dev/rlsen0` a second time for streaming can conflict with video hub.
If your application must own raw RGB, intentionally replace the camera service
with one capture process that distributes frames to both consumers, and treat
that as a new base variant requiring stock-video acceptance. Depth/IMU through
librealsense likewise requires an explicitly tested userspace/kernel pairing;
this base only validates the stock RGB path.

## Local iteration and debugging

Build on an ARM64 machine or Docker Buildx with ARM64 emulation. Ordinary Docker
Desktop cannot prove Jetson acceleration or the G1 network/USB behavior.
For a hardware-free startup test of a built app:

```sh
docker run --rm -e UNITREE_HARDWARE_CHECKS=0 YOUR_LOCAL_APP_IMAGE
```

The starter will wait for camera packets. Test robot-specific code with a mock
or simulator until deployed on the G1. A simulator may require a different
DDS domain/interface; keep that configuration distinct from real-robot mode.

To build the starter from a local base, use a Docker builder that can see the
image in the local engine. A separate BuildKit container cannot automatically
resolve an unpushed local tag. Either choose the engine's local builder or use
a private registry digest for the base, which is the production workflow.

On Admiral, use dashboard stdout/stderr first. From a shell **inside the
workload**, `/usr/local/bin/unitree-g1-status inspect` collects process, camera,
network and library diagnostics. This repository supplies that command in the
image; neither the host OS nor the kernel must provide it. `check` returns
nonzero for unmet readiness; it still cannot prove remote frame reception.
For SSH, add only your own public key in the child Dockerfile:

```dockerfile
COPY --chmod=0600 authorized_keys /root/.ssh/authorized_keys
```

The base has no authorized keys or password login. Port 22 is on the host
network; ensure Admiral's management setup does not occupy the same port.
Provisioning durable SSH host keys can use an application-specific persistent
location, without mounting over all of `/etc/ssh` and hiding its configuration.

## Persistence, rollout and base upgrades

Put writable application state in `/var/lib/robot-app`, mounted as a custom
Admiral volume. A new volume may be root-owned: provision its ownership for
UID 10001 (or your selected UID) before a non-root writer starts. Keep code,
Python environments, SDKs and model versions in the image. Large models may
use a separate read-only managed artifact store with verified hashes.

Do not persist `/unitree`. The runtime OTA service, its CLI, pending-update
payloads, backup configuration and startup hooks have been removed. PC4 no
longer exposes the Unitree module-update endpoint on TCP 1026. All PC4 software
changes are new OCI images deployed through Admiral, with rollback to a previous
digest. Do not mount over NVIDIA driver paths or `/run`.

For every release:

1. Build/test the app against a specific approved base digest and dependency lock.
2. Publish under a unique commit/version tag and record the resolved digest.
3. Deploy to one development G1; verify diagnostics, PC1 state reads, actual
   video frames and application behavior. Explicitly activate any motion tests.
4. Roll out that digest through Admiral. Keep the previous app digest and its
   compatible BSP version available for rollback.
5. For a new base/BSP, rerun [hardware acceptance](validation.md), then update
   the application's pinned base digest in a reviewed change.

This repository's publish workflow creates candidate base images. A successful
build alone does not promote a candidate to a hardware-approved golden master.
Publication builds the image without running lifecycle or readiness tests.
Document the tested BSP, robot firmware and hardware evidence alongside the
approved digest. Publish reusable SDK/CV variants only after their additional
compatibility tests pass; ordinary applications should inherit the smallest
approved variant that contains their needs.
