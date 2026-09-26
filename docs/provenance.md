# Where the Unitree binaries actually come from

Short answer: **the base install bundle is Unitree's own public, official
recovery instructions** — not something reverse-engineered or sniffed off
the wire. The camera/patch *module* packages (`unitree_patch_pc4`,
`video_hub_pc4`) are a separate, murkier story. Sleuthing trail below.

## The base bootstrap (`g1plus_pc4_unitree_install.zip`)

`legion1581/unitree-jetpack`'s `versions/*/version.env` pins:

```
UNITREE_INSTALL_URL="https://oss-global-cdn.unitree.com/static/ad3297c5c9bb40368c3e0c9febefa375.zip"
```

That exact hash-named URL appears **verbatim** in Unitree's own official
developer FAQ:

- **Canonical source:** [support.unitree.com/home/en/G1_developer/FAQ](https://support.unitree.com/home/en/G1_developer/FAQ)
  (served from `doc-cdn.unitree.com`), under the heading *"Regarding the
  issue of the Go interface being unable to preview video streams for depth
  cameras connected to the NX development board EDU+ device"* — i.e. this
  is Unitree's **official fix for exactly the camera/video_hub problem this
  workload cares about**, published for any G1 EDU+ developer to use.
- The FAQ gives the identical procedure `unitree-jetpack`'s
  `70-rootfs-unitree-base.sh` patch automates: scp the zip to
  `unitree@192.168.123.164`, `unzip`, `rm -rf /unitree`, run `./install`,
  verify with `ps -ef | grep master_service`.
- **Independently corroborated** — the same URL/hash shows up verbatim in
  at least four unrelated repos that mirror or translate Unitree's official
  docs, found via GitHub code search:
  - [`MoissanClub/g1-docs`](https://github.com/MoissanClub/g1-docs) — "AI
    agent friendly offline docs for Unitree G1. Copyright Unitree"
  - [`Orboh/g1-handbook-jp`](https://github.com/Orboh/g1-handbook-jp) —
    Japanese translation of Unitree's G1 SDK Development Guide
  - [`maxtlee/HumanoidSeatAssembly`](https://github.com/maxtlee/HumanoidSeatAssembly) —
    unrelated robotics project, docs snapshot for reference
  - [`zh-plus/unitree-g1-dev-copilot`](https://github.com/zh-plus/unitree-g1-dev-copilot) —
    an AI coding-assistant "skill" bundling the same FAQ as grounding docs

Four independently-maintained mirrors of Unitree's own documentation citing
the identical CDN hash is about as strong a confirmation as you get without
Unitree explicitly saying so on the record: **this zip is Unitree's own
public support artifact**, not proprietary leaked material.

That said — it is still Unitree's copyrighted binary distribution, hosted
on Unitree's own infrastructure. This repo does **not** re-fetch it from
that URL and does **not** redistribute it; `capture/capture-unitree-g1.sh`
only snapshots it off a board where *you* legitimately installed it
following Unitree's own instructions. See `capture/README.md`.

## The module packages (`unitree_patch_pc4`, `video_hub_pc4` — the actual camera code)

This is the part that's genuinely murkier. The same official FAQ entry ends
with:

> *"After completing the above steps, contact technical support to: Update
> the Patch PC4 and Video Hub PC4 components to the latest versions."*

Unitree does **not** publish `unitree_patch_pc4_*.upk` or
`video_hub_pc4_*.upk` at a public URL anywhere in that FAQ — official
channel is "contact support." `legion1581/unitree-jetpack`'s own
`docs/unitree-stack.md` instead points users at a **third-party Yandex Disk
mirror** for these `.upk` files:

```
https://disk.yandex.com/d/hDJ2DQMlDnoB2g
```

That's a community re-hosting, not an Unitree URL — presumably populated by
someone in the community who got the packages through the official support
channel (or extracted them off a shipped robot) and shared them forward.
We have no independent corroboration of that mirror's provenance the way
the base-install zip has four independent citations, and this repo does
**not** link to or fetch from it.

**This is exactly why `workload-unitree-g1` is a capture build and not a
"just re-fetch these URLs" Dockerfile**: the base install is confidently
sourceable from Unitree's own docs, but the actual camera-streaming module
is only reliably available by pulling it off hardware you already have
legitimate access to — which is what `capture-unitree-g1.sh` does. It's the
same posture the community itself has already converged on.

## Everything else in this Dockerfile, for comparison

- **WiFi driver** (`rtl8852bu-dkms_*.deb`) — same official FAQ page, a
  different `doc-cdn.unitree.com` hash-named zip, separate entry. Not used
  by this workload (no WiFi dependency here) but confirms the pattern: NX
  board driver blobs Unitree does publish, they publish through this same
  FAQ mechanism.
- **`nvidia-l4t-gstreamer` and friends** — NVIDIA's own public Jetson apt
  repository (`repo.download.nvidia.com/jetson/...`), no provenance
  question at all; standard NVIDIA distribution infrastructure.
- **CycloneDDS, OpenSSL 1.1** — upstream open source / Ubuntu archive,
  built or fetched by us directly, not from Unitree or legion1581 at all.
