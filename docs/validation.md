# Acceptance of a G1 Clean slate release

## Optional hardware-free checks

CI only builds and publishes the ARM64 Ubuntu 26.04 image, using verified
Unitree inputs and pinned NVIDIA packages. It does not start a container or
run these tests, and the Dockerfile does not run the image diagnostic checker.
The manual checks below are available for maintainers on a native ARM64 Docker
host; vendor service process checks are not validated under QEMU. They cover:

- No competing Admiral GPU driver or CUDA stub in the image.
- ELF dependencies for Unitree executables, required GStreamer plugins,
  nvJPEG/CUDA runtime and encoder/VIC/NvSci backends. Only known injected
  driver names may be unresolved during an ordinary image build.
- Registration of `nvvidconv`, `nvv4l2h264enc`, `nvjpegenc` with the actual
  R39.2.1 test driver libraries mounted into a disposable container.
- No runtime OTA executable, CLI, pending update or manager update hook.
- Cold startup, Unitree service manager, camera waiting/blocked state, child CMD,
  clean SIGTERM, rootfs reuse after restart and failure on child-app exit.
- Synthetic USB/sysfs tests: capture versus metadata, depth/interface/vendor
  filtering, multiple-camera rejection/serial selection, alias handling,
  re-enumeration and child-process termination.
- A derived image can build without replacing the base entrypoint.

Run locally:

```sh
python3 -m unittest discover -s tests -v
bash tests/smoke-image.sh unitree-g1:local
# On Linux, optionally assemble the driver-loading fixture:
python3 tests/stage-driver.py --cache artifacts/test-driver-debs --output /tmp/g1-test-driver
bash tests/smoke-image.sh unitree-g1:local /tmp/g1-test-driver
```

A Docker host with no Jetson hardware will report CUDA/device initialization
errors when plugins probe the hardware. Plugin registration is a loader/ABI
check only, not accelerated execution. No motion commands are issued.

## G1 hardware gate — required before golden-master promotion

Record the image digest, app/base commit, Admiral init/BSP version, L4T driver
manifest, robot firmware version, camera firmware and test date. Deploy the
actual candidate **through Admiral**, not a manually assembled SSH/container
setup. Require `unitree-g1-status check` to pass; a running workload with
default warning-only startup is not a readiness pass. Set
`ENV UNITREE_HARDWARE_CHECKS=1` in a production child image when startup must
require a complete platform. An Orin Nano cannot pass stock video acceptance
because it has no NVENC hardware.

**Run all commands below inside the deployed workload**, through its shell or
the SSH server in the image (after provisioning your key). This repository
installs `/usr/local/bin/unitree-g1-status` and `/usr/local/bin/unitree-g1-check.py`
in the image. They are userspace diagnostics, not kernel features or host-side
commands. For a conventional Docker deployment the equivalent is
`docker exec CONTAINER unitree-g1-status inspect`; Admiral does not require
a Docker daemon on the robot.

1. **Platform contract.** Confirm the G1 BSP's carrier patches, kernel modules,
   firmware, all multimedia engines, NIC and time owner. Run:

   ```sh
   unitree-g1-status platform
   unitree-g1-status inspect
   cat /run/unitree-g1/camera.json
   lsusb -d 8086:0b3a
   readlink -f /dev/rlsen0
   v4l2-ctl -d /dev/rlsen0 --list-formats-ext
   ip -brief address show eth0
   unitree-g1-status lan
   ip route get 192.168.123.161
   ```

   Capture the manifest from `/run/admrl/nvidia/manifest.json` (published path)
   or `/run/admiral/nvidia/manifest.json` (inspected init implementation).
   The image supports both. Check camera USB SuperSpeed enumeration and
   YUY2 1920×1080 at 15 fps. Do not treat a kernel version string alone as
   proof of a matching driver payload. The G1 BSP must name the physical wired
   NIC `eth0`: the vendor binary uses that literal name for multicast as well
   as DDS. The correct `.164` address on a different NIC name is insufficient.

   In the workload SSH session, confirm `libcuda.so.1` appears in `ldconfig -p`
   even when `LD_LIBRARY_PATH` is unset. The startup loader refresh must make
   injected drivers available to login sessions as well as the entrypoint.
   `unitree-g1-status inspect` uses a fresh cache to avoid stale plugin blacklists.

2. **Actual video.** Wait for warmup to pass and `unitree-g1-status check` to
   succeed. Observe live, advancing frames in the stock robot app. Independently
   verify JPEG and H.264 output, both encoded H.264 resolutions used by the
   vendor, frame rate, latency and sustained operation. Receive from another
   robot-LAN machine as well as the local app if local multicast is needed.
   Receiving packets alone is not a decode/frame-quality test.

3. **Isolate engine failures if needed.** Stop the video service before opening
   its camera directly. Run a bounded camera capture and synthetic NVMM/VIC →
   H.264/JPEG encode pipeline with `gst-launch-1.0` appropriate to the negotiated
   formats, inspect the produced output, then restart video hub. This checks
   actual allocation/ioctls, not only `gst-inspect`. Retain driver and kernel
   errors with the result. Do not repair a passing run with manual driver copies.

4. **Cold boot and hotplug.** Test several full power cycles and warm reboots.
   Disconnect/reconnect the D435i while streaming. Confirm `/dev/rlsen0` tracks
   the RGB capture node even if video numbering changes, warmup repeats, and
   frames resume in both the stock app and the user app. Exercise absent camera
   at boot and late enumeration. Camera recovery must not require host edits.

5. **PC1 integration.** Confirm a read-only SDK2 state request/subscription on
   domain 0 and `eth0`, matching G1 firmware/message types. Check time offset
   against the vendor `.161` NTP source using the host's clock service. Confirm
   no competing clock daemon. A ping proves neither DDS discovery nor clocks.
   Perform motion acceptance separately with an operator and explicit activation.

6. **Audio and peripherals.** Match the vendor ALSA selection to actual G1 card
   enumeration. Test stock audio behavior, Wi-Fi and Bluetooth if included in the
   device acceptance scope. Depth/IMU and extra accessories need separate tests;
   the stock RGB pipeline does not exercise them.

7. **Lifecycle and load.** Run the intended perception/application load, monitor
   shared CPU/GPU RAM and thermals, stop/restart it, reboot, then roll forward and
   back between image digests. Confirm orderly app termination, automatic restart
   after a failure, unchanged PC1 behavior, durable app data and recovery of video.
   Do not automatically replay prior movement commands on restart.

A base is approved only after this record is complete. Missing G1 evidence is
an open validation item, not a software-only pass. Track new BSP/driver, robot
firmware and CUDA/framework versions as new compatibility combinations.
