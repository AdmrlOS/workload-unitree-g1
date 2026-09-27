# Hardware and communication target

This image runs the **PC4 user-workload stack** on the G1 EDU's Jetson Orin NX.
Admiral's G1-specific BSP supplies NVIDIA L4T **39.2.1** kernel/firmware/driver
components. The image supplies **Ubuntu 26.04** userspace. It does not replace
PC1 or the robot's protected locomotion firmware.

```text
User application on PC4 (.164, eth0)
  ├─ Unitree SDK2 / CycloneDDS, domain 0 ── Ethernet/IP ── robot control services
  ├─ UDP camera consumer ◀── video hub multicast 230.1.1.1:1720
  └─ CUDA/vision application ── Admiral-injected GPU driver ── Orin NX

D435i USB RGB ── BSP UVC driver ── workload /dev/rlsen0 ── video hub
                                                    VIC / NVENC / JPEG
```

PC1 is conventionally `192.168.123.161`; the vendor clock configuration
points there. Confirm the mapping for the target firmware/hardware revision.
The locomotion SDK uses named DDS services, initialized on `eth0`, rather
than connecting to an HTTP motion API at a fixed PC1 port.

See [movement control and application development](clean-slate.md#movement-control-ip-dds-and-sdk2),
[the BSP contract](bsp-handoff.md), and
[the G1 source reviewed](https://github.com/legion1581/unitree-jetpack/tree/f2742cf578bc4d0754301e0de6413cbb9c29f633).
