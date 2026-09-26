# Admiral Configuration for this workload

Everything below maps this image onto the launch contract described in
[Configurations & Workloads](https://docs.admrl.co/core-concepts/configurations)
and [Hardware Access](https://docs.admrl.co/core-concepts/hardware-access).

```yaml
name: "unitree-g1-pc4"
image: "docker.io/<you>/workload-unitree-g1:2026-09-26-pc4-r39.2.0-r1"   # pin a real tag or @sha256, never :latest

desiredState: "RUNNING"

options:
  interactive: false      # headless — no kiosk/VT, keeps the Admiral console on tty1
  isolateDevices: false   # REQUIRED: V4L2 camera, /dev/nvhost*, /dev/nvmap, /dev/dri
  hostNetwork: true        # REQUIRED: static 192.168.123.164/24 + DDS multicast (230.1.1.1)
  readOnlyRoot: false

# Command left empty: this image's ENTRYPOINT (tini -g -- start-unitree-g1) runs as-is.

volumes:
  # Fill in the actual mutable-state path(s) once confirmed against a real
  # capture — /unitree/robot/pkg (module metadata) and any video_hub_pc4
  # runtime/config dir are the current best guesses. Anything NOT in a
  # volume is lost on every image update (Admiral destroys and re-snapshots
  # the rootfs — see "Root Filesystem Snapshot Persistence" in the docs).
  - name: "unitree-module-state"
    mountPath: "/unitree/robot/data"    # verify exact path from a live board
  - name: "unitree-logs"
    mountPath: "/var/log/unitree-g1"

ports:
  - containerPort: 22
    hostPort: 22
    protocol: "TCP"      # diagnostic SSH; drop this in production if unneeded
  # 8888 (the vendor OTA uploader) is deliberately NOT captured/exposed —
  # module set is frozen at image-build time; ship module upgrades as a new
  # image tag through Admiral's rollout engine instead of a live uploader.
```

## Why each flag

- **`isolateDevices: false`** — same requirement as
  [Jetson Orin CUDA](https://docs.admrl.co/core-concepts/jetson-orin-cuda)
  and the [Hardware Access guide](https://docs.admrl.co/core-concepts/hardware-access):
  V4L2/camera and Tegra device nodes only appear with device isolation off.
- **`hostNetwork: true`** — required for two independent reasons: (1) the
  board's static `192.168.123.164/24` IP is a host-network-namespace
  setting, and (2) CycloneDDS discovery + `video_hub_pc4`'s multicast
  publish (`230.1.1.1` on `eth0`) do not survive a NAT'd container network
  namespace — see [Robotics & ROS 2 §2](https://docs.admrl.co/core-concepts/robotics#2-unrestricted-dds-multicast-hostnetwork-true).
- **`interactive: false`** — this is a headless appliance; there's no
  kiosk/GUI component. Leaving interactive mode on would detach the
  Admiral console's tty1 for no benefit (see the docs' explicit warning
  about this).
- **Custom Volumes** — anything Unitree's stack writes at runtime (module
  install state, `ota_pipe` bookkeeping, logs) must live outside the
  container rootfs or it's wiped on every image update. **Not yet
  confirmed** exactly which paths under `/unitree/` are genuinely mutable
  vs. part of the installed-module payload — check this against a live
  board with `inotifywait`/`find -newer` before finalizing, then update
  this file and the Dockerfile/capture script accordingly.
- **No GPU-specific flag** — per the Jetson Orin CUDA doc, there isn't one;
  `isolateDevices: false` is the whole story. This workload doesn't call
  CUDA directly, but the L4T GStreamer HW encode path likely rides the same
  device/driver surface.

## Open risk items to validate on real hardware

1. **CycloneDDS ABI/version mismatch.** We build the last `0.x` release
   (0.10.5) of CycloneDDS from source to get the `libddsc.so.0` SONAME
   `video_hub_pc4` expects — we do not know which exact upstream commit
   Unitree actually linked against. Confirm `video_hub_pc4` starts cleanly
   and a DDS peer on the robot's domain actually receives frames; if not,
   try other 0.x point releases (0.9.x, 0.8.x) or extract a header/symbol
   diff from the captured binary.
2. **L4T GStreamer point-release match.** The pinned `nvidia-l4t-gstreamer`
   `.deb` targets L4T 39.2.0 specifically. Confirm this matches whatever
   point release Admiral's own Tegra 6.8 kernel build actually reports
   (`uname -r` inside the deployed workload vs. the `.deb`'s target) —
   mismatched L4T multimedia libraries can silently fail to open the
   HW encoder/ISP.
3. **Exact camera device nodes.** `docs/g1-topology.md` — needs confirming
   against `unitree-g1-status camera` / `v4l2-ctl --list-devices` on the
   real board once deployed under Admiral, not just on the stock
   `unitree-jetpack` image.
4. **Mutable state paths for Custom Volumes** — see above.
5. **`master_service`'s actual foreground behavior.** `start-unitree-g1`
   assumes `/etc/init.d/master_service start` daemonizes normally and a
   `pgrep -x master_service` watchdog is an adequate crash signal for
   Admiral's restart policy. Verify the process name and exit/respawn
   behavior match what the init script actually does — we captured the
   binaries, not their internals.
6. **SSH is optional attack surface.** Consider dropping port 22 entirely
   once the workload is validated, or restricting `AllowUsers`/keys tightly
   — see `ssh/authorized_keys`.
