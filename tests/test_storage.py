import unittest
from unittest.mock import patch, MagicMock
import os
import sys
import json

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import storage

class TestStorage(unittest.TestCase):

    def setUp(self):
        self.sm = storage.StorageManager()

    def test_initial_state(self):
        self.assertEqual(self.sm.drives, {})
        self.assertIsNone(self.sm.primary_mount)

    @patch('os.statvfs')
    def test_free_bytes(self, mock_stat):
        mock_stat.return_value.f_bavail = 100
        mock_stat.return_value.f_frsize = 1024
        self.assertEqual(self.sm.free_bytes("/mnt"), 102400)

    @patch('subprocess.run')
    def test_eject_success(self, mock_run):
        self.sm._drives = {"/dev/sda1": "/run/media/pi/USB"}
        mock_run.return_value = MagicMock(returncode=0)
        
        res = self.sm.eject("/dev/sda1")
        self.assertTrue(res)
        self.assertEqual(self.sm.drives, {})
        self.assertEqual(mock_run.call_count, 3) # sync, unmount, power-off

    @patch('subprocess.check_output')
    def test_detect_usb_devices(self, mock_check_output):
        lsblk_json = {
            "blockdevices": [
                {
                    "name": "sda",
                    "tran": "usb",
                    "type": "disk",
                    "children": [
                        {"name": "sda1", "type": "part"}
                    ]
                },
                {
                    "name": "mmcblk0",
                    "tran": "sata", # not usb
                    "type": "disk",
                    "children": [{"name": "mmcblk0p1", "type": "part"}]
                }
            ]
        }
        mock_check_output.return_value = json.dumps(lsblk_json)
        
        devs = self.sm._detect_usb_devices()
        self.assertEqual(devs, {"/dev/sda1"})

    @patch('builtins.open', create=True)
    def test_mount_already_mounted(self, mock_open):
        mock_open.return_value = ["/dev/sda1 /run/media/pi/USB ext4 rw 0 0\n"]
        
        mp = self.sm._mount("/dev/sda1")
        self.assertEqual(mp, "/run/media/pi/USB")

if __name__ == '__main__':
    unittest.main()
