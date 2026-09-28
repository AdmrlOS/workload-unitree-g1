"""Hardware selection regressions using a synthetic sysfs tree, no fake /dev writes."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('camera', Path(__file__).parents[1] / 'scripts/unitree-g1-camera.py')
camera = importlib.util.module_from_spec(spec)
spec.loader.exec_module(camera)


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sys = self.root / 'class/video4linux'
        self.dev = self.root / 'dev'
        self.sys.mkdir(parents=True)
        self.dev.mkdir()

    def node(self, number, interface='03', serial='A', vendor='8086', product='0b3a', index='1'):
        usb = self.root / 'devices' / serial
        iface = usb / f'{serial}:1.{interface}'
        path = iface / 'video4linux' / f'video{number}'
        path.mkdir(parents=True, exist_ok=True)
        for name, value in [('idVendor', vendor), ('idProduct', product), ('serial', serial), ('devnum', index)]:
            (usb / name).write_text(value)
        (iface / 'bInterfaceNumber').write_text(interface)
        (self.sys / path.name).symlink_to(path)
        (self.dev / path.name).touch()

    def discover(self, **kwargs):
        return camera.discover(self.sys, self.dev, probe=lambda p: p.name != 'video5', **kwargs)

    def test_rgb_not_depth_metadata_or_unrelated_usb(self):
        self.node(0, interface='00')
        self.node(4)
        self.node(5)  # metadata rejected by QUERYCAP probe
        self.node(6, serial='B', product='0b07')
        self.assertEqual(self.discover()[0], self.dev / 'video4')

    def test_replug_and_stale_alias(self):
        self.node(4)
        before = self.discover()
        alias = self.dev / 'rlsen0'
        camera.reconcile_alias(before, alias)
        self.assertEqual(alias.resolve(), (self.dev / 'video4').resolve())
        (self.dev / 'video4').unlink()
        self.assertIsNone(self.discover())
        camera.reconcile_alias(None, alias)
        self.assertFalse(alias.is_symlink())
        (self.dev / 'video4').touch()
        (self.root / 'devices/A/devnum').write_text('2')
        self.assertNotEqual(before, self.discover())

    def test_ambiguous_camera_needs_serial(self):
        self.node(4)
        self.node(8, serial='B')
        with self.assertRaisesRegex(RuntimeError, 'multiple'):
            self.discover()
        self.assertEqual(self.discover(serial='B')[0], self.dev / 'video8')

    def test_regular_file_never_overwritten(self):
        alias = self.dev / 'rlsen0'
        alias.write_text('preserve')
        with self.assertRaises(RuntimeError):
            camera.reconcile_alias((self.dev / 'video4', ()), alias)
        self.assertEqual(alias.read_text(), 'preserve')

    def test_device_caps_override_aggregate_capture_flag(self):
        node = self.dev / 'video5'
        node.touch()
        def metadata_ioctl(fd, request, data, mutate):
            self.assertEqual(request, 0x80685600)
            struct.pack_into('=II', data, 84, 0x84000001, 0x04800000)
        with patch.object(camera.fcntl, 'ioctl', metadata_ioctl):
            self.assertFalse(camera.capture_device(node))

    def test_signal_cleanup_reaps_child(self):
        child = subprocess.Popen(['sleep', '30'], start_new_session=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        camera.terminate(child)
        self.assertIsNotNone(child.poll())

    def test_hotplug_stops_running_capture(self):
        camera.STOP.clear()
        with patch.object(camera, 'discover', return_value=None):
            self.assertFalse(camera.run_child(['sleep', '30'], ('old', ()), '', timeout=2))

    def test_exiting_video_hub_never_reports_running(self):
        camera.STOP.clear()
        with patch.object(camera, 'discover') as discover:
            started = []
            self.assertTrue(camera.run_child(['true'], ('camera', ()), '',
                                              on_started=lambda: started.append(True)))
            self.assertEqual(started, [])
            discover.assert_not_called()

    def test_missing_encoder_blocks_video_without_starting_capture(self):
        camera.STOP.clear()
        result = subprocess.CompletedProcess([], 1, 'Orin Nano has no NVENC')
        lan = subprocess.CompletedProcess([], 0, 'PASS: robot LAN')
        def stop_after_wait(_):
            camera.STOP.set()
            return True
        with patch.object(camera.subprocess, 'run', side_effect=[lan, result]), \
                patch.object(camera.STOP, 'wait', side_effect=stop_after_wait), \
                patch.object(camera, 'discover') as discover, \
                patch.object(camera, 'run_child') as run_child, \
                patch.object(camera, 'status') as status:
            camera.run('')
            status.assert_any_call('blocked', 'Orin Nano has no NVENC')
            discover.assert_not_called()
            run_child.assert_not_called()
        camera.STOP.clear()

    def test_wrong_robot_nic_blocks_before_camera_warmup(self):
        camera.STOP.clear()
        result = subprocess.CompletedProcess([], 1, 'robot LAN is enP8p1s0; eth0 required')
        with patch.object(camera.subprocess, 'run', return_value=result) as checks, \
                patch.object(camera.STOP, 'wait', side_effect=lambda _: camera.STOP.set() or True), \
                patch.object(camera, 'discover') as discover, \
                patch.object(camera, 'run_child') as run_child, \
                patch.object(camera, 'status') as status:
            camera.run('')
            self.assertEqual(checks.call_args.args[0][-1], 'lan')
            status.assert_any_call('blocked', 'robot LAN is enP8p1s0; eth0 required')
            discover.assert_not_called()
            run_child.assert_not_called()
        camera.STOP.clear()


if __name__ == '__main__':
    unittest.main()
