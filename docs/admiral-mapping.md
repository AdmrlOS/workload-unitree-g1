# Deploying the PC4 userspace on Admiral

In **Configs > New Configuration** use a versioned tag or digest of the
**private** `ghcr.io/admrlos/workload-unitree-g1` image:

```yaml
name: unitree-g1-pc4
image: ghcr.io/admrlos/workload-unitree-g1@sha256:<published-manifest-digest>
desiredState: RUNNING
options:
  interactive: false
  isolateDevices: false
  hostNetwork: true
  readOnlyRoot: false
# Leave Command empty to use tini + start-unitree-g1 from the image.
volumes:
  - name: pc4-diagnostics
    mountPath: /var/log/unitree-g1
```

Set up private GHCR access through [Admiral registry credentials](https://docs.admrl.co/core-concepts/registry-credentials).
`isolateDevices: false` passes host `/dev` including the camera and Tegra
multimedia nodes. `hostNetwork: true` allows CycloneDDS on `eth0` and the
UDP H.264 multicast stream on `230.1.1.1:1720`. The BSP/Admiral host owns
the NIC name, IP address and udev rules; this image cannot rename a NIC or
make the host's `/dev/rlsen0` by installing a rule in its private rootfs.

On image updates Admiral replaces the writable rootfs snapshot. The two
module versions are **baked in**, so do not mount a fresh empty volume on
`/unitree` or `/unitree/robot/pkg`: that would hide the installed modules.
Use a new pinned image for upgrades. Keep a volume for application state
only once its exact paths have been determined on hardware; the logging
volume above is optional.

## Remaining hardware validation

1. **NVIDIA multimedia userspace is incomplete.** The image contains the
   pinned R39.2 `nvidia-l4t-gstreamer` plugin .deb, but the plugins do not
   register without matching `nvidia-l4t-multimedia` (e.g.
   `libnvbufsurface.so.1.0.0`, `libnvbufsurftransform.so.1.0.0`), camera
   and NvSci runtime libraries. Obtain the matched non-driver packages
   from NVIDIA's R39.2.0 BSP `nv_tegra/l4t_deb_packages/` and add them to
   the OCI userspace. **Do not** package `nvidia-l4t-cuda-nvgpu`/
   `-cuda-openrm` or another `libcuda.so.1`: Admiral injects its matching
   driver. Check every NVIDIA GStreamer element with `gst-inspect-1.0`
   before testing with the camera.
2. **Host UVC node/udev:** see [BSP handoff](bsp-handoff.md). The UPK uses
   `/dev/rlsen0` for D435i RGB; this needs host udev and full `/dev` access.
3. **Match L4T 39.2.x:** BSP kernel/firmware, Admiral GPU driver profile and
   the image's multimedia libraries must be tested as one set. GPU compute
   passing a CUDA smoke test alone does not prove NVENC/VIC/JPEG works.
4. **On-robot behavior:** check the camera-warmup log
   `/var/log/videohub-warmup.log`, `unitree-g1-status inspect`, and actual
   JPEG/H.264 frames on the robot network. The package's service may report
   `running` before its first frames arrive.

If the bootstrap's `amixer` or chrony setup needs actual ALSA devices or
robot time synchronization, provide those at the OS/BSP layer. The patch
UPK's `chrony.service` is a systemd unit and is not started inside the
Admiral workload.
