"""Shared test tools: a recording fake tkinter, a fake Stratz, and a builder
for a complete (synthetic) data folder."""
import re
import shutil
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

HEROES = list(range(1, 9))          # hero ids 1..8, names Hero1..Hero8


# ------------------------------------------------------------- fake tkinter
class Widget:
    """Records config() calls so tests can read what a label shows."""

    def __init__(self, *a, **kw):
        self.opts = {k: v for k, v in kw.items() if k != "textvariable"}
        self.afters, self.destroyed = [], False

    def config(self, **kw):
        self.opts.update(kw)

    configure = config

    def after(self, ms, fn=None):
        self.afters.append((ms, fn))

    def winfo_id(self):
        return 1

    def winfo_x(self):
        return 0

    def winfo_y(self):
        return 0

    def destroy(self):
        self.destroyed = True

    def __getattr__(self, name):        # pack, grid, bind, attributes, ...
        return lambda *a, **k: None


class Var:
    def __init__(self, value=""):
        self.v = value

    def get(self):
        return self.v

    def set(self, v):
        self.v = v


def install_fake_tk():
    tk = types.ModuleType("tkinter")
    for name in ("Tk", "Toplevel", "Label", "Frame", "Entry", "Button", "Spinbox", "Text"):
        setattr(tk, name, Widget)
    tk.StringVar = Var
    tk.Tcl = lambda: SimpleNamespace(eval=lambda script: "9.0")
    tk.ttk = SimpleNamespace(Combobox=Widget, Separator=Widget, Progressbar=Widget)
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = tk.ttk


install_fake_tk()
if "mss" not in sys.modules:           # only needed for the packaged self-test
    try:
        import mss  # noqa: F401
    except ImportError:
        sys.modules["mss"] = types.ModuleType("mss")

time.sleep = lambda seconds: None      # the downloaders pause between requests

import counter_score as cs   # noqa: E402
import draft_reader as dr    # noqa: E402
import paths                 # noqa: E402

HOME = paths.data_dir()


def reset_home():
    """Empty the throw-away data folder."""
    for name in ("cache", "portraits"):
        shutil.rmtree(HOME / name, ignore_errors=True)
    for name in ("config.json", "slots.json", "error.log", "selftest.txt"):
        (HOME / name).unlink(missing_ok=True)


# ------------------------------------------------------------- fake Stratz
def fake_gql(query, token=None):
    if "constants" in query:
        return {"constants": {"heroes": [{"id": i, "displayName": f"Hero{i}"} for i in HEROES]}}
    if "matchUp" in query:
        out = {}
        for hid in map(int, re.findall(r"h(\d+): matchUp", query)):
            rows = [{"heroId2": o, "matchCount": 500, "winCount": 250 + hid} for o in HEROES if o != hid]
            out[f"h{hid}"] = [{"heroId": hid, "vs": rows, "with": rows}]
        return {"heroStats": out}
    if "winWeek" in query:
        pos = int(re.search(r"POSITION_(\d)", query).group(1))
        rows = []
        for wk, (g, w) in zip((100, 200, 300, 400), ((1000, 400), (1000, 500), (1000, 600), (1000, 700))):
            for h in HEROES:
                big = (h + pos) % 4 != 0          # some heroes barely played in a position
                rows.append({"week": wk, "heroId": h, "matchCount": g if big else 1,
                             "winCount": w if big else 0})
        return {"heroStats": {"winWeek": rows}}
    raise AssertionError(f"unexpected query: {query[:80]}")


def _png(rng):
    art = cv2.resize(rng.integers(0, 255, (6, 10, 3), dtype=np.uint8), (128, 72),
                     interpolation=cv2.INTER_CUBIC)
    return cv2.imencode(".png", art)[1].tobytes()


def fake_get(url, timeout=None):
    rng = np.random.default_rng(abs(hash(url)) % (2 ** 32))
    if "heroStats" in url:
        data = [{"id": i, "localized_name": f"Hero{i}", "img": f"/h{i}.png"} for i in HEROES]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)
    return SimpleNamespace(raise_for_status=lambda: None, content=_png(rng))


def build_world():
    """Fill the data folder as a successful 'Update everything' would."""
    with mock.patch.object(cs, "gql", fake_gql), mock.patch.object(dr.requests, "get", fake_get):
        dr.fetch(lambda m: None)
        cs.set_info("portraits")
        cs.fetch(lambda m: None)
        cs.fetch_meta(lambda m: None)


# ---------------------------------------------------------------- frames
def make_frame(place, size=(1440, 2560)):
    """A draft screen with hero portraits in the given slots, using slots.json
    (2560x1440 reference boxes). place = {"radiant_1": 1, ...}."""
    import json

    slots = json.loads((paths.resource_dir() / "slots.json").read_text())["slots"]
    frame = np.full((*size, 3), 30, np.uint8)
    for slot, hero in place.items():
        x, y, w, h = slots[slot]
        art = cv2.imread(str(dr.PORTRAIT_DIR / f"{hero}.png"))
        frame[y:y + h, x:x + w] = cv2.resize(art, (w, h))
    return frame


def overlay_args(**kw):
    values = dict(position=None, meta=False, team=None, me=None, top=6, monitor=1, interval=1,
                  alpha=.9, pos=(20, 160), plain_window=False, dev=False, preview=False, debug=False)
    values.update(kw)
    return SimpleNamespace(**values)
