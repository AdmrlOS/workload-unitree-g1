"""Verify guarded NVIDIA endpoint initialization without making real nodes."""
import importlib.util
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    'devices', Path(__file__).parents[1] / 'scripts/unitree-g1-devices.py')
devices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(devices)


class EncoderDeviceTests(unittest.TestCase):
    def setUp(self):
        self.driver = Mock()
        self.driver.is_symlink.return_value = True
        self.driver.is_dir.return_value = True
        self.device = Mock()
        self.device.lstat.return_value = SimpleNamespace(
            st_mode=stat.S_IFCHR | 0o660, st_rdev=os.makedev(1, 3))

    def test_absent_driver_never_creates_an_encoder_endpoint(self):
        self.driver.is_dir.return_value = False
        with patch.object(devices.os, 'mknod') as create:
            with self.assertRaisesRegex(RuntimeError, 'driver is not bound'):
                devices.prepare_encoder(self.driver, self.device)
            create.assert_not_called()

    def test_vendor_endpoint_is_created_with_restricted_permissions(self):
        with patch.object(devices.os, 'mknod') as create, \
                patch.object(devices.os, 'chown') as chown, \
                patch.object(devices.os, 'chmod') as chmod:
            devices.prepare_encoder(self.driver, self.device)
            create.assert_called_once_with(self.device, stat.S_IFCHR | 0o660, os.makedev(1, 3))
            chown.assert_called_once_with(self.device, 0, 28)
            chmod.assert_called_once_with(self.device, 0o660)

    def test_existing_valid_endpoint_is_left_unchanged(self):
        with patch.object(devices.os, 'mknod', side_effect=FileExistsError), \
                patch.object(devices.os, 'chown') as chown, \
                patch.object(devices.os, 'chmod') as chmod:
            devices.prepare_encoder(self.driver, self.device)
            chown.assert_not_called()
            chmod.assert_not_called()

    def test_regular_file_symlink_and_other_device_are_not_overwritten(self):
        for mode, number in [(stat.S_IFREG, 0), (stat.S_IFLNK, 0),
                             (stat.S_IFCHR, os.makedev(1, 5))]:
            self.device.lstat.return_value = SimpleNamespace(st_mode=mode, st_rdev=number)
            with self.subTest(mode=mode, number=number), \
                    patch.object(devices.os, 'mknod', side_effect=FileExistsError), \
                    patch.object(devices.os, 'chown') as chown:
                with self.assertRaisesRegex(RuntimeError, 'refusing to overwrite'):
                    devices.prepare_encoder(self.driver, self.device)
                chown.assert_not_called()


if __name__ == '__main__':
    unittest.main()
