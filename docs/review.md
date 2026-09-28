# Clean slate review — 2026-09-27

## Target and evidence

Requested target: an Admiral BSP built for the G1 EDU user-workload Orin NX,
NVIDIA **L4T R39.2.1**, with **Ubuntu 26.04** application userspace. This review
covers this repository and the public community/vendor sources; no G1 was
connected. Do not label the candidate hardware-approved until the
[acceptance record](validation.md) is completed on that BSP.

Sources inspected:

- [Admiral Jetson driver contract](https://docs.admrl.co/core-concepts/jetson-orin-cuda),
  [launch contract](https://docs.admrl.co/core-concepts/configurations), and
  [hardware access](https://docs.admrl.co/core-concepts/hardware-access).
- Local Admiral init `internal/workload/runtime.go` and `nvidia_platform.go`:
  shared writable `/dev`, visible USB/V4L2 sysfs, host-network option,
  root entry process, capability set, driver inventory and manifest schema.
  These are implementation observations; deployed BSP/init acceptance still
  needs to confirm the same contract.
- [unitree-jetpack g1 at f2742cf](https://github.com/legion1581/unitree-jetpack/tree/f2742cf578bc4d0754301e0de6413cbb9c29f633):
  carrier/EEPROM/USB, Wi-Fi/BT, NIC naming, PC4 bootstrap, GStreamer and stack guide.
- Actual checksum-verified bootstrap ZIP and both UPKs, their scripts,
  service definitions, DDS/network settings and ARM64 dependencies.
- NVIDIA R39.2.1 Debian package indexes and actual binaries, including
  runtime-loaded JPEG/V4L2/encoder dependencies.
- Official Unitree SDK2 G1 locomotion and low-level examples linked in the
  [developer guide](clean-slate.md#movement-control-ip-dds-and-sdk2).

## Findings and changes

| Finding | Severity / consequence | Resolution |
|---|---|---|
| Ubuntu 24.04 and R39.2.0 did not match the requested deployment | Compatibility blocker | Ubuntu 26.04 digest pin and R39.2.1 application-library lock |
| Only the NVIDIA GStreamer plugin package was installed | Camera encode could not load | Matching multimedia/NvSci/Ada/VIC userspace, NVIDIA V4L dispatcher, nvJPEG 13 and CUDA runtime; loader checks |
| Camera alias depended on a host udev rule | Unsuited to an immutable generic workload deployment | Workload implements the vendor USB/interface/capture match via sysfs/V4L2 and maintains the alias |
| Warmup eventually launched video despite failure; no USB reconnection handling | A running service could publish no frames indefinitely | Retry until 45 frames pass, monitor device identity, stop/restart on disconnect or process exit |
| Root process watched only master_service and SSH | App failure could be hidden | Watch the manager, SSH and optional foreground app; structured teardown |
| PC4 could update itself via Unitree OTA | Runtime changes diverged from the published OCI image | Remove updater, CLI, pending payloads and live/backup startup hooks; Admiral owns deployment |
| PID files survive Admiral's reused rootfs | Restart could act on stale process IDs | Remove stack-owned stale PID files before service startup |
| SSH access must be explicit | Derived apps inherit base authorized keys | Owner requested GitHub alexanderturner key on 2026-09-28; pinned snapshot installed in both accounts, inheritance documented |
| No child-image application contract | Easy to bypass robot startup with ENTRYPOINT | Exec-form child CMD, supervised process group, explicit working directory and optional privilege drop |
| ARM64 service status was checked under x64/QEMU | Vendor process inspection can misidentify a live process | Native ARM64 build; remove runtime test gates from publication as requested |
| Documentation treated workload-created device aliases as impossible | Incorrect platform boundary | Corrected BSP/OCI contract and deployment instructions |

The fixture test initially found the missing `libnvjpeg.so.13` dependency
through an actual failed `nvjpegenc` load. Static `ldd` alone did not expose
that `dlopen` dependency. The final fixture loads all three required elements.
The fixture is not a mock GPU and is not part of the shipped image.

## Local validation performed

- Built the real `linux/arm64` Ubuntu 26.04 candidate, including the existing
  pinned Unitree UPKs and all locked NVIDIA application packages.
- Passed image dependency checks and the no-bundled-driver check.
- Loaded `nvvidconv`, `nvv4l2h264enc` and `nvjpegenc` against matching R39.2.1
  driver libraries mounted into a disposable container.
- Passed device-discovery tests covering metadata/depth exclusion, serial
  selection, aliases, reconnection and child cleanup.
- Before OTA removal, started `master_service` and `ota_pipe`, registered video hub in its waiting
  state, started a supplied application CMD, stopped cleanly, restarted using
  the same rootfs, and observed workload failure when the application exited.
- Built the example derived image and ran its multicast receiver as UID 10001.
  Packet reception is tested with a synthetic packet, not a robot stream.

These local runtime checks covered the earlier candidate before the final OTA
removal. The final publishing workflow builds and pushes only, as requested;
it does not claim a fresh runtime or hardware validation result. The optional
manual checks have been updated for the image without OTA.

## Remaining hardware/platform obligations

A software pass does not prove the target kernel's NVENC/VIC/JPEG ioctls,
D435i cold-boot frame behavior, local/remote video reception, PC1 DDS exchange,
ALSA mapping or clock synchronization. The polling camera supervisor detects
USB identity/process failure but does not monitor encoded frame progress;
a later silent video stall still needs receiver-side monitoring or restart.

The inspected runtime lacks `CAP_SYS_TIME`. The G1 BSP must arrange clock
sync to the robot's time source; the bundled vendor systemd chrony installer
is deliberately not run. NVIDIA host NvSci setup remains a BSP responsibility.

The PC4 OTA protocol and runtime updater have been removed. This deliberately
removes PC4 update/version-query functionality that depends on the vendor OTA
endpoint. Admiral image deployment is the update and rollback mechanism. Ubuntu package resolution at base-build time is recorded,
not fully snapshot-locked. Child builds become deterministic by reusing the
approved base digest and locking their own dependencies.

## 2026-09-28: Orin Nano startup report

The reported `nvv4l2h264enc` failure occurred on Orin Nano, not the G1 Orin NX.
NVIDIA's pinned R39.2.1 source deliberately omits encoder registration for
Nano module IDs 3767-0003/0004/0005 because those modules lack NVENC. Passing
ELF checks or plugin registration in a hardware-free fixture does not establish
availability on a particular Jetson module.

Startup inspection now defaults to `warn`: log unmet requirements and keep
SSH/services/apps available. Strict `UNITREE_HARDWARE_CHECKS=1` and explicit
readiness still fail; no video capability is fabricated. Camera startup waits
in `blocked` when required elements are unavailable instead of launching the
vendor pipeline. No software encoder is substituted for the stock service.
The owner-requested GitHub public key is included for root and unitree-ssh.

## 2026-09-28: G1 Orin NX camera restart report

Live SSH inspection of the NX confirmed the D435i RGB capture node at
`/dev/video4`, successful warmup, registered NVIDIA plugins, and the robot
address `192.168.123.164/24` on `enP8p1s0`. PC1 `.161` routed through that
interface. The video hub failed CycloneDDS creation because its XML names
`eth0`; the proprietary binary also embeds
`multicast-iface=eth0` in its GStreamer UDP pipeline. The default route and
multicast route were on Wi-Fi, so a DDS-only XML substitution would not
establish the stock video path.

The workload now identifies the physical NIC carrying `.164/24`, renames it
to `eth0` before Unitree starts, and validates the PC1 route. It refuses to
rename a default-route interface or overwrite an existing `eth0`. This
workaround affects Admiral's host network namespace and briefly interrupts
the PC1 link; on failure it keeps SSH available and camera state `blocked`.
The live host network was not manually renamed during development; the new
image must be validated after deployment. The VictoriaLogs
`missing _msg field` and Admiral's headless screen-capture warning are separate
logging/UI messages, not causes of the video hub exit.

## 2026-09-28: SSH plugin inspection on the live Nano

The running workload was reachable over SSH and master_service responded.
`nvvidconv` and `nvjpegenc` nevertheless appeared missing in SSH diagnostics.
Direct inspection found `libcuda.so.1` unresolved when `LD_LIBRARY_PATH` was
unset: this deployed Admiral version exposed the driver under `/run/admiral`
and `/run/admrl`, but did not bind it into the standard multiarch library path.
Both plugins registered successfully when given the injected path explicitly.

The image now supplies a loader configuration for those directories and runs
`ldconfig -X` after injection, before starting SSH/services. Inspection uses a
fresh temporary GStreamer cache and prints registration errors instead of
hiding them. This resolves environment-independent library lookup; it does
not add the Nano's missing NVENC engine or establish hardware encode readiness.
