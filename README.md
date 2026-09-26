# workload-unitree-g1

Packages the Unitree G1 EDU **PC4 stack** (`master_service` + `ota_pipe` +
`unitree_patch` + the `video_hub` camera module) as an Admiral OCI workload
for the G1's **second Jetson Orin NX** — the user-workload board, not the
locked-down motion/locomotion computer. See `docs/g1-topology.md` for how
that maps onto the robot's actual hardware.

This is a **capture** build, following the pattern in the sibling
[`workload-cuda-debug`](../workload-cuda-debug) repo (multi-stage Dockerfile,
`tini`-as-PID1, SSH for diagnostics, `co.admrl.workload` label, no baked-in
NVIDIA driver) but adapted for a stack we don't control the source of:
instead of compiling anything Unitree-specific ourselves, we snapshot an
already-flashed, already-working board (via
[`legion1581/unitree-jetpack`](https://github.com/legion1581/unitree-jetpack/tree/g1)
+ its documented post-flash module installs) and re-host that snapshot as
an Admiral workload. See `capture/README.md` for the exact procedure.

## Why capture instead of rebuild

`master_service`, `ota_pipe`, `unitree_patch`, and `video_hub_pc4` are
proprietary Unitree binaries fetched from Unitree's CDN by
`unitree-jetpack`'s build script — there's no public source to recompile
against, and no guarantee this repo could redistribute them even if there
were. **See `docs/provenance.md` for the full sleuthing trail**: the base
install bundle turns out to be Unitree's own official, publicly documented
recovery FAQ (confirmed via four independent doc mirrors citing the same
CDN hash) — but the actual camera-streaming module (`video_hub_pc4`) is
only ever handed out via "contact support" or a community-run mirror we
deliberately don't link to. That asymmetry is *why* this is a capture build:
the reliable, legitimate way to get the real module is off hardware you
already have access to, not by us re-hosting someone else's re-hosting.

What *is* reproducible and pinned here, the same way
`workload-cuda-debug` pins CUDA package versions by exact `.deb` URL +
sha256:

| Gap vs. a stock Ubuntu 24.04 rootfs | How this repo fills it |
|---|---|
| `libcrypto.so.1.1` / `libssl.so.1.1` (master_service built against OpenSSL 1.1, 24.04 ships only 3.0) | Pinned Ubuntu archive `.deb`, sha256-verified |
| `libddsc.so.0` (video_hub_pc4 links Eclipse CycloneDDS) | Built from source, pinned to CycloneDDS **0.10.5** — see the "CycloneDDS versioning trap" below |
| `nvvidconv`/`nvv4l2h264enc`/`nvjpegenc` (video_hub's HW GStreamer pipeline) | Pinned `nvidia-l4t-gstreamer` `.deb` for L4T 39.2.0, sha256-verified — same artifact `unitree-jetpack` itself bakes in |
| `/unitree/**`, `/etc/init.d/{master_service,ota_pipe}` | **Captured**, not reconstructed — see `capture/` |

### The CycloneDDS versioning trap

Eclipse CycloneDDS jumped its version numbering straight from `0.10.5` to
`11.0.0` — there was never a `1.x`–`10.x`. Its shared library's `SONAME` is
tied to that scheme (`libddsc.so.0` for every `0.x` release, `libddsc.so.11`
for `11.0.x`). `video_hub_pc4`'s `DT_NEEDED` entry is `libddsc.so.0`, which
means it was linked against something from the `0.x` line — **not** current
upstream. Building latest CycloneDDS here would produce a library the
dynamic linker can never satisfy that dependency with. The
`cyclonedds-build` stage in the `Dockerfile` pins `0.10.5` (the last `0.x`
release) and hard-fails the build if the resulting `SONAME` isn't exactly
`libddsc.so.0`. This is a **best-effort ABI match, not a confirmed one** —
see the risk list below.

## Layout

```
Dockerfile                    multi-stage build: CycloneDDS from source + captured
                               Unitree rootfs + pinned OpenSSL1.1/L4T-GStreamer .debs
capture/
  capture-unitree-g1.sh        run ON the flashed board to snapshot /unitree + init.d
  README.md                    full capture → build → verify procedure
  (unitree-g1-rootfs.tar.zst)  produced by the script above; git-ignored, NOT in this repo
  (MANIFEST.txt)                provenance for the tarball above; git-ignored
scripts/
  start-unitree-g1              ENTRYPOINT: starts ota_pipe + master_service via their
                                 own init.d scripts, keeps sshd up, watchdogs master_service
  unitree-g1-status             diagnostic CLI (mscli/ota_pipe_cli/DDS/camera/GStreamer)
ssh/
  sshd_config                   same restrictive posture as workload-cuda-debug
  authorized_keys                empty placeholder — add your own key before building
docs/
  g1-topology.md                which Jetson this targets and why, network/camera notes
  admiral-mapping.md            the actual Configuration YAML + why each flag is set,
                                 plus the open risk list
  provenance.md                 where the captured Unitree binaries actually come from
```

## Quick start

```bash
# 1. On the flashed G1 user-workload board (see capture/README.md step 1):
scp capture/capture-unitree-g1.sh unitree@192.168.123.164:~
ssh unitree@192.168.123.164 sudo ./capture-unitree-g1.sh
scp unitree@192.168.123.164:~/unitree-g1-rootfs.tar.zst capture/
scp unitree@192.168.123.164:~/MANIFEST.txt capture/

# 2. Add an SSH key to ssh/authorized_keys (or leave empty to disable SSH)

# 3. Build
docker buildx build --platform linux/arm64 --load \
  -t <you>/workload-unitree-g1:2026-09-26-pc4-r39.2.0-r1 .

# 4. Push, then deploy through Admiral using docs/admiral-mapping.md's
#    Configuration (isolateDevices: false, hostNetwork: true, interactive: false)
docker push <you>/workload-unitree-g1:2026-09-26-pc4-r39.2.0-r1
```

## CI/CD

- **`.github/workflows/ci.yml`** — runs on every push/PR, no secrets
  needed. Builds the image against a synthetic fake capture tarball
  (never real Unitree binaries) and exercises the actual runtime behavior
  (entrypoint → ota_pipe/master_service → sshd, plus the crash watchdog
  actually exiting the container on a simulated `master_service` death).
  This is exactly the harness used to develop this repo — it already
  caught a real tee/pipe deadlock and a CycloneDDS SONAME mismatch before
  either shipped.
- **`.github/workflows/publish.yml`** — builds the *real* image (real
  capture tarball) and pushes to `ghcr.io/admrlos/workload-unitree-g1`
  (private, inherits this repo's visibility). Requires two repo/org
  secrets pointing at wherever you privately store the real capture
  tarball — **never commit it to git**:
  - `UNITREE_CAPTURE_URL`
  - `UNITREE_CAPTURE_SHA256`

  Fails fast with a clear error if those aren't configured yet.

## Open risks — read before trusting this in production

This was assembled from documentation and a captured-binary contract, not
validated end-to-end against real G1 hardware running under Admiral yet.
Full list with context lives in `docs/admiral-mapping.md#open-risk-items`;
headline items:

1. **CycloneDDS ABI match is best-effort** (see above) — confirm
   `video_hub_pc4` actually talks to a DDS peer once deployed.
2. **L4T GStreamer point-release** must match whatever Tegra 6.8 kernel
   build Admiral actually ships for the Orin NX — confirm, don't assume.
3. **Exact camera `/dev` nodes** and **mutable-state paths for Custom
   Volumes** are still TODO — fill in from a live capture, then update
   `docs/admiral-mapping.md` and the capture script's tar excludes.
4. **`master_service`'s daemonization/crash behavior** is inferred from
   its LSB init script conventions, not inspected — the watchdog in
   `scripts/start-unitree-g1` may need tuning once you can actually read
   `/etc/init.d/master_service` from a capture.

## Related

- [`workload-cuda-debug`](../workload-cuda-debug) — the sibling repo this
  one's Dockerfile/entrypoint conventions are modeled on.
- [`legion1581/unitree-jetpack`](https://github.com/legion1581/unitree-jetpack/tree/g1) —
  the JetPack build + post-flash module install this workload captures from.
- [docs.admrl.co](https://docs.admrl.co) — in particular
  [Configurations & Workloads](https://docs.admrl.co/core-concepts/configurations),
  [Hardware Access](https://docs.admrl.co/core-concepts/hardware-access), and
  [Jetson Orin CUDA](https://docs.admrl.co/core-concepts/jetson-orin-cuda).
