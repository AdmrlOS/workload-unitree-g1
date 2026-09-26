# Hardware target

The G1 EDU user-workload computer described in
[unitree-jetpack/g1](https://github.com/legion1581/unitree-jetpack/tree/g1)
is a Jetson Orin NX on the G1 carrier. This image runs the **PC4 user
stack on that NX**. It does not replace the robot's protected motion-control
computer or its motor/position services.

The JetPack 7.2 build targets L4T 39.2.0, Ubuntu 24.04, kernel 6.8 on
Tegra234. The base ZIP and the Noble 7.2 patch plus common video UPKs
contain the PC4 services. `video_hub_pc4` consumes the D435i USB color
camera through V4L2 (`/dev/rlsen0`), NVIDIA VIC/NVENC/JPEG through
GStreamer/NVMM, and publishes UDP H.264 to `230.1.1.1:1720` on `eth0`.
Its CycloneDDS config also selects `eth0` for DDS discovery.

The static robot network address `192.168.123.164/24` and clock sync
belong to Admiral's host OS/BSP provisioning, not to the container.
