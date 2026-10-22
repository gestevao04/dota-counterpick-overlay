"""Where the program keeps its files.

Everything the program saves (config.json, cache/, portraits/, error.log)
lives in one "data folder":

  1. the folder in the DOTA_OVERLAY_HOME environment variable, if set
     (handy for tests, or to keep your data somewhere else);
  2. otherwise the folder the program sits in (the .exe's folder when
     packaged, the source folder when run from source) so the whole thing is
     portable;
  3. if that folder is not writable (for example under Program Files), a
     DotaDraftOverlay folder in %APPDATA%.

Read-only files that ship inside the program (the default slots.json) are
found through resource_dir().
"""

import os
import sys
from pathlib import Path

APP_NAME = "DotaDraftOverlay"


def frozen():
    """True inside a PyInstaller build."""
    return bool(getattr(sys, "frozen", False))


def _program_dir():
    if frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _writable(folder):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def data_dir():
    override = os.environ.get("DOTA_OVERLAY_HOME")
    if override:
        folder = Path(override).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    here = _program_dir()
    if _writable(here):
        return here
    fallback = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def resource_dir():
    """Folder holding the files bundled with the program."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS", _program_dir()))
    return Path(__file__).resolve().parent
