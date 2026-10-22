"""Test setup. Runs before any program module is imported.

All program data goes to a throw-away folder (never your real settings), and
tkinter is replaced by a recording fake so the tests run without a display.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Always override: the tests wipe this folder, so it must never be a real one.
os.environ["DOTA_OVERLAY_HOME"] = tempfile.mkdtemp(prefix="dota-overlay-tests-")

from tests import helpers  # noqa: E402,F401  (installs the fakes)
