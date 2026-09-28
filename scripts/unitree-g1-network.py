#!/usr/bin/env python3
"""Name the already-provisioned G1 robot LAN eth0 before Unitree starts.

Admiral configures the physical port by MAC before launching a host-network
workload. Its udev daemon does not read rules from the OCI rootfs, so the
workload must perform this one-time netlink rename itself.
"""

import argparse
import json
import subprocess
import sys
import time


ROBOT_ADDRESS = '192.168.123.164'
ROBOT_PREFIX = 24
ROBOT_NETWORK = '192.168.123.0/24'
PC1_ADDRESS = '192.168.123.161'


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(f'{" ".join(args)}: {result.stderr.strip() or result.stdout.strip()}')
    return result.stdout


def ip_json(*args):
    return json.loads(command('ip', '-j', '-4', *args))


def robot_interfaces():
    return [interface['ifname'] for interface in ip_json('addr', 'show')
            if any(address.get('local') == ROBOT_ADDRESS
                   and address.get('prefixlen') == ROBOT_PREFIX
                   for address in interface.get('addr_info', []))]


def pc1_route(name):
    routes = ip_json('route', 'get', PC1_ADDRESS)
    return bool(routes and routes[0].get('dev') == name
                and routes[0].get('prefsrc') == ROBOT_ADDRESS)


def wait_for_carrier(name, timeout=20):
    # LinkSetUp returns before PHY autonegotiation finishes. The NX takes
    # about 3.5 seconds; routes remain linkdown until LOWER_UP appears.
    print(f'robot LAN waiting for Ethernet carrier on {name}', flush=True)
    deadline = time.monotonic() + timeout
    while True:
        links = json.loads(command('ip', '-j', 'link', 'show', 'dev', name))
        if len(links) == 1 and {'UP', 'LOWER_UP'} <= set(links[0].get('flags', [])):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f'Ethernet carrier did not recover on {name} within {timeout}s')
        time.sleep(0.5)


def repair_pc1_route(name, metric):
    if name not in robot_interfaces():
        try:
            command('ip', '-4', 'addr', 'add', f'{ROBOT_ADDRESS}/{ROBOT_PREFIX}', 'dev', name)
        except RuntimeError:
            if name not in robot_interfaces():
                raise
    if not pc1_route(name):
        try:
            command('ip', '-4', 'route', 'replace', ROBOT_NETWORK, 'dev', name,
                    'src', ROBOT_ADDRESS, 'metric', str(metric))
        except RuntimeError:
            if not pc1_route(name):
                raise
    if not pc1_route(name):
        raise RuntimeError(f'PC1 route did not recover through {name}')


def rename_robot_lan():
    names = robot_interfaces()
    if not names:
        return False
    if len(names) != 1:
        raise RuntimeError(f'{ROBOT_ADDRESS}/{ROBOT_PREFIX} occurs on multiple interfaces: {names}')
    source = names[0]
    if source == 'eth0':
        if not pc1_route('eth0'):
            raise RuntimeError('eth0 has the robot address but PC1 does not route through it')
        print('robot LAN already eth0; PC1 route is correct', flush=True)
        return True
    links = json.loads(command('ip', '-j', '-d', 'link', 'show'))
    if any(link.get('ifname') == 'eth0' for link in links):
        raise RuntimeError(f'eth0 already belongs to another interface; refusing to rename {source}')
    matches = [link for link in links if link.get('ifname') == source]
    if len(matches) != 1 or matches[0].get('link_type') != 'ether' or 'UP' not in matches[0].get('flags', []):
        raise RuntimeError(f'{source} is not an active Ethernet link; refusing to rename it')
    # Admiral's workload sysfs may hide /sys/class/net, so use the netlink
    # parent bus instead. Refuse veth, macvlan and other virtual interfaces.
    if matches[0].get('parentbus') not in ('pci', 'platform', 'usb') or matches[0].get('linkinfo'):
        raise RuntimeError(f'{source} is not a physical Ethernet device; refusing to rename it')
    if not pc1_route(source):
        raise RuntimeError(f'PC1 does not route through {source}; refusing to rename it')
    if any(route.get('dev') == source for route in ip_json('route', 'show', 'default')):
        raise RuntimeError(f'{source} carries the default route; refusing to interrupt management traffic')
    lan_routes = ip_json('route', 'show', ROBOT_NETWORK)
    metric = next((route.get('metric', 100) for route in lan_routes
                   if route.get('dev') == source), 100)

    # A running Ethernet link cannot reliably be renamed. The down/up flap is
    # confined to the robot LAN; Wi-Fi and its default route are untouched.
    renamed = False
    try:
        command('ip', 'link', 'set', 'dev', source, 'down')
        command('ip', 'link', 'set', 'dev', source, 'name', 'eth0')
        renamed = True
        command('ip', 'link', 'set', 'dev', 'eth0', 'up')
        wait_for_carrier('eth0')
        repair_pc1_route('eth0', metric)
    except Exception:
        # Restore the original name and PC1 path if validation fails. Do not
        # let an unsuccessful workaround strand the robot control network.
        current = 'eth0' if renamed else source
        try:
            command('ip', 'link', 'set', 'dev', current, 'down')
            if renamed:
                command('ip', 'link', 'set', 'dev', 'eth0', 'name', source)
            command('ip', 'link', 'set', 'dev', source, 'up')
            wait_for_carrier(source)
            repair_pc1_route(source, metric)
        except Exception as rollback_error:
            print(f'WARNING: robot LAN rollback failed: {rollback_error}', file=sys.stderr, flush=True)
        raise
    print(f'robot LAN renamed {source} -> eth0; {ROBOT_ADDRESS}/{ROBOT_PREFIX} and PC1 route verified',
          flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-seconds', type=int, default=10)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 60:
        parser.error('--wait-seconds must be between 0 and 60')
    try:
        deadline = time.monotonic() + args.wait_seconds
        while True:
            if rename_robot_lan():
                return 0
            if time.monotonic() >= deadline:
                raise RuntimeError(f'robot LAN {ROBOT_ADDRESS}/{ROBOT_PREFIX} not present')
            time.sleep(1)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'WARNING: robot LAN rename skipped or failed: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
