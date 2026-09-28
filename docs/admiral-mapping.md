# Deploying the Clean slate or a derived application on Admiral

Publish an ARM64 image to an accessible registry, then select its immutable
digest in **Configs > New Configuration**:

```yaml
name: unitree-g1-pc4
image: ghcr.io/YOUR_ORG/YOUR_APPLICATION@sha256:REPLACE_WITH_PUBLISHED_DIGEST
desiredState: RUNNING
options:
  interactive: false
  isolateDevices: false
  hostNetwork: true
  readOnlyRoot: false
# Leave Command empty: inherited ENTRYPOINT + child-image CMD start together.
volumes:
  - name: robot-app-data
    mountPath: /var/lib/robot-app
```

For the bare Clean slate, select the approved base digest and omit the app
volume. Configure [registry credentials](https://docs.admrl.co/core-concepts/registry-credentials)
for private images. This YAML describes the portal's configuration fields;
use your Admiral API schema when automating configuration creation.

`isolateDevices: false` exposes the real `/dev` tree and activates Admiral's
NVIDIA driver path. `hostNetwork: true` permits DDS and video multicast on
the physical robot LAN. No Docker daemon, NVIDIA Toolkit flags, driver
installation, custom GPU mounts or host udev file edits are required.

Admiral must provision `192.168.123.164/24` on the physical wired NIC before
launching this host-network workload. Startup renames that verified PC1 port
to `eth0` when boot-time naming gave it another name; this requires `CAP_NET_ADMIN`
and briefly interrupts the robot link. The closed video hub hardcodes `eth0`
for DDS and H.264 multicast. The image checks L4T 39.2.1,
resolved NVIDIA libraries, the three video plugins and robot network before
starting the Unitree stack. By default, `UNITREE_HARDWARE_CHECKS=warn` logs
failures and keeps SSH, the manager and the app available. Missing hardware
never becomes a passing readiness result. Use `ENV UNITREE_HARDWARE_CHECKS=1`
in a production child Dockerfile to require a passing platform check at startup.
`0` skips startup inspection for local development.

Orin Nano has no NVENC: stock video cannot run there. The camera supervisor
reports `blocked` while SSH/apps can continue. Use the G1's Orin NX for full
video acceptance; installing additional drivers cannot add a hardware encoder.

Use `/var/lib/robot-app` for durable application data. A newly created volume
can be root-owned; provision ownership for the app's UID (the starter uses
10001) before starting a writer. Do not mount over `/unitree`, `/usr/lib`,
`/run`, `/opt/app`, or other installed-code/driver locations. Admiral preserves
rootfs changes across ordinary restarts, but replaces the rootfs on image
updates. An explicit app-data volume survives those updates.

The Unitree PC4 OTA service and CLI are removed, including the TCP endpoint
on `.164:1026`, pending-update payloads and the service manager's update hooks
in both live and backup configuration. Use Admiral to update or roll back the
complete PC4 application image. Unitree-app PC4 update/version queries using
that endpoint are intentionally unsupported; PC1 firmware is unchanged.

Admiral supervises the root process; Docker `HEALTHCHECK` is not executed.
The entrypoint checks master_service, SSH and the optional app.
Camera readiness is separately exposed by `unitree-g1-status check` and
`/run/unitree-g1/camera.json`; blocked, warmup and waiting states are not “camera ready”.

On receipt of SIGTERM the entrypoint stops the app and vendor services; allow
about 25 seconds for an orderly rollout stop. App and camera logs reach
Admiral's dashboard. Run `unitree-g1-status inspect` **inside the workload**
for detailed diagnostics. The image installs it at `/usr/local/bin/unitree-g1-status`;
it is not supplied by the Admiral host or kernel.

See [BSP contract](bsp-handoff.md), [application guide](clean-slate.md),
[acceptance tests](validation.md), and Admiral's
[launch contract](https://docs.admrl.co/core-concepts/configurations) and
[Jetson GPU contract](https://docs.admrl.co/core-concepts/jetson-orin-cuda).
