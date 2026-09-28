"""Hardware capability diagnostics without a Jetson or container startup."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'platform_check', Path(__file__).parents[1] / 'scripts/unitree-g1-check.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class VideoCapabilityTests(unittest.TestCase):
    def test_nano_does_not_probe_or_claim_hardware_encoder(self):
        for sku in ('0003', '0004', '0005'):
            board = {'model': 'Jetson', 'chosen/ids': f'3767-{sku}-0000 3768-0000-0000'}
            with self.subTest(sku=sku), patch.object(check, 'board_info', return_value=board), \
                    patch.object(check, 'execute') as execute:
                with self.assertRaisesRegex(RuntimeError, 'Orin Nano has no NVENC'):
                    check.video()
                execute.assert_not_called()

    def test_shared_carrier_does_not_misidentify_nx_as_nano(self):
        self.assertFalse(check.is_orin_nano('3767-0000-0000 3768-0000-0000'))
        self.assertFalse(check.is_orin_nano('3767-0001-0000 3768-0000-0000'))
        self.assertFalse(check.is_orin_nano('unavailable'))

    def test_robot_lan_rejects_predictable_name_even_with_correct_address(self):
        addresses = [{'ifname': 'enP8p1s0', 'addr_info': [
            {'local': '192.168.123.164', 'prefixlen': 24}]}]
        with patch.object(check, 'execute', return_value=json.dumps(addresses)) as execute:
            with self.assertRaisesRegex(RuntimeError, 'enP8p1s0.*hardcodes eth0'):
                check.lan()
            execute.assert_called_once()

    def test_robot_lan_accepts_eth0_with_pc1_route(self):
        addresses = [{'ifname': 'eth0', 'addr_info': [
            {'local': '192.168.123.164', 'prefixlen': 24}]}]
        route = [{'dev': 'eth0', 'prefsrc': '192.168.123.164'}]
        with patch.object(check, 'execute', side_effect=[json.dumps(addresses), json.dumps(route)]):
            check.lan()


if __name__ == '__main__':
    unittest.main()
