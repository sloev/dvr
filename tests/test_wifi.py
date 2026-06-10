import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import wifi

class TestWifi(unittest.TestCase):

    def setUp(self):
        self.wm = wifi.WifiManager()

    @patch('subprocess.check_output')
    def test_current_connection(self, mock_check_output):
        mock_check_output.return_value = "yes:MySSID:80:192.168.1.10\nno:Other:50:192.168.1.11\n"
        
        conn = self.wm.current_connection()
        self.assertEqual(conn['ssid'], "MySSID")
        self.assertEqual(conn['strength'], 80)
        self.assertEqual(conn['ip'], "192.168.1.10")

    @patch('subprocess.run')
    @patch('subprocess.check_output')
    def test_scan_sync(self, mock_check_output, mock_run):
        mock_check_output.return_value = "MySSID:80:WPA2:*\nOtherSSID:60:WPA1: \n"
        
        nets = self.wm._scan_sync()
        self.assertEqual(len(nets), 2)
        self.assertEqual(nets[0]['ssid'], "MySSID")
        self.assertEqual(nets[0]['strength'], 80)
        self.assertTrue(nets[0]['in_use'])

    @patch('subprocess.run')
    def test_connect_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        
        res = self.wm.connect("MySSID", "password")
        self.assertTrue(res)
        self.assertEqual(mock_run.call_count, 2) # connect + persist

    @patch('subprocess.check_output')
    def test_known_networks(self, mock_check_output):
        mock_check_output.return_value = "MySSID:802-11-wireless\nEth:802-3-ethernet\n"
        
        known = self.wm.known_networks()
        self.assertEqual(known, ["MySSID"])

if __name__ == '__main__':
    unittest.main()
