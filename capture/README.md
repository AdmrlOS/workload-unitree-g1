# Optional comparison against a flashed G1

The OCI image now builds **without hardware** from the official PC4 base
ZIP and the two hash-pinned UPKs. If a G1 becomes available, follow
[legion1581/unitree-jetpack's G1 guide](https://github.com/legion1581/unitree-jetpack/blob/g1/docs/unitree-stack.md),
install the Patch PC4 and Video Hub PC4 modules and run
`capture-unitree-g1.sh` on the Jetson as root. It records an installed
`/unitree` tree and a manifest of versions. Use those outputs to compare
the package-built userspace to a known-working robot. The tarball and
manifest are gitignored and are **not** inputs to the current Dockerfile.

The mandatory on-hardware acceptance is broader than file comparison:
confirm the host BSP udev rule creates `/dev/rlsen0`,
`gst-inspect-1.0` loads the three NVIDIA multimedia elements, and a
subscribed peer receives the real camera stream at `230.1.1.1:1720`.
