#!/bin/bash
# Optional, manual hardware-free lifecycle tests; not a publication gate.
# Runs only isolated containers it creates. Requires native ARM64 Docker.
set -euo pipefail
image=${1:?usage: smoke-image.sh IMAGE [TEST_DRIVER_DIRECTORY]}
name="unitree-smoke-$$"
cleanup() {
    docker logs "$name" 2>/dev/null || true
    docker cp "$name:/var/log/unitree-g1/boot.log" - 2>/dev/null | tar -xO 2>/dev/null || true
    docker rm -f "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --rm --entrypoint /usr/local/bin/unitree-g1-check.py "$image" image
# Default startup must reject absent Admiral drivers, not report readiness.
if docker run --rm --entrypoint /usr/local/bin/unitree-g1-check.py "$image" platform; then
    echo 'ERROR: hardware-free platform check unexpectedly passed' >&2; exit 1
fi
if [[ -n "${2:-}" ]]; then
    docker run --rm -v "$2:/run/test-driver:ro" -e LD_LIBRARY_PATH=/run/test-driver \
        --entrypoint /bin/bash "$image" -c '
        set -e
        for plugin in nvvidconv nvv4l2h264enc nvjpegenc; do
            gst-inspect-1.0 "$plugin" > /tmp/plugin.log 2>&1 || { cat /tmp/plugin.log; exit 1; }
            echo "PASS: $plugin registers with R39.2.1 drivers"
        done'
fi

docker run -d --name "$name" -e UNITREE_HARDWARE_CHECKS=0 \
    -e UNITREE_WATCHDOG_INTERVAL=1 -e UNITREE_APP_DIR=/tmp "$image" \
    /usr/bin/python3 -u -c 'import signal,time,sys; signal.signal(signal.SIGTERM,lambda *_: sys.exit(0)); print("APPLICATION_STARTED",flush=True); time.sleep(300)'
for _ in {1..90}; do
    docker logs "$name" 2>&1 | grep -q APPLICATION_STARTED && break
    sleep 1
done
docker logs "$name" 2>&1 | grep -q APPLICATION_STARTED
docker exec "$name" /etc/init.d/master_service status
docker exec "$name" /usr/local/bin/unitree-g1-status modules
docker exec "$name" /bin/sh -c '! ss -ltnH | grep -q ":1026 "'
docker exec "$name" jq -e '.Module.unitree_patch_pc4=="1.0.0.6" and .Module.video_hub_pc4=="1.0.1.1"' /unitree/robot/pkg/version/version.json
docker exec "$name" jq -e '.state=="waiting" or .state=="blocked"' /run/unitree-g1/camera.json
docker exec "$name" /unitree/sbin/mscli listservice
docker stop -t 25 "$name" >/dev/null
test "$(docker inspect -f '{{.State.ExitCode}}' "$name")" = 0
# Reuse the same writable rootfs; stale PID files must not prevent restart.
docker start "$name" >/dev/null
for _ in {1..30}; do
    docker exec "$name" /etc/init.d/master_service status >/dev/null 2>&1 && break
    sleep 1
done
docker exec "$name" /etc/init.d/master_service status
# Wait for this startup's new app process (logs also contain the first run).
for _ in {1..30}; do
    docker exec "$name" pgrep -f '^/usr/bin/python3 -u -c' >/dev/null 2>&1 && break
    sleep 1
done
# A user application exit (even exit 0) must not leave a falsely healthy stack.
docker exec "$name" pkill -TERM -f '^/usr/bin/python3 -u -c'
for _ in {1..30}; do
    [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == false ]] && break
    sleep 1
done
test "$(docker inspect -f '{{.State.Running}}' "$name")" = false
test "$(docker inspect -f '{{.State.ExitCode}}' "$name")" = 1
echo 'PASS: service startup, child CMD, graceful stop, rootfs reuse and app failure propagation'
