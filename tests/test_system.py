import unittest
from unittest.mock import patch, mock_open, MagicMock
import os
import sys

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import system

class TestSystem(unittest.TestCase):

    @patch('subprocess.run')
    def test_shutdown(self, mock_run):
        system.shutdown()
        mock_run.assert_called_with(["systemctl", "poweroff"], check=False)

    @patch('subprocess.run')
    def test_reboot(self, mock_run):
        system.reboot()
        mock_run.assert_called_with(["systemctl", "reboot"], check=False)

    @patch('builtins.open', new_callable=mock_open, read_data="45000\n")
    def test_cpu_temp(self, mock_file):
        temp = system.cpu_temp()
        self.assertEqual(temp, 45.0)
        mock_file.assert_called_with("/sys/class/thermal/thermal_zone0/temp")

    @patch('builtins.open', side_effect=OSError)
    def test_cpu_temp_error(self, mock_file):
        temp = system.cpu_temp()
        self.assertEqual(temp, 0.0)

    @patch('builtins.open', new_callable=mock_open, read_data="1234.56 7890.12\n")
    def test_uptime_seconds(self, mock_file):
        uptime = system.uptime_seconds()
        self.assertEqual(uptime, 1234.56)
        mock_file.assert_called_with("/proc/uptime")

    @patch('subprocess.run')
    def test_save_setting_invalid_key(self, mock_run):
        res = system.save_setting("INVALID_KEY", "value")
        self.assertFalse(res)
        mock_run.assert_not_called()

    @patch('subprocess.run')
    @patch('os.path.exists', return_value=False)
    @patch('os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    def test_save_setting_dev_fallback(self, mock_file, mock_makedirs, mock_exists, mock_run):
        # Mock sudo failing
        mock_run.side_effect = Exception("sudo not found")
        
        res = system.save_setting("DVR_WIDTH", "1280")
        self.assertTrue(res)
        
        # Check dev fallback
        expected_path = os.path.expanduser("~/.config/dvr/dvr.env")
        mock_file.assert_called_with(expected_path, "w")
        mock_file().writelines.assert_called_with(["DVR_WIDTH=1280\n"])

    def test_format_duration(self):
        self.assertEqual(system.format_duration(0), "00:00")
        self.assertEqual(system.format_duration(65), "01:05")
        self.assertEqual(system.format_duration(3661), "01:01:01")

    def test_format_size(self):
        self.assertEqual(system.format_size(1024), "1 KB")
        self.assertEqual(system.format_size(1024 * 1024), "1 MB")
        self.assertEqual(system.format_size(1024 * 1024 * 1024), "1.1 GB") # 1e9 vs 1024^3
        # The code uses 1e9, 1e6, 1e3
        self.assertEqual(system.format_size(1000), "1 KB")
        self.assertEqual(system.format_size(1000000), "1 MB")
        self.assertEqual(system.format_size(1000000000), "1.0 GB")

    @patch('subprocess.run')
    def test_is_ntp_synced(self, mock_run):
        # Synced case
        mock_run.return_value = MagicMock(stdout="NTPSynchronized=yes\n", returncode=0)
        self.assertTrue(system.is_ntp_synced())
        
        # Unsynced case
        mock_run.return_value = MagicMock(stdout="NTPSynchronized=no\n", returncode=0)
        self.assertFalse(system.is_ntp_synced())

        # Error case
        mock_run.side_effect = Exception("timedatectl error")
        self.assertFalse(system.is_ntp_synced())

    @patch('os.path.isdir')
    @patch('os.listdir')
    @patch('os.path.isfile')
    @patch('os.path.getsize')
    @patch('os.stat')
    def test_list_clips(self, mock_stat, mock_getsize, mock_isfile, mock_listdir, mock_isdir):
        def isdir_side_effect(path):
            return path in ["/dir", "/dir/stopmotion", "/dir/stopmotion/proj_1"]
            
        def listdir_side_effect(path):
            if path == "/dir":
                return ["clip1.mp4", "stopmotion", "ignored.txt"]
            elif path == "/dir/stopmotion":
                return ["proj_1", "ignored_dir"]
            elif path == "/dir/stopmotion/proj_1":
                return ["frame_0001.jpg", "frame_0002.jpg"]
            return []

        def isfile_side_effect(path):
            return path in ["/dir/clip1.mp4", "/dir/stopmotion/proj_1/frame_0001.jpg", "/dir/stopmotion/proj_1/frame_0002.jpg"]

        mock_isdir.side_effect = isdir_side_effect
        mock_listdir.side_effect = listdir_side_effect
        mock_isfile.side_effect = isfile_side_effect
        mock_getsize.side_effect = lambda path: 1000000 if "frame_0001" in path else 2000000
        
        mock_stat_obj = MagicMock()
        mock_stat_obj.st_size = 5000000
        mock_stat_obj.st_mtime = 1234567.0
        mock_stat.return_value = mock_stat_obj

        clips = system.list_clips("/dir")
        self.assertEqual(len(clips), 2)
        
        # Check first clip (clip1.mp4)
        self.assertEqual(clips[0]["name"], "clip1.mp4")
        self.assertEqual(clips[0]["size_mb"], 5.0)
        self.assertEqual(clips[0]["path"], "/dir/clip1.mp4")
        
        # Check second clip (proj_1)
        self.assertEqual(clips[1]["name"], "proj_1")
        self.assertEqual(clips[1]["size_mb"], 3.0) # 1MB + 2MB
        self.assertEqual(clips[1]["path"], "/dir/stopmotion/proj_1")

if __name__ == '__main__':
    unittest.main()

