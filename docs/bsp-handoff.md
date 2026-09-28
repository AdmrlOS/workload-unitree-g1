# G1 BSP / Clean slate boundary

The platform target is **G1 EDU PC4 Orin NX, NVIDIA L4T 39.2.1**. Admiral's
immutable OS is built for this carrier. The workload supplies Ubuntu 26.04
application userspace. It never flashes firmware or changes the host rootfs.

| Responsibility | G1 Admiral BSP / provisioning | Clean slate image |
|---|---|---|
| Boot and carrier | MB2 EEPROM configuration, G1 USB3 lane mapping, DTB, clocks/power/thermal | None |
| USB and camera driver | xHCI, UVC/V4L2, actual `/dev/video*` nodes, USB bus and sysfs | Identify the D435i RGB capture node; maintain `/dev/rlsen0`; warmup/reconnect |
| NVIDIA hardware | Matching kernel modules, firmware, NVGPU/VIC/NVENC/NVJPG/NvSci devices | Matching multimedia/CUDA application libraries and video service |
| GPU driver | Inject R39.2.1 NVGPU driver and companion libraries | No libcuda or duplicate injected companions |
| Robot LAN | Physical wired NIC, `192.168.123.164/24` and a PC1 route, host network namespace, `CAP_NET_ADMIN` | Rename the verified robot NIC to `eth0` at startup; vendor CycloneDDS and H.264 use that name |
| Time | One clock owner, synchronized to PC1 as required | Report requirement; do not run conflicting clock daemons |
| Wi-Fi/BT | G1 RTL8852BU driver, firmware, blacklist/autoload policy | Application connectivity through Admiral |
| Audio | ALSA kernel drivers, stable card assignment and `/dev/snd` | Vendor ALSA configuration and amixer; validate card mapping |

## Carrier source reviewed

[unitree-jetpack g1](https://github.com/legion1581/unitree-jetpack/tree/f2742cf578bc4d0754301e0de6413cbb9c29f633),
particularly `versions/7.2/patches/10-*`, `20-*`, `50-*`, `80-*` and
[USB mapping](https://github.com/legion1581/unitree-jetpack/blob/f2742cf578bc4d0754301e0de6413cbb9c29f633/docs/usb-mapping.md).
The upstream carrier work targets R39.2.0; rebuild/adapt it for Admiral's
R39.2.1 kernel. Do not reuse an upstream `.ko` merely because both releases
report kernel 6.8. The G1 carrier mapping enables the third SuperSpeed lane
and moves the device-mode controller to the correct USB-C lane. Kernel
modules, device tree and firmware remain BSP inputs.

## Camera initialization is owned by the workload

The vendor rule matches **USB 8086:0b3a, interface 03, video capture**. Its
original text is retained at `/opt/unitree-g1/vendor-camera.rules` for audit.
Installing it into a container does not make host udev read it. Instead,
`unitree-g1-camera.py` scans the USB ancestry exposed under
`/sys/class/video4linux`, queries V4L2 device capabilities, and creates the
relative symlink `/dev/rlsen0 -> videoN` in Admiral's shared `/dev`.

It rejects metadata/depth nodes and ambiguous cameras. With more than one
D435i, set `UNITREE_CAMERA_SERIAL`. It never assumes a fixed `/dev/video4`,
makes devices world-writable, reloads drivers, or needs the host udev database.
**Do not also provision a host rule managing the same alias.** It refuses to
overwrite a non-symlink at `/dev/rlsen0`.

The supervisor waits for the device, captures 45 RGB frames at the vendor
format (YUY2, 1920×1080, 15 fps), then launches video hub. Failed warmup is
retried rather than launching an already-stalled pipeline. USB identity
changes stop the old process, refresh the alias and repeat warmup. A camera
unplug does not kill the user's application; consumers must tolerate a gap.
This is process/hotplug recovery, not a proof of continuous frame delivery.

The workload needs readable `/sys/class/video4linux`, `/sys/devices` and
shared writable `/dev`, supplied by Admiral's normal device passthrough.
Host rootfs immutability does not prevent creating a symlink in devtmpfs.

## NVIDIA multimedia

Expose the actual R39.2.1 kernel's NVMM/VIC/NVENC/JPEG and NvSci interfaces,
including `/dev/nvmap`, GPU/host1x controls, and the relevant `nvhost-*`
engine nodes. Names can differ by kernel; compare actual engine devices to
a vendor-flashed G1. Pass `/dev/snd` and USB bus devices too. Never fake
major/minor numbers. `/dev/nvidia0` is not an Orin readiness test.

`config/nvidia-packages.json` pins application libraries. The extra
`libnvrm_stream`, VIC and 2D helper libraries are selected from `l4t-core`
because they are absent from the inspected Admiral compute-driver inventory.
`config/admiral-driver-libraries.json` names libraries that must remain absent
from the image. If the G1 BSP broadens its injected inventory, reconcile this
boundary and rebuild the base rather than shipping two copies.

The workload includes both published and current injected-driver directories
in `/etc/ld.so.conf.d/000-admiral-nvidia.conf`. Startup runs `ldconfig -X`
after Admiral injects the payload, so SSH and services that clear
`LD_LIBRARY_PATH` still resolve the driver. This updates the workload's loader
cache only; it does not copy drivers or modify the read-only BSP payload.

The image includes NvSci userspace and its endpoint config. NVIDIA's host
NvSci device initialization/UID policy remains in the BSP; the image does
not execute NVIDIA's systemd scripts or their `chmod 666` operation. Validate
the multimedia engines on the G1, not just CUDA compute on an Orin Nano.

## Robot LAN, time and audio

The vendor configuration expects `eth0`. Its DDS XML names `eth0`, and the
closed `videohub_pc4` executable contains
`udpsink host=230.1.1.1 port=1720 multicast-iface=eth0`. Changing only the XML
cannot fix video egress. On the inspected
2026-09-28 NX BSP, that NIC was `enP8p1s0` with the correct
`192.168.123.164/24` address and PC1 route; the video hub repeatedly exited
because CycloneDDS could not find `eth0`.

The Clean slate now performs the rename **inside workload startup, before
Unitree services**. It discovers the single physical Ethernet port carrying
`.164/24`, requires a working route to PC1 through that port, refuses to
touch the default-route interface or an occupied `eth0`, briefly takes the
robot link down to rename it, then brings it back up and verifies/repairs the
PC1 address and route. It is idempotent across workload restarts. This is a
host-network operation: the physical NIC is renamed for Admiral too, not only
for processes in the image. The BSP still owns the NIC driver; provisioning
must still put `.164/24` on the physical port before the workload starts.
No additional udev daemon or host rootfs rule is needed for this workaround.

The rename cannot be inferred when the robot address is absent, the port is
down, or the default route uses it. Startup logs a warning and keeps SSH
available in these cases; `unitree-g1-status lan` and readiness remain failed.
On the NX, Wi-Fi owns the default route, so its management connection should
remain up while the robot port is briefly renamed. Confirm on-device with
`ip -brief addr show eth0`, `ip route get 192.168.123.161`, and
`unitree-g1-status lan`. Check that Admiral's host network manager continues
to preserve the address after a network reconfiguration or lease renewal;
the immutable BSP's naming policy may be needed if it renames the port again.
The camera supervisor reports `blocked` until the `eth0` contract is met.

Provision `.164/24` before startup, without a
competing default route on this point-to-point LAN; use another Admiral
interface for registry/internet access. PC1 is conventionally `.161`, and the
patch's chrony file names `192.168.123.161` as its NTP server. Confirm this on
the target robot; SDK2 selects the Ethernet interface and DDS peers rather
than requiring a hard-coded HTTP endpoint.

The inspected Admiral capability set does **not** include `CAP_SYS_TIME`.
Starting stock chronyd in this image would therefore not reproduce clock
synchronization. Configure the Admiral host's existing time service to use
the robot's time source. Do not claim stock timestamp parity until offset
and clock ownership are verified. If workload-owned clock control is later
required, it needs an explicit Admiral capability/clock-ownership change.

The bootstrap selects an ALSA card and invokes `amixer set Speaker 75%`.
Validate its `/etc/asound.conf` against `aplay -l` and `amixer` on the actual
G1. Ubuntu enumeration on a different BSP can change the numeric card index;
record any required stable ALSA mapping in the workload rather than masking
errors by ignoring them.
