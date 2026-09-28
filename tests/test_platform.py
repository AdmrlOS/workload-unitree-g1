"""Hardware capability diagnostics without a Jetson or container startup."""
import importlib.util
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


if __name__ == '__main__':
    unittest.main()
