#!/bin/bash
# capture-unitree-g1.sh — run this ON the Unitree G1 user-workload Jetson
# (Orin NX) AFTER flashing it with legion1581/unitree-jetpack (g1 branch,
# -j 7.2) and AFTER installing the unitree_patch + video_hub modules via the
# OTA uploader (http://192.168.123.164:8888/), per that repo's
# docs/unitree-stack.md. It snapshots exactly the subtree the Admiral
# workload-unitree-g1 Dockerfile needs, so the image is a faithful capture
# of a known-good running board rather than a reimplementation from guesses.
#
# Output (copy both back to this repo's capture/ directory on your build
# host, next to the Dockerfile):
#   unitree-g1-rootfs.tar.zst   — /unitree + the two init.d scripts
#   MANIFEST.txt                — provenance: versions, dpkg -l, mscli/ota_pipe
#                                 state, sha256 of the tarball, for the
#                                 build-time image LABEL/audit trail
#
# Usage (on the robot, as root, over the wired 192.168.123.164 SSH or serial
# console — see legion1581/unitree-jetpack docs/tips.md for the UART header):
#   sudo ./capture-unitree-g1.sh
#
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo $0)" >&2
    exit 1
fi

OUT_DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARBALL="${OUT_DIR}/unitree-g1-rootfs.tar.zst"
MANIFEST="${OUT_DIR}/MANIFEST.txt"

command -v zstd >/dev/null 2>&1 || { echo "installing zstd..."; apt-get update && apt-get install -y zstd; }

echo "== sanity checks =="
test -x /unitree/module/master_service/master_service || { echo "FATAL: /unitree/module/master_service/master_service not found — is the board flashed + patched per docs/unitree-stack.md?" >&2; exit 1; }
test -f /etc/init.d/master_service || { echo "FATAL: /etc/init.d/master_service missing" >&2; exit 1; }
test -f /etc/init.d/ota_pipe || { echo "FATAL: /etc/init.d/ota_pipe missing" >&2; exit 1; }

echo "== recording provenance =="
{
    echo "captured: ${STAMP}"
    echo "hostname: $(hostname)"
    echo "uname:    $(uname -a)"
    echo
    echo "--- /etc/os-release ---"
    cat /etc/os-release
    echo
    echo "--- installed module versions (/unitree/robot/pkg/version/version.json) ---"
    cat /unitree/robot/pkg/version/version.json 2>/dev/null || echo "(not present)"
    echo
    echo "--- mscli listservice ---"
    /unitree/sbin/mscli listservice 2>&1 || echo "(mscli failed — is master_service running?)"
    echo
    echo "--- ota_pipe_cli listmoduleversion ---"
    /unitree/sbin/ota_pipe_cli -a default -c listmoduleversion 2>&1 || echo "(ota_pipe_cli failed)"
    echo
    echo "--- dpkg -l (full package list, for reproducing runtime lib deps) ---"
    dpkg -l
} > "${MANIFEST}"
echo "  -> ${MANIFEST}"

echo "== capturing /unitree + init.d scripts =="
# Excludes: PIDs/sockets/logs — anything that's live runtime state, not part
# of the installed module bytes. Adjust the excludes if your capture picks
# up something unexpected; check MANIFEST.txt's `mscli listservice` output
# against what actually made it into the tarball.
tar --create \
    --exclude='*.pid' \
    --exclude='*.sock' \
    --exclude='/unitree/**/log/*' \
    --exclude='/unitree/**/logs/*' \
    -C / \
    unitree \
    etc/init.d/master_service \
    etc/init.d/ota_pipe \
    | zstd -19 -T0 -o "${TARBALL}"

echo "== sha256 =="
sha256sum "${TARBALL}" | tee -a "${MANIFEST}"

echo
echo "Capture complete:"
echo "  ${TARBALL}"
echo "  ${MANIFEST}"
echo
echo "Copy both to the build host's capture/ directory (next to Dockerfile), then:"
echo "  docker buildx build --platform linux/arm64 -t <you>/workload-unitree-g1:<version> ."
