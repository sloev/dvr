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

if __name__ == '__main__':
    unittest.main()
