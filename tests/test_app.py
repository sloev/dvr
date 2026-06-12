import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Mock tkinter before importing app
mock_tk = MagicMock()
sys.modules['tkinter'] = mock_tk

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

import app

class TestDVRApp(unittest.TestCase):
    def setUp(self):
        self.pipeline = MagicMock()
        self.storage = MagicMock()
        self.wifi = MagicMock()
        self.root = MagicMock()

    def test_adjust_onion_alpha(self):
        app_inst = app.DVRApp.__new__(app.DVRApp)
        app_inst.pipeline = self.pipeline
        app_inst._stopmotion_mode = True
        app_inst._onion_enabled = True
        app_inst._onion_alpha = 0.5
        app_inst._onion_btn = MagicMock()

        # Decrement onion alpha
        app_inst._adjust_onion_alpha(-0.1)
        self.assertEqual(app_inst._onion_alpha, 0.4)
        self.pipeline.set_onion_alpha.assert_called_with(0.4)

        # Clamping at 0.1
        app_inst._onion_alpha = 0.1
        app_inst._adjust_onion_alpha(-0.1)
        self.assertEqual(app_inst._onion_alpha, 0.1)

        # Increment onion alpha
        app_inst._onion_alpha = 0.8
        app_inst._adjust_onion_alpha(0.1)
        self.assertEqual(app_inst._onion_alpha, 0.9)
        self.pipeline.set_onion_alpha.assert_called_with(0.9)

        # Clamping at 0.9
        app_inst._adjust_onion_alpha(0.1)
        self.assertEqual(app_inst._onion_alpha, 0.9)

    def test_do_delete_folder(self):
        app_inst = app.DVRApp.__new__(app.DVRApp)
        app_inst._refresh_clips = MagicMock()
        
        # Test directory deletion
        with patch('os.path.isdir', return_value=True), \
             patch('shutil.rmtree') as mock_rmtree:
            clip = {'path': '/some/stopmotion/proj_folder', 'name': 'proj_folder'}
            app_inst._do_delete(clip)
            mock_rmtree.assert_called_with('/some/stopmotion/proj_folder')

        # Test file deletion
        with patch('os.path.isdir', return_value=False), \
             patch('os.remove') as mock_remove:
            clip = {'path': '/some/file.mp4', 'name': 'file.mp4'}
            app_inst._do_delete(clip)
            mock_remove.assert_called_with('/some/file.mp4')

if __name__ == '__main__':
    unittest.main()
