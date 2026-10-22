import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import launcher
import paths
from tests.helpers import HOME, reset_home


class PathsTests(unittest.TestCase):
    def test_env_override_is_used(self):
        self.assertEqual(paths.data_dir(), HOME)

    def test_frozen_build_uses_the_exe_folder(self):
        exe_dir = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ), mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", str(exe_dir / "DotaDraftOverlay.exe")):
            os.environ.pop("DOTA_OVERLAY_HOME")
            self.assertEqual(paths.data_dir(), exe_dir.resolve())

    def test_unwritable_program_folder_falls_back_to_appdata(self):
        appdata = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"APPDATA": appdata}), mock.patch.object(paths, "_writable", lambda f: False):
            os.environ.pop("DOTA_OVERLAY_HOME")
            self.assertEqual(paths.data_dir(), Path(appdata) / paths.APP_NAME)
            self.assertTrue((Path(appdata) / paths.APP_NAME).is_dir())

    def test_resource_dir_in_a_frozen_build_is_the_bundle(self):
        bundle = tempfile.mkdtemp()
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "_MEIPASS", bundle, create=True):
            self.assertEqual(paths.resource_dir(), Path(bundle))

    def test_default_slots_file_ships_with_the_program(self):
        self.assertTrue((paths.resource_dir() / "slots.json").exists())


class LauncherTests(unittest.TestCase):
    def setUp(self):
        reset_home()

    def test_selftest_passes_and_writes_its_report(self):
        self.assertEqual(launcher.selftest(), 0)
        self.assertIn("selftest ok", (HOME / "selftest.txt").read_text())

    def test_selftest_reports_a_missing_library(self):
        with mock.patch.dict(sys.modules, {"cv2": None}):        # makes `import cv2` fail
            self.assertEqual(launcher.selftest(), 1)
        report = (HOME / "selftest.txt").read_text()
        self.assertIn("FAILED", report)
        self.assertIn("cv2", report)

    def test_a_crash_is_written_to_error_log(self):
        with mock.patch.dict(sys.modules, {"draft_overlay": mock.Mock(main=mock.Mock(side_effect=RuntimeError("boom")))}), \
                mock.patch.object(sys, "argv", ["DotaDraftOverlay.exe"]), self.assertRaises(SystemExit) as cm:
            launcher.main()
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("boom", (HOME / "error.log").read_text())


if __name__ == "__main__":
    unittest.main()
