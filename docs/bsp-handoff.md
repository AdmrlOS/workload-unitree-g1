# G1 EDU user-board BSP handoff (Jetson Orin NX, Tegra 6.8)

This image runs in Admiral's workload namespace; **the BSP owns USB, kernel
drivers, the physical network interface, host udev and the host `/dev` tree**.
The second Orin NX is the target, not the locked motion-control board.

## 1. D435i camera and stable capture node

`video_hub_pc4_1.0.1.1` hardcodes `v4l2src device=/dev/rlsen0` at **YUY2,
1920×1080, 15 fps**. Its included udev rule is:

```udev
# /etc/udev/rules.d/70-unitree-realsense-rlsen0.rules (BSP/host rootfs)
SUBSYSTEM=="video4linux", ENV{ID_VENDOR_ID}=="8086", ENV{ID_MODEL_ID}=="0b3a", ENV{ID_USB_INTERFACE_NUM}=="03", ENV{ID_V4L_CAPABILITIES}=="*capture*", SYMLINK+="rlsen0"
```

Place it in the **BSP's host udev rules**. The copy supplied by the UPK is
intentionally removed from the OCI image: Admiral's host udev does not load
rules from a container's `/etc/udev/rules.d`. It must create the symlink
before the workload needs the camera, and recreate it after USB hotplug.

- Enable the G1 carrier's correct USB3 ports/device tree and USB xHCI/UVC
  V4L2 support (`uvcvideo`, `videodev`, videobuf2 dependencies, whether built
  in or module). This is an **Intel USB camera**, not MIPI CSI/Argus.
- The rule depends on host udev populating `ID_VENDOR_ID`, `ID_MODEL_ID`,
  `ID_USB_INTERFACE_NUM`, and `ID_V4L_CAPABILITIES`. A minimal udev setup
  without the standard persistent-V4L/USB ID rules and `v4l_id` import may
  expose `/dev/video*` but **never match this rule**. Verify the properties
  on the *color capture* node, not one of the D435i metadata/depth nodes.
- Keep the host's `/dev` bind-mounted into the workload (`isolateDevices:
  false`). `/dev/rlsen0` must resolve to a usable `/dev/videoN` in that
  same tree. Do not hardcode `/dev/video4`: USB enumeration order changes.

Verification **on Admiral OS** with camera connected:

```sh
lsusb -d 8086:0b3a
udevadm info --query=property --name=/dev/videoN  # check the four properties above
readlink -f /dev/rlsen0                      # points to the color capture node
v4l2-ctl -d /dev/rlsen0 --all                # reports Video Capture
v4l2-ctl -d /dev/rlsen0 --list-formats-ext   # YUY2 1920x1080 @15 fps
```

Run `unitree-g1-status inspect` *inside the workload* to confirm it sees
the same alias. The bundled warmup script captures 45 frames using
`v4l2src` before starting video_hub because this D435i may stall during
its first stream after cold power-up. The workload does not generate the
udev symlink, and does not run a second udev daemon.

## 2. Hardware video encode and multimedia device exposure

The actual GStreamer pipeline is: `v4l2src /dev/rlsen0` → `nvvidconv`
(NVMM/VIC) → `nvv4l2h264enc` (NVENC, 720p and 360p) plus `nvjpegenc`
(1080p JPEG). Encoded H.264 also goes to **UDP multicast
230.1.1.1:1720** via `eth0`.

- Expose Tegra NVMM/multimedia device nodes from the matching NVIDIA R39.2.x
  kernel/firmware: `/dev/nvmap` and the NVHOST VIC, NVENC/MSENC and JPEG
  engine control nodes (actual names differ across releases; commonly
  `/dev/nvhost-vic`, `/dev/nvhost-nvenc*`, `/dev/nvhost-msenc`,
  `/dev/nvhost-nvjpg*`). Also expose NVGPU/DRM device nodes required by the
  Admiral NVIDIA profile. **Confirm actual nodes and permissions on G1
  hardware**; do not create fake nodes in the image. `/dev/nvidia0` and
  `nvidia-smi` are desktop GPU assumptions, not this Tegra path.
- Ensure Admiral's device permissions include these nodes (the workload
  starts the vendor stack as root). Default full `/dev` pass-through with
  `isolateDevices: false` is the intended setup, including USB bus nodes
  for any subsequent userspace USB/RealSense tooling.
- **Userspace belongs in the OCI image, not the BSP:** NVIDIA's R39.2.x
  `nvidia-l4t-multimedia`, `-multimedia-utils`, `-camera` and `-nvsci`
  libraries must be bundled without a competing `libcuda.so.1` driver.
  The current image lacks these multimedia libraries, so its NVIDIA
  GStreamer elements do **not** load, even though the Unitree services
  start. See `docs/admiral-mapping.md`. The BSP must supply the matching
  kernel/firmware/devices and identify which L4T release it uses; image
  maintainers supply the matching user libraries.

## 3. Wired robot network and time

Set the **host** robot NIC to `eth0` (or agree a change to the package's
CycloneDDS XML and GStreamer pipeline); the package hardcodes `eth0` in
both. Provision `192.168.123.164/24` on the robot network. Use
`hostNetwork: true` so DDS discovery and `230.1.1.1:1720` reach the main
computer. The vendor OTA CLI also targets **tcp://192.168.123.164:1026**;
it cannot connect in a Docker NAT test on an unrelated host. Chrony from
the patch UPK is a systemd unit and is not run in
the OCI image: arrange clock sync with the main computer at the OS/BSP
network layer if needed for the robot's timestamps.

The base supervisor invokes `amixer set Speaker 75%`; if PC4 audio is
needed, expose the host ALSA `/dev/snd/*` nodes and matching sound driver.
The current video pipeline does **not** require CAN/motor UARTs, a MIPI
CSI/Argus camera, or an x86-style `/dev/nvidia0`. It also attempts to set
`/proc/sys/kernel/core_pattern` for diagnostics; this may be read-only in
the workload and is not a camera or device-pass-through requirement.
