"""
Dota 2 draft assistant: screen reader + counter scorer in one tool.

Keep draft_reader.py and counter_score.py in the same folder. The overlay's
Settings window can do the three downloads below with a button; from a
terminal, before using this:
  1. python draft_reader.py fetch          (portraits, once)
  2. python counter_score.py fetch         (matchup data, after each patch)
  3. python counter_score.py fetch-meta    (position pick counts)
  4. Slot boxes: if a slots.json file sits in the folder it is used (uniform
     boxes, scaled to your capture size). Otherwise SLOTS in draft_reader.py
     must list your pick boxes (named ally_N / enemy_N, or radiant_N / dire_N).

Usage:
  python draft_assistant.py image draft.png --position 4 --meta
  python draft_assistant.py watch --team radiant --position 4 --meta --me radiant_3
  python draft_assistant.py learn snapshot.png radiant_4 Tidehunter

`learn` teaches the reader a hero's look when a player's cosmetics make the
portrait differ from the default one. It crops that slot from a saved frame
(use snapshot.png from the overlay's Snap button) and stores it in
portraits/extra/. Any hero can have several. Run it for each misread slot.

Options:
  --position N   only suggest heroes played in position N (1-5)
  --meta         with --position: only the most played heroes there
  --team SIDE    radiant or dire. Needed if your slots are named
                 radiant_1..5 / dire_1..5 instead of ally_N / enemy_N
  --me SLOT      ignore this slot (your own pick, e.g. radiant_3), so you
                 aren't counted as your own teammate
  --monitor N    which monitor `watch` captures (default 1 = primary)
  --interval S   seconds between captures in `watch` (default 1.0)
  --slots-size WxH  the resolution your SLOTS boxes were calibrated at
                 (default 1920x1080). They are scaled to the capture size,
                 so 1920x1080 boxes also work on a 2560x1440 screen.
  --preview      write preview.jpg each capture: the exact frame the script
                 sees, with your slot boxes drawn.
  --delay S      wait S seconds before `watch` starts, to switch to Dota
  --debug        every second, print each slot's best guess and score.

`watch` needs:  pip install mss
Capture works with Dota in borderless windowed. Slot coordinates must match
the captured image size (full monitor, native resolution).
"""

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import counter_score as cs
import draft_reader as dr
import paths


SLOT_REF = (1920, 1080)  # resolution the SLOTS boxes were calibrated at
SLOTS_FILE = cs.DATA_DIR / "slots.json"

# A slot counts as a pick when its best match clears a low floor (raw score)
# AND beats the runner-up clearly after hub correction (see read_scores).
# Empty slots score ~0.30 with ~0 margin; real picks scored 0.57+ with margins
# of +0.20 or more.
MIN_SCORE = 0.40
MIN_MARGIN = 0.10
HUB_WEIGHT = 0.5   # how hard to push down templates that match many slots
MISS_LIMIT = 5     # frames a read may fail before the hero is forgotten
LEARN_INSET = 3    # pixels trimmed off a learned crop (drops box outlines)


def use_slots_file():
    """If a slots.json exists, it replaces SLOTS in draft_reader.py and the
    calibration size. A slots.json in the data folder wins (edit it to adjust
    the boxes); otherwise the default shipped with the program is used.
    Format: {"ref_size": [W, H], "slots": {"radiant_1": [x, y, w, h], ...}}"""
    global SLOT_REF
    for candidate in (SLOTS_FILE, paths.resource_dir() / "slots.json"):
        if candidate.exists():
            data = json.loads(candidate.read_text())
            dr.SLOTS = {k: tuple(v) for k, v in data["slots"].items()}
            SLOT_REF = tuple(data["ref_size"])
            return True
    return False


def slots_for(img):
    """SLOTS scaled from their calibration resolution to this capture's size."""
    sx = img.shape[1] / SLOT_REF[0]
    sy = img.shape[0] / SLOT_REF[1]
    return {
        slot: (round(x * sx), round(y * sy), round(w * sx), round(h * sy))
        for slot, (x, y, w, h) in dr.SLOTS.items()
    }


# ----------------------------------------------------------------- matching --
def vec(img):
    """Image -> zero-mean unit vector (so a dot product is a correlation)."""
    v = dr.prep(img).flatten()
    v = v - v.mean()
    n = np.linalg.norm(v)
    return v / n if n else v


class TemplateBank:
    """Hero portraits (plus any learned extras) as one matrix for fast matching."""

    def __init__(self, primaries, extras=()):
        self.ids = sorted(primaries)
        owners = list(self.ids) + [h for h, _ in extras]
        vecs = [primaries[h] for h in self.ids] + [v for _, v in extras]
        self.T = np.stack(vecs).astype(np.float32)
        index = {h: i for i, h in enumerate(self.ids)}
        self.owner = np.array([index[h] for h in owners])
        self.n = len(self.ids)
        self.n_extras = len(extras)

    def hero_scores(self, F):
        """(k, d) slot vectors -> (k, n_heroes): best correlation per hero."""
        sims = F @ self.T.T
        S = sims[:, : self.n].copy()
        for e in range(self.n, self.T.shape[0]):  # learned extras
            h = self.owner[e]
            S[:, h] = np.maximum(S[:, h], sims[:, e])
        return S


def load_templates():
    meta = json.loads(dr.HEROES_JSON.read_text())
    primaries = {}
    for hid in meta:
        img = cv2.imread(str(dr.PORTRAIT_DIR / f"{hid}.png"))
        if img is not None:
            primaries[int(hid)] = vec(img)
    extras = []
    for f in sorted((dr.PORTRAIT_DIR / "extra").glob("*.png")):
        try:
            hid = int(f.stem.split("_")[0])
        except ValueError:
            continue
        img = cv2.imread(str(f))
        if img is not None and hid in primaries:
            extras.append((hid, vec(img)))
    return TemplateBank(primaries, extras)


def read_scores(img, bank):
    """Score every slot. Returns [(slot, first, second)], each of first/second
    being (raw_score, hero_id, adjusted_score).

    adjusted = raw - HUB_WEIGHT * (that hero's average raw score on the OTHER
    slots of this frame). A template that matches everything a little (a
    "hub", like Io's bright portrait) is pushed down, while a real pick, which
    matches only its own slot, is barely affected.
    """
    slots, feats = [], []
    for slot, (x, y, w, h) in slots_for(img).items():
        crop = img[y : y + h, x : x + w]
        if crop.size:
            slots.append(slot)
            feats.append(vec(crop))
    if not slots:
        return []
    S = bank.hero_scores(np.stack(feats))
    k = S.shape[0]
    hub = (S.sum(axis=0, keepdims=True) - S) / (k - 1) if k > 1 else np.zeros_like(S)
    A = S - HUB_WEIGHT * hub
    out = []
    for i, slot in enumerate(slots):
        j1, j2 = np.argsort(-A[i])[:2]
        out.append((
            slot,
            (float(S[i, j1]), bank.ids[j1], float(A[i, j1])),
            (float(S[i, j2]), bank.ids[j2], float(A[i, j2])),
        ))
    return out


def accepted(first, second):
    """Raw score above a floor, and a clear lead after hub correction."""
    return first[0] >= MIN_SCORE and first[2] - second[2] >= MIN_MARGIN


class SlotMemory:
    """Keeps a slot's last read for a few frames so one bad frame can't drop it."""

    def __init__(self, miss_limit=MISS_LIMIT):
        self.miss_limit = miss_limit
        self.picks, self.misses = {}, {}

    def update(self, fresh):
        for slot, val in fresh.items():
            self.picks[slot], self.misses[slot] = val, 0
        for slot in list(self.picks):
            if slot not in fresh:
                self.misses[slot] += 1
                if self.misses[slot] >= self.miss_limit:
                    del self.picks[slot], self.misses[slot]
        return dict(self.picks)


def read_draft(img, bank):
    """Return {slot: (hero_id, confidence)} for every confidently read slot."""
    picks = {}
    for slot, first, second in read_scores(img, bank):
        if accepted(first, second):
            picks[slot] = (first[1], first[0])
    # a hero can only be picked once: keep the more confident reading
    best = {}
    for slot, (hid, score) in picks.items():
        if hid not in best or score > picks[best[hid]][1]:
            best[hid] = slot
    return {slot: v for slot, v in picks.items() if best[v[0]] == slot}


def split_picks(picks, me=None, team=None):
    """Sort slots into allies/enemies.

    Slots named ally_N / enemy_N are used as-is. Slots named radiant_N /
    dire_N need --team to say which side you are on.
    """
    allies, enemies = [], []
    for slot, (hid, _) in picks.items():
        if slot == me:
            continue
        side = slot.split("_")[0]
        if side == "ally" or (side in ("radiant", "dire") and side == team):
            allies.append(hid)
        elif side in ("enemy", "radiant", "dire"):
            enemies.append(hid)
    return allies, enemies


# ------------------------------------------------------------------ output --
def show_suggestions(picks, names, args):
    allies, enemies = split_picks(picks, args.me, args.team)
    if not allies and not enemies:
        print("No heroes recognized yet. First-pick meta instead:")
        try:
            names_ = names
            rows = cs.meta_table(args.position, args.meta)
            print(f"{'Hero':<22}{'Win%':>7}{'Pick%':>8}")
            for h, win, pick, _g in rows[: args.top]:
                print(f"{names_[h]:<22}{win:>7.1f}{pick:>8.1f}")
        except (FileNotFoundError, ValueError):
            print("(run `python counter_score.py fetch-meta` to get win rates)")
        return
    print("\nAllies :", ", ".join(names[h] for h in allies) or "-")
    print("Enemies:", ", ".join(names[h] for h in enemies) or "-")
    pool = None
    if args.position:
        pool = cs.meta_pool(args.position, cs.META_TOP if args.meta else None)
    cs.suggest(allies, enemies, args.top, pool)


def debug_lines(img, bank, names):
    """Per-slot best guess, runner-up and margin, as a list of text lines."""
    lines = [f"capture {img.shape[1]}x{img.shape[0]}  "
             f"(accept: raw score >= {MIN_SCORE}, margin >= {MIN_MARGIN}; "
             f"{bank.n_extras} learned extra portraits)"]
    scored = {slot: (f, s) for slot, f, s in read_scores(img, bank)}
    for slot in slots_for(img):
        if slot not in scored:
            lines.append(f"  {slot:<9} box is outside the capture, recheck SLOTS")
            continue
        first, second = scored[slot]
        mark = "ok " if accepted(first, second) else "low"
        lines.append(
            f"  {slot:<9} {mark} {names.get(first[1], first[1]):<20} {first[0]:.2f}"
            f"   next: {names.get(second[1], second[1]):<18} {second[0]:.2f}"
            f"   margin {first[2] - second[2]:+.2f}")
    return lines


def debug_report(img, bank, names):
    print("\n".join(debug_lines(img, bank, names)))


def save_preview(img, path="preview.jpg"):
    """Save the captured frame with every slot box drawn on it."""
    out = img.copy()
    for slot, (x, y, w, h) in slots_for(img).items():
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(out, slot, (x, max(y - 6, 14)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 0), 1, cv2.LINE_AA)
    cv2.imwrite(path, out, [cv2.IMWRITE_JPEG_QUALITY, 85])


_sct = None


def grab(monitor):
    """Capture one monitor. The capture object is created once and reused."""
    global _sct
    if _sct is None:
        import mss  # imported here so `image` mode doesn't need it

        # newer mss versions renamed mss.mss to mss.MSS
        _sct = getattr(mss, "MSS", None) or mss.mss
        _sct = _sct()
    shot = np.array(_sct.grab(_sct.monitors[monitor]))
    return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)


# ------------------------------------------------------------------- learn --
def learn(path, slot, hero_text):
    """Store one slot of a saved frame as an extra portrait for a hero."""
    img = cv2.imread(path)
    if img is None:
        sys.exit(f"Could not read {path}")
    boxes = slots_for(img)
    if slot not in boxes:
        sys.exit(f"Unknown slot {slot!r}. Slots: {', '.join(boxes)}")
    names, _ = cs.load()
    hid = cs.resolve(hero_text, names)[0]
    x, y, w, h = boxes[slot]
    m = LEARN_INSET
    crop = img[y + m : y + h - m, x + m : x + w - m]
    if crop.size == 0:
        sys.exit("That slot's box is outside the image.")
    folder = dr.PORTRAIT_DIR / "extra"
    folder.mkdir(parents=True, exist_ok=True)
    n = len(list(folder.glob(f"{hid}_*.png"))) + 1
    out = folder / f"{hid}_{n}.png"
    cv2.imwrite(str(out), crop)
    print(f"Saved {out} as an extra portrait for {names[hid]}.")
    # show how the slot reads now
    bank = load_templates()
    for s, first, second in read_scores(img, bank):
        if s == slot:
            print(f"{slot} now reads: {names.get(first[1], first[1])} "
                  f"(raw {first[0]:.2f}, margin {first[2] - second[2]:+.2f}) -> "
                  f"{'accepted' if accepted(first, second) else 'still below the accept rule'}")


# -------------------------------------------------------------------- main --
def main():
    sys.stdout.reconfigure(line_buffering=True)  # show output immediately
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("mode", choices=["image", "watch", "learn"])
    p.add_argument("path", nargs="?", help="screenshot path (image / learn mode)")
    p.add_argument("rest", nargs="*", help="learn mode: SLOT HERO")
    p.add_argument("--position", type=int, choices=range(1, 6))
    p.add_argument("--meta", action="store_true")
    p.add_argument("--me", default=None)
    p.add_argument("--team", choices=["radiant", "dire"], default=None,
                   help="your side, needed when slots are named radiant_N / dire_N")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--monitor", type=int, default=1)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--slots-size", default="1920x1080",
                   help="resolution your SLOTS boxes were calibrated at (default "
                        "1920x1080); they are scaled to the capture size")
    p.add_argument("--preview", action="store_true",
                   help="save preview.jpg: the captured frame with slot boxes drawn")
    p.add_argument("--delay", type=float, default=0,
                   help="seconds to wait before `watch` starts capturing")
    p.add_argument("--debug", action="store_true",
                   help="print best guess + score for every slot each second")
    args = p.parse_args()

    global SLOT_REF
    try:
        SLOT_REF = tuple(int(v) for v in args.slots_size.lower().split("x"))
        assert len(SLOT_REF) == 2
    except (ValueError, AssertionError):
        sys.exit("--slots-size should look like 1920x1080")

    if use_slots_file():
        print(f"Using {SLOTS_FILE} (boxes for {SLOT_REF[0]}x{SLOT_REF[1]}, scaled to the capture)")

    if not (cs.CACHE / "matchups.json").exists():
        sys.exit("Run `python counter_score.py fetch` first.")
    if not dr.HEROES_JSON.exists():
        sys.exit("Run `python draft_reader.py fetch` first.")

    if args.mode == "learn":
        if not args.path or len(args.rest) < 2:
            sys.exit('Usage: python draft_assistant.py learn snapshot.png radiant_4 "Tidehunter"')
        learn(args.path, args.rest[0], " ".join(args.rest[1:]))
        return

    if args.meta and not args.position:
        sys.exit("--meta needs --position")
    if not args.team and any(k.split("_")[0] in ("radiant", "dire") for k in dr.SLOTS):
        sys.exit("Your slots are named radiant_/dire_: add --team radiant (or dire).")
    if args.position and not (cs.CACHE / "meta.json").exists():
        sys.exit("Run `python counter_score.py fetch-meta` first.")

    bank = load_templates()
    names, _ = cs.load()

    if args.mode == "image":
        if not args.path:
            sys.exit("Give a screenshot path.")
        img = cv2.imread(args.path)
        if img is None:
            sys.exit(f"Could not read {args.path}")
        if args.preview:
            save_preview(img)
            print("saved preview.jpg")
        if args.debug:
            debug_report(img, bank, names)
        show_suggestions(read_draft(img, bank), names, args)
        return

    if args.delay:
        print(f"Starting in {args.delay:.0f}s: switch to Dota now.")
        time.sleep(args.delay)
    print("Watching the screen. Ctrl+C to stop.")
    prev_key, shown_key, last_status = None, None, None
    memory = SlotMemory()
    while True:
        img = grab(args.monitor)
        if args.preview:
            save_preview(img)
        if args.debug:
            debug_report(img, bank, names)
        picks = memory.update(read_draft(img, bank))
        allies, enemies = split_picks(picks, args.me, args.team)
        key = (tuple(sorted(allies)), tuple(sorted(enemies)))
        # act only when two consecutive reads agree (ignores transitions)
        if key == prev_key and key != shown_key and (allies or enemies):
            show_suggestions(picks, names, args)
            shown_key = key
        prev_key = key
        status = len(allies) + len(enemies)
        if not args.debug and status != last_status:
            print(f"[{time.strftime('%H:%M:%S')}] recognized {status} hero(es) so far")
            last_status = status
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
