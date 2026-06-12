import unittest
import os
import sys
import time
import shutil
import threading

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import stubs

class TestStubs(unittest.TestCase):

    def test_fake_pipeline(self):
        p = stubs.FakePipeline()
        self.assertFalse(p.recording)
        self.assertEqual(p.rec_elapsed, 0.0)
        
        p.start_recording("/tmp")
        self.assertTrue(p.recording)
        time.sleep(0.1)
        self.assertGreater(p.rec_elapsed, 0.0)
        
        p.stop_recording()
        self.assertFalse(p.recording)
        
        self.assertTrue(p.query_signal())
        
        # Test level callback
        levels_called = [False]
        def on_level(pl, pr, rl, rr):
            levels_called[0] = True
        p.on_level = on_level
        time.sleep(0.2)
        self.assertTrue(levels_called[0])
        p.stop()

    def test_fake_storage(self):
        s = stubs.FakeStorage()
        self.assertIn(s._dev, s.drives)
        self.assertEqual(s.primary_mount, s._dir)
        self.assertEqual(s.free_gb(s._dir), 12.3)
        
        added_called = [False]
        def on_drive_added(dev, mp):
            added_called[0] = True
        s.on_drive_added = on_drive_added
        s.start()
        time.sleep(0.6)
        self.assertTrue(added_called[0])
        
        shutil.rmtree(s._dir)

    def test_fake_wifi(self):
        w = stubs.FakeWifi()
        self.assertTrue(w.is_connected())
        conn = w.current_connection()
        self.assertEqual(conn['ssid'], "Studio")
        
        nets = w.last_networks
        self.assertEqual(len(nets), 3)
        
        scan_called = [False]
        def on_scan(n):
            scan_called[0] = True
        w.scan(callback=on_scan)
        time.sleep(0.7)
        self.assertTrue(scan_called[0])

    def test_fake_pipeline_stopmotion(self):
        p = stubs.FakePipeline()
        p.set_onion_skin("/tmp/nonexistent.jpg", 0.5)
        p.set_onion_alpha(0.3)
        
        callback_called = threading.Event()
        def callback(success, err):
            self.assertTrue(success)
            self.assertEqual(err, "")
            callback_called.set()
            
        p.compile_stopmotion("/tmp", "/tmp/test_compile.mp4", fps=8, callback=callback)
        self.assertTrue(callback_called.wait(3.0))
        self.assertTrue(os.path.exists("/tmp/test_compile.mp4"))
        try:
            os.remove("/tmp/test_compile.mp4")
        except Exception:
            pass

if __name__ == '__main__':
    unittest.main()
