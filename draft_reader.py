"""
Dota 2 draft portrait matcher (prototype).

Step 1: python draft_reader.py fetch
        Downloads hero portraits + names (OpenDota list, Valve's CDN) into
        ./portraits/ next to this file. The overlay's Settings window does the
        same thing with a button.

Step 2: python draft_reader.py calibrate screenshot.png
        Shows the screenshot so you can click the top-left and bottom-right
        of ONE pick slot, then prints its pixel box. Do this for each slot
        (or measure the spacing) and put the boxes in SLOTS below.

Step 3: python draft_reader.py match screenshot.png
        Crops each slot in SLOTS, matches it against every portrait,
        and prints the best hero + confidence per slot.

Requires: pip install opencv-python numpy requests
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import requests

import paths

DATA_DIR = paths.data_dir()      # see paths.py for where this is
PORTRAIT_DIR = DATA_DIR / "portraits"
HEROES_JSON = PORTRAIT_DIR / "heroes.json"
CDN = "https://cdn.cloudflare.steamstatic.com"

# ---------------------------------------------------------------------------
# EDIT ME: pixel boxes (x, y, w, h) of each pick slot in YOUR resolution.
# Use `calibrate` to find them. Placeholders below are NOT real values.
# ---------------------------------------------------------------------------
SLOTS = {
    "enemy_1": (1000, 20, 80, 45),
    "enemy_2": (1090, 20, 80, 45),
    "enemy_3": (1180, 20, 80, 45),
    "enemy_4": (1270, 20, 80, 45),
    "enemy_5": (1360, 20, 80, 45),
}

# Portraits are resized to this before comparing (keeps matching cheap).
COMPARE_SIZE = (64, 36)
MIN_CONFIDENCE = 0.55  # below this, report "unknown" instead of guessing


def fetch(progress=print):
    """Download the hero list and portrait images (OpenDota list, Valve's CDN).

    Portraits already on disk are skipped, so re-running only fetches new heroes.
    Raises requests exceptions on network problems; the caller decides how to
    show them.
    """
    PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
    progress("Downloading the hero list...")
    r = requests.get("https://api.opendota.com/api/heroStats", timeout=30)
    r.raise_for_status()
    heroes = r.json()
    meta = {}
    for i, h in enumerate(heroes, 1):
        hid = h["id"]
        img_path = PORTRAIT_DIR / f"{hid}.png"
        if not img_path.exists():
            img = requests.get(CDN + h["img"], timeout=30)
            img.raise_for_status()
            img_path.write_bytes(img.content)
        meta[hid] = h["localized_name"]
        if i % 16 == 0 or i == len(heroes):
            progress(f"Portraits: {i}/{len(heroes)}")
    HEROES_JSON.write_text(json.dumps(meta))
    progress(f"Portraits saved: {len(meta)} heroes.")


def load_templates():
    meta = json.loads(HEROES_JSON.read_text())
    templates = {}
    for hid, name in meta.items():
        img = cv2.imread(str(PORTRAIT_DIR / f"{hid}.png"))
        if img is None:
            continue
        templates[name] = prep(img)
    return templates


def prep(img):
    """Resize + convert to float grayscale-ish vector features."""
    small = cv2.resize(img, COMPARE_SIZE, interpolation=cv2.INTER_AREA)
    return small.astype(np.float32)


def similarity(a, b):
    """Normalized correlation between two same-size images (-1..1)."""
    a = a.flatten() - a.mean()
    b = b.flatten() - b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def match_slot(crop, templates):
    feat = prep(crop)
    scores = sorted(
        ((similarity(feat, t), name) for name, t in templates.items()),
        reverse=True,
    )
    return scores[:3]


def match(path):
    img = cv2.imread(path)
    if img is None:
        sys.exit(f"Could not read {path}")
    templates = load_templates()
    for slot, (x, y, w, h) in SLOTS.items():
        crop = img[y : y + h, x : x + w]
        if crop.size == 0:
            print(f"{slot}: box is outside the image, check SLOTS")
            continue
        top = match_slot(crop, templates)
        best_score, best_name = top[0]
        label = best_name if best_score >= MIN_CONFIDENCE else "unknown"
        runner = ", ".join(f"{n} {s:.2f}" for s, n in top[1:])
        print(f"{slot}: {label} ({best_score:.2f})  | next: {runner}")


def calibrate(path):
    """Click top-left then bottom-right of a slot; prints x, y, w, h."""
    img = cv2.imread(path)
    if img is None:
        sys.exit(f"Could not read {path}")
    clicks = []

    def on_click(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN:
            clicks.append((x, y))
            if len(clicks) == 2:
                (x1, y1), (x2, y2) = clicks
                print(f"({min(x1,x2)}, {min(y1,y2)}, {abs(x2-x1)}, {abs(y2-y1)})")
                clicks.clear()

    cv2.namedWindow("calibrate", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("calibrate", on_click)
    print("Click top-left then bottom-right of a slot. Press q to quit.")
    while True:
        cv2.imshow("calibrate", img)
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
    elif sys.argv[1] == "fetch":
        fetch()
    elif sys.argv[1] == "calibrate" and len(sys.argv) == 3:
        calibrate(sys.argv[2])
    elif sys.argv[1] == "match" and len(sys.argv) == 3:
        match(sys.argv[2])
    else:
        print(__doc__)
