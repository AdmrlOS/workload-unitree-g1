"""Network rename tests use a fake ip command; they never change host links."""

import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'network_rename', Path(__file__).parents[1] / 'scripts/unitree-g1-network.py')
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class FakeIP:
    def __init__(self, name='enP8p1s0', default='wlan0', lose_config=False):
        self.name = name
        self.default = default
        self.address = True
        self.route = True
        self.up = True
        self.lose_config = lose_config
        self.operations = []
        self.fail_rename = False
        self.fail_route_replace_once = False
        self.clock = 0
        self.carrier_delay = 0
        self.carrier_at = 0

    def sleep(self, seconds):
        self.clock += seconds

    def __call__(self, *args):
        self.operations.append(args)
        if args == ('ip', '-j', '-4', 'addr', 'show'):
            return json.dumps([{'ifname': self.name, 'addr_info': [
                {'local': network.ROBOT_ADDRESS, 'prefixlen': network.ROBOT_PREFIX}
            ] if self.address else []}])
        if args == ('ip', '-j', '-d', 'link', 'show'):
            return json.dumps([{'ifname': self.name, 'link_type': 'ether',
                                'flags': ['UP'] if self.up else [], 'parentbus': 'pci'}])
        if args == ('ip', '-j', 'link', 'show', 'dev', self.name):
            flags = ['UP'] if self.up else []
            if self.up and self.clock >= self.carrier_at:
                flags.append('LOWER_UP')
            return json.dumps([{'ifname': self.name, 'flags': flags}])
        if args == ('ip', '-j', '-4', 'route', 'get', network.PC1_ADDRESS):
            return json.dumps([{'dev': self.name if self.route else self.default,
                                'prefsrc': network.ROBOT_ADDRESS if self.route else '192.168.15.154'}])
        if args == ('ip', '-j', '-4', 'route', 'show', 'default'):
            return json.dumps([{'dev': self.default}])
        if args == ('ip', '-j', '-4', 'route', 'show', network.ROBOT_NETWORK):
            return json.dumps([{'dev': self.name, 'metric': 100}])
        if args[:4] == ('ip', 'link', 'set', 'dev'):
            if args[-1] == 'down':
                self.up = False
                if self.lose_config:
                    self.address = False
                    self.route = False
                return ''
            if args[-1] == 'up':
                self.up = True
                self.carrier_at = self.clock + self.carrier_delay
                return ''
            if args[-2:] == ('name', 'eth0'):
                if self.fail_rename:
                    raise RuntimeError('rename denied')
                self.name = 'eth0'
                return ''
            if args[-2:] == ('name', 'enP8p1s0'):
                self.name = 'enP8p1s0'
                return ''
        if args[:4] == ('ip', '-4', 'addr', 'add'):
            self.address = True
            return ''
        if args[:4] == ('ip', '-4', 'route', 'replace'):
            if self.fail_route_replace_once:
                self.fail_route_replace_once = False
                raise RuntimeError('route replace denied')
            self.route = True
            return ''
        raise AssertionError(f'unexpected ip command: {args}')


class RobotNetworkTests(unittest.TestCase):
    def run_with(self, fake):
        with patch.object(network, 'command', side_effect=fake), \
                patch.object(network.time, 'sleep', side_effect=fake.sleep), \
                patch.object(network.time, 'monotonic', side_effect=lambda: fake.clock):
            return network.rename_robot_lan()

    def test_renames_only_verified_robot_port(self):
        fake = FakeIP()
        self.assertTrue(self.run_with(fake))
        self.assertEqual(fake.name, 'eth0')
        self.assertTrue(fake.up)
        self.assertIn(('ip', 'link', 'set', 'dev', 'enP8p1s0', 'name', 'eth0'), fake.operations)
        self.assertNotIn(('ip', 'link', 'set', 'dev', 'wlan0', 'down'), fake.operations)

    def test_restores_address_and_pc1_route_if_link_flap_drops_them(self):
        fake = FakeIP(lose_config=True)
        self.assertTrue(self.run_with(fake))
        self.assertEqual((fake.name, fake.address, fake.route), ('eth0', True, True))
        self.assertIn(('ip', '-4', 'addr', 'add', '192.168.123.164/24', 'dev', 'eth0'), fake.operations)
        self.assertIn(('ip', '-4', 'route', 'replace', '192.168.123.0/24',
                       'dev', 'eth0', 'src', '192.168.123.164', 'metric', '100'), fake.operations)

    def test_rejects_default_route_port_without_bringing_it_down(self):
        fake = FakeIP(default='enP8p1s0')
        with self.assertRaisesRegex(RuntimeError, 'default route'):
            self.run_with(fake)
        self.assertNotIn(('ip', 'link', 'set', 'dev', 'enP8p1s0', 'down'), fake.operations)

    def test_rename_failure_restores_original_link(self):
        fake = FakeIP()
        fake.fail_rename = True
        with self.assertRaisesRegex(RuntimeError, 'rename denied'):
            self.run_with(fake)
        self.assertEqual(fake.name, 'enP8p1s0')
        self.assertTrue(fake.up)
        self.assertIn(('ip', 'link', 'set', 'dev', 'enP8p1s0', 'up'), fake.operations)

    def test_route_repair_failure_rolls_back_name_and_recovers_pc1(self):
        fake = FakeIP(lose_config=True)
        fake.fail_route_replace_once = True
        with self.assertRaisesRegex(RuntimeError, 'route replace denied'):
            self.run_with(fake)
        self.assertEqual((fake.name, fake.up, fake.address, fake.route),
                         ('enP8p1s0', True, True, True))

    def test_already_named_eth0_is_idempotent(self):
        fake = FakeIP(name='eth0')
        self.assertTrue(self.run_with(fake))
        self.assertFalse(any(op[:2] == ('ip', 'link') for op in fake.operations))

    def test_nx_carrier_recovery_longer_than_three_seconds_does_not_rollback(self):
        fake = FakeIP(lose_config=True)
        fake.carrier_delay = 4
        self.assertTrue(self.run_with(fake))
        self.assertEqual(fake.name, 'eth0')
        self.assertEqual(fake.clock, 4)
        self.assertNotIn(('ip', 'link', 'set', 'dev', 'eth0', 'name', 'enP8p1s0'), fake.operations)

    def test_rollback_also_waits_for_carrier(self):
        fake = FakeIP(lose_config=True)
        fake.carrier_delay = 4
        fake.fail_route_replace_once = True
        with self.assertRaisesRegex(RuntimeError, 'route replace denied'):
            self.run_with(fake)
        self.assertEqual((fake.name, fake.clock, fake.address, fake.route),
                         ('enP8p1s0', 8, True, True))

    def test_carrier_wait_has_a_deadline(self):
        fake = FakeIP()
        fake.carrier_at = 100
        with patch.object(network, 'command', side_effect=fake), \
                patch.object(network.time, 'sleep', side_effect=fake.sleep), \
                patch.object(network.time, 'monotonic', side_effect=lambda: fake.clock):
            with self.assertRaisesRegex(RuntimeError, 'carrier did not recover'):
                network.wait_for_carrier(fake.name, timeout=2)
        self.assertEqual(fake.clock, 2)


if __name__ == '__main__':
    unittest.main()
