"""
Dota 2 draft overlay: a small always-on-top window with live suggestions.

Run it with Dota in borderless windowed mode:
  python draft_overlay.py

First run: the Settings window opens by itself. Enter your free Stratz token,
pick your bracket, and press "Update everything" to download the data. No
terminal commands are needed.

In the overlay:
  Team      which side you are on (radiant / dire)
  Pos       only suggest heroes played in that position (All = no filter)
  Meta      with a position: only the most played heroes there
  Me        your own slot (1-5, counted left to right on your side), so you
            are not counted as your own teammate; "-" = none
  Settings  token, bracket, weeks of meta data, and downloading data

With nothing picked yet (you are first pick) it shows the first-pick meta:
win% and pick% per hero for the selected position (all positions if "All").
Columns otherwise: Syn = synergy with your allies, Mat = matchup vs the
enemies, Tot = total, in percentage points of win rate.

Your choices (team, position, Meta, Me) are remembered between runs.
Drag the window by its background; right-click anywhere on it to quit.
The overlay re-asserts "always on top" four times a second and does not take
focus when clicked. It cannot draw over true exclusive fullscreen.

Options (starting values; the buttons override them):
  --team SIDE  --position N  --meta  --me N
  --top N          rows to show (default 8)
  --monitor N      monitor to capture (default 1)   --interval S  (default 1.0)
  --pos X,Y        where the window starts, in screen pixels (default 20,160)
  --alpha A        window opacity 0.2-1.0 (default 0.88)
  --slots-size WxH resolution the slot boxes were calibrated at (default 1920x1080,
                   ignored when slots.json is present)
  --plain-window   skip the Windows tweaks (no-focus-steal, hidden from taskbar)

Developer options:
  --dev            show a Snap button: saves preview.jpg (what the script sees),
                   snapshot.png (clean frame) and snapshot.txt (each slot's score).
                   `python draft_assistant.py learn snapshot.png SLOT "Hero"`
                   then teaches the reader a hero's look (e.g. a cosmetic set).
  --preview        write preview.jpg each second
  --debug          print every slot's best guess, score and margin each second
"""

import argparse
import os
import queue
import sys
import threading
import time
import webbrowser
from pathlib import Path

import cv2

import counter_score as cs
import draft_assistant as da
import draft_reader as dr
import updater
from version import __version__

BG, FG, DIM = "#10141c", "#e8e8e8", "#7f8c8d"
GOOD, BAD, WARN = "#58d68d", "#ec7063", "#e5a50a"
BTN, BTN_ON = "#1c2430", "#2e86c1"
FONT = ("Consolas", 12)
COUNTER_COLS = f"{'Hero':<16}{'Syn':>5}{'Mat':>6}{'Tot':>6}"
META_COLS = f"{'Hero':<16}{'Win%':>6}{'Pick%':>6}"
STATE_COLOUR = {"ok": "#1e8449", "stale": "#b9770e", "missing": "#c0392b"}


def _user32():
    """user32 with explicit types (needed for 64-bit window handles)."""
    import ctypes

    u = ctypes.windll.user32
    u.GetParent.argtypes = [ctypes.c_void_p]
    u.GetParent.restype = ctypes.c_void_p
    u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.GetWindowLongW.restype = ctypes.c_long
    u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    return u


def format_rows(names, rows, top):
    """Pure helper: [(text, colour)] for the ranked suggestions."""
    out = []
    for total, syn, mat, hid in rows[:top]:
        text = f"{names[hid][:16]:<16}{syn:>+5.1f}{mat:>+6.1f}{total:>+6.1f}"
        out.append((text, GOOD if total > 0 else BAD if total < 0 else FG))
    return out


def format_meta_rows(names, rows, top):
    """First-pick table rows: win% coloured against the 50% line."""
    out = []
    for hid, win, pick, _games in rows[:top]:
        colour = GOOD if win >= 51 else BAD if win < 49 else FG
        out.append((f"{names[hid][:16]:<16}{win:>6.1f}{pick:>6.1f}", colour))
    return out


def header_text(n_read, n_total, team, position, meta):
    mode = (f"pos {position}" + (" meta" if meta else "")) if position else "all heroes"
    return f"{team.title()} | read {n_read}/{n_total} | {mode}"


def parse_me(me):
    """'3' or 'radiant_3' -> 3; None -> None."""
    if me is None:
        return None
    try:
        return int(str(me).split("_")[-1])
    except ValueError:
        return None


def footer_text():
    """(text, colour) describing which data the overlay is using."""
    if not updater.is_ready():
        return "No data yet. Open Settings to download it.", WARN
    info, cfg = cs.get_info(), cs.load_config()
    got = info.get("matchups", {})
    bracket = got.get("bracket", cfg["bracket"])
    text = f"Data: {cs.bracket_label(bracket)} | {cs.current_weeks()} wk meta"
    if got.get("fetched"):
        text += f" | {got['fetched'][:10]}"
    if bracket != cfg["bracket"]:
        return "Bracket changed: update data in Settings.", WARN
    return text, DIM


class SettingsWindow:
    """Token, bracket, weeks and data downloads. A normal window (not the
    no-focus overlay style) so the token field can take keyboard input."""

    def __init__(self, overlay):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk, self.ov = tk, ttk, overlay
        self.q = queue.Queue()
        self.busy, self.alive = False, True
        cfg = cs.load_config()

        win = self.win = tk.Toplevel(overlay.root)
        win.title(f"Dota Draft Overlay v{__version__} - Settings")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.close)
        pad = {"padx": 8, "pady": 3}

        # --- Stratz token ---
        tk.Label(win, text="Stratz API token").grid(row=0, column=0, sticky="w", **pad)
        self.token_var = tk.StringVar(value=cfg.get("token", ""))
        tk.Entry(win, textvariable=self.token_var, show="*", width=46).grid(
            row=0, column=1, columnspan=2, sticky="we", **pad)
        link = tk.Label(win, text="Get a free token (opens stratz.com/api)",
                        fg="#2e86c1", cursor="hand2")
        link.grid(row=1, column=1, columnspan=2, sticky="w", padx=8)
        link.bind("<ButtonPress-1>", lambda e: webbrowser.open("https://stratz.com/api"))
        note = ("Using STRATZ_TOKEN from the environment (it takes priority)."
                if os.environ.get("STRATZ_TOKEN")
                else "Saved in config.json next to the program. Keep that file private.")
        tk.Label(win, text=note, fg=DIM).grid(row=2, column=1, columnspan=2, sticky="w", padx=8)

        # --- bracket and weeks ---
        tk.Label(win, text="Bracket").grid(row=3, column=0, sticky="w", **pad)
        self.bracket_map = {}
        self.bracket_var = tk.StringVar()
        self.bracket_box = ttk.Combobox(win, textvariable=self.bracket_var,
                                        state="readonly", width=24)
        self.bracket_box.grid(row=3, column=1, sticky="w", **pad)
        self.set_brackets(cs.FALLBACK_BRACKETS, cfg["bracket"])
        tk.Label(win, text="Matchups and position data are downloaded for this bracket.",
                 fg=DIM).grid(row=4, column=1, columnspan=2, sticky="w", padx=8)

        tk.Label(win, text="Weeks of meta").grid(row=5, column=0, sticky="w", **pad)
        self.weeks_var = tk.StringVar(value=str(cs.current_weeks()))
        tk.Spinbox(win, from_=1, to=cs.MAX_WEEKS, width=5,
                   textvariable=self.weeks_var).grid(row=5, column=1, sticky="w", **pad)
        tk.Label(win, text="For the position filters and first-pick table. "
                           "Changing it needs no download.",
                 fg=DIM).grid(row=6, column=1, columnspan=2, sticky="w", padx=8)
        self.save_btn = tk.Button(win, text="Save settings", command=self.save)
        self.save_btn.grid(row=7, column=1, sticky="w", **pad)

        # --- data ---
        ttk.Separator(win).grid(row=8, column=0, columnspan=3, sticky="we", pady=6)
        self.status_labels, self.task_buttons = {}, {}
        for i, task in enumerate(updater.TASKS):
            tk.Label(win, text=updater.LABELS[task]).grid(row=9 + i, column=0, sticky="w", **pad)
            lbl = tk.Label(win, text="", anchor="w", width=46)
            lbl.grid(row=9 + i, column=1, sticky="w", **pad)
            btn = tk.Button(win, text="Update", width=9, command=lambda t=task: self.start([t]))
            btn.grid(row=9 + i, column=2, **pad)
            self.status_labels[task], self.task_buttons[task] = lbl, btn
        self.all_btn = tk.Button(win, text="Update everything", command=lambda: self.start(list(updater.TASKS)))
        self.all_btn.grid(row=12, column=1, sticky="w", **pad)

        self.progress = ttk.Progressbar(win, mode="indeterminate", length=380)
        self.progress.grid(row=13, column=0, columnspan=3, sticky="we", padx=8, pady=4)
        self.log_box = tk.Text(win, height=8, width=70, state="disabled", bg="#f4f4f4")
        self.log_box.grid(row=14, column=0, columnspan=3, padx=8, pady=4)
        tk.Button(win, text="Close", command=self.close).grid(row=15, column=2, **pad)

        self.refresh_status()
        self.ov.root.after(100, self.poll)
        win.after(150, win.focus_force)
        if cs.get_token():                       # ask Stratz which brackets it offers
            threading.Thread(target=self._load_brackets, daemon=True).start()

    # ---- helpers --------------------------------------------------------
    def set_brackets(self, enums, current):
        self.bracket_map = {cs.bracket_label(e): e for e in enums}
        if current not in enums:                  # keep the saved choice selectable
            self.bracket_map[cs.bracket_label(current)] = current
        self.bracket_box.config(values=list(self.bracket_map))
        self.bracket_var.set(cs.bracket_label(current))

    def _load_brackets(self):
        self.q.put(("brackets", cs.available_brackets()))

    def log(self, text):
        if not self.alive:
            return
        self.log_box.config(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def refresh_status(self):
        if not self.alive:
            return
        for task, (state, text) in updater.status().items():
            self.status_labels[task].config(text=text, fg=STATE_COLOUR[state])

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.save_btn, self.all_btn, *self.task_buttons.values()):
            b.config(state=state)
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    # ---- actions --------------------------------------------------------
    def save(self):
        """Write the settings that are on screen to config.json."""
        cfg = cs.load_config()
        bracket = self.bracket_map.get(self.bracket_var.get(), cfg["bracket"])
        try:
            weeks = max(1, min(cs.MAX_WEEKS, int(self.weeks_var.get())))
        except ValueError:
            weeks = cs.current_weeks()
        self.weeks_var.set(str(weeks))
        token_changed = self.token_var.get().strip() != cfg.get("token", "")
        cs.save_config(token=self.token_var.get().strip(), bracket=bracket, weeks=weeks)
        self.ov.pools.clear()                     # the weeks setting changes the pools
        self.refresh_status()
        self.ov.update_footer()
        self.ov.refresh()
        if token_changed and cs.get_token():
            threading.Thread(target=self._load_brackets, daemon=True).start()

    def start(self, tasks):
        if self.busy:
            return
        self.save()
        self.set_busy(True)
        self.log(f"--- {time.strftime('%H:%M:%S')}: updating {', '.join(tasks)} ---")

        def work():
            results = updater.run(tasks, lambda msg: self.q.put(("log", msg)))
            self.q.put(("done", results))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        """Runs on the GUI thread; worker threads only talk to us through the queue."""
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "brackets" and self.alive:
                    self.set_brackets(payload, self.bracket_map.get(
                        self.bracket_var.get(), cs.load_config()["bracket"]))
                elif kind == "done":
                    self.finish(payload)
        except queue.Empty:
            pass
        if self.alive or self.busy:
            self.ov.root.after(150, self.poll)

    def finish(self, results):
        failed = [(t, m) for t, ok, m in results if not ok]
        for task, ok, msg in results:
            self.log(f"{updater.LABELS[task]}: " + ("done" if ok else f"FAILED - {msg}"))
        if not failed:
            self.log("All done. You can close this window.")
        if self.alive:
            self.set_busy(False)
        else:
            self.busy = False
        self.ov.load_data()
        self.ov.refresh()
        self.refresh_status()

    def close(self):
        self.alive = False
        self.win.destroy()
        self.ov.settings = None


class Overlay:
    def __init__(self, args):
        import tkinter as tk  # imported here so the helpers above need no GUI

        self.args = args
        cfg = cs.load_config()
        self.team = args.team or cfg.get("team") or "radiant"
        self.position = args.position if args.position is not None else cfg.get("position")
        self.meta = bool(args.meta or cfg.get("meta"))
        self.me_idx = parse_me(args.me) if args.me else parse_me(cfg.get("me"))
        self.pools, self.buttons = {}, {}
        self.last_picks, self.last_img = {}, None
        self.memory = da.SlotMemory()
        self.prev_key = self.shown_key = None
        self.names, self.templates, self.ready = {}, None, False
        self.settings = None

        root = self.root = tk.Tk()
        root.overrideredirect(True)            # no title bar
        root.attributes("-topmost", True)
        root.attributes("-alpha", args.alpha)
        root.configure(bg=BG)
        root.geometry(f"+{args.pos[0]}+{args.pos[1]}")
        draggable = [root]

        def label(text="", font=("Consolas", 10), fg=DIM, **kw):
            w = tk.Label(root, text=text, font=font, fg=fg, bg=BG, anchor="w",
                         justify="left", padx=8, **kw)
            w.pack(fill="x")
            draggable.append(w)
            return w

        self.title = label("Waiting for draft...", ("Consolas", 11, "bold"), pady=4)

        # --- control rows (clickable) ---
        def row(name, key, options, extra=None):
            frame = tk.Frame(root, bg=BG)
            frame.pack(fill="x", padx=8, pady=1)
            draggable.append(frame)
            tk.Label(frame, text=f"{name:<5}", font=("Consolas", 10), fg=DIM,
                     bg=BG).pack(side="left")
            for value, text in options + (extra or []):
                b = tk.Label(frame, text=text, font=("Consolas", 10), fg=FG, bg=BTN,
                             padx=6, pady=1, cursor="hand2")
                b.pack(side="left", padx=2)
                b.bind("<ButtonPress-1>", lambda e, k=key, v=value: self.on_button(k, v))
                b.bind("<Button-3>", lambda e: root.destroy())
                self.buttons[(key, value)] = b

        team_extra = [("settings", "Settings")]
        if args.dev:
            team_extra.append(("snap", "Snap"))
        row("Team", "team", [("radiant", "Radiant"), ("dire", "Dire")], extra=team_extra)
        row("Pos", "position", [(None, "All")] + [(i, str(i)) for i in range(1, 6)],
            extra=[("toggle", "Meta")])
        row("Me", "me", [(None, "-")] + [(i, str(i)) for i in range(1, 6)])
        self.style_buttons()

        self.ally_lbl = label("Allies: -", wraplength=330)
        self.enemy_lbl = label("Enemies: -", wraplength=330)
        self.cols = label(COUNTER_COLS)
        self.rows = [label("", FONT, FG) for _ in range(args.top)]
        self.footer = label("", ("Consolas", 9), DIM, pady=3)

        for w in draggable:
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._drag)
            w.bind("<Button-3>", lambda e: root.destroy())

        self.load_data()

    # ---- data -----------------------------------------------------------
    def load_data(self):
        """(Re)load hero names and portraits. True when drafts can be scored."""
        self.pools.clear()
        try:
            self.names, _ = cs.load()
            self.templates = da.load_templates()
            self.ready = True
        except (FileNotFoundError, ValueError, KeyError):
            self.names, self.templates, self.ready = {}, None, False
        self.update_footer()
        return self.ready

    def update_footer(self):
        text, colour = footer_text()
        self.footer.config(text=text, fg=colour)

    def open_settings(self):
        if self.settings is not None and self.settings.alive:
            self.settings.win.lift()
            self.settings.win.focus_force()
            return
        self.settings = SettingsWindow(self)

    # ---- dragging -------------------------------------------------------
    def _start_drag(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag(self, e):
        self.root.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    # ---- state ----------------------------------------------------------
    def on_button(self, key, value):
        if value == "toggle":
            self.meta = not self.meta
        elif value == "settings":
            self.open_settings()
            return
        elif value == "snap":
            self.snap()
            return
        elif key == "team":
            self.team = value
        elif key == "position":
            self.position = value
        elif key == "me":
            self.me_idx = value
        self.style_buttons()
        self.save_prefs()
        self.refresh()

    def choose(self, key, value):
        self.on_button(key, value)

    def toggle_meta(self):
        self.on_button("position", "toggle")

    def save_prefs(self):
        try:
            cs.save_config(team=self.team, position=self.position,
                           meta=self.meta, me=self.me_idx)
        except OSError:
            pass

    def style_buttons(self):
        selected = {("team", self.team), ("position", self.position), ("me", self.me_idx)}
        for (key, value), b in self.buttons.items():
            if value in ("settings", "snap"):
                continue
            on = self.meta if value == "toggle" else (key, value) in selected
            b.config(bg=BTN_ON if on else BTN)

    def me_slot(self):
        if self.me_idx is None:
            return None
        sided = any(k.split("_")[0] in ("radiant", "dire") for k in dr.SLOTS)
        return f"{self.team}_{self.me_idx}" if sided else f"ally_{self.me_idx}"

    def pool(self):
        if not self.position:
            return None
        key = (self.position, self.meta, cs.current_weeks())
        if key not in self.pools:
            self.pools[key] = cs.meta_pool(self.position, cs.META_TOP if self.meta else None)
        return self.pools[key]

    def split(self, picks):
        return da.split_picks(picks, self.me_slot(), self.team)

    def key_of(self, picks):
        allies, enemies = self.split(picks)
        return (tuple(sorted(allies)), tuple(sorted(enemies)))

    # ---- drawing --------------------------------------------------------
    def set_rows(self, items):
        for i, lbl in enumerate(self.rows):
            text, colour = items[i] if i < len(items) else ("", FG)
            lbl.config(text=text, fg=colour)

    def render(self, picks):
        if not self.ready:
            self.title.config(text="Setup needed: click Settings", fg=WARN)
            self.set_rows([])
            return
        allies, enemies = self.split(picks)
        self.ally_lbl.config(text="Allies: " + (", ".join(self.names[h] for h in allies) or "-"))
        self.enemy_lbl.config(text="Enemies: " + (", ".join(self.names[h] for h in enemies) or "-"))
        if not allies and not enemies:
            self.render_first_pick()
            return
        self.cols.config(text=COUNTER_COLS)
        try:
            names, ranked = cs.rank(allies, enemies, self.pool())
        except (FileNotFoundError, ValueError, KeyError):
            self.title.config(text="Download position data in Settings", fg=BAD)
            self.set_rows([])
            return
        n_read = len(allies) + len(enemies) + (1 if self.me_slot() in picks else 0)
        self.title.config(text=header_text(n_read, len(dr.SLOTS), self.team,
                                           self.position, self.meta), fg=FG)
        self.set_rows(format_rows(names, ranked, self.args.top))

    def render_first_pick(self):
        """No picks on screen yet: show the meta win% for the chosen position."""
        self.cols.config(text=META_COLS)
        try:
            rows = cs.meta_table(self.position, self.meta)
        except (FileNotFoundError, ValueError, KeyError):
            self.title.config(text="Download position data in Settings", fg=BAD)
            self.set_rows([])
            return
        mode = (f"pos {self.position}" + (" meta" if self.meta else "")) if self.position else "all positions"
        self.title.config(text=f"No picks yet | meta win% | {mode}", fg=FG)
        self.set_rows(format_meta_rows(self.names, rows, self.args.top))

    def refresh(self):
        """Redraw immediately after a click or a settings change, using the latest read."""
        self.render(self.last_picks)
        self.shown_key = self.key_of(self.last_picks)

    # ---- developer tools ------------------------------------------------
    def snap(self):
        """Save what the script sees right now (preview.jpg, snapshot.png,
        snapshot.txt) in the program's data folder, wherever it was started from."""
        if self.last_img is None or self.templates is None:
            self.title.config(text="Nothing captured yet", fg=BAD)
            return
        out = cs.DATA_DIR
        try:
            da.save_preview(self.last_img, str(out / "preview.jpg"))
            cv2.imwrite(str(out / "snapshot.png"), self.last_img)  # clean frame, for `learn`
            (out / "snapshot.txt").write_text(
                "\n".join(da.debug_lines(self.last_img, self.templates, self.names)))
        except OSError as exc:
            self.title.config(text=f"Could not save: {exc}"[:48], fg=BAD)
            return
        self.title.config(text="Saved snapshot files in the program folder", fg=GOOD)

    # ---- staying above the game (Windows) -------------------------------
    def _hwnd(self, u):
        child = self.root.winfo_id()
        return u.GetParent(child) or child

    def setup_window_style(self):
        """Don't take focus from the game when clicked; hide from the taskbar."""
        if sys.platform != "win32":
            return
        try:
            u = _user32()
            hwnd = self._hwnd(u)
            style = u.GetWindowLongW(hwnd, -20)                      # GWL_EXSTYLE
            u.SetWindowLongW(hwnd, -20, style | 0x08000080)          # NOACTIVATE | TOOLWINDOW
            # NOMOVE | NOSIZE | NOZORDER | NOACTIVATE | FRAMECHANGED
            u.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
        except Exception:
            pass

    def keep_on_top(self):
        """Re-claim the top-most layer. A game that is also top-most would
        otherwise cover us as soon as it is clicked."""
        try:
            self.root.attributes("-topmost", True)
            if sys.platform == "win32":
                import ctypes

                u = _user32()
                # HWND_TOPMOST; NOMOVE | NOSIZE | NOACTIVATE | SHOWWINDOW
                u.SetWindowPos(self._hwnd(u), ctypes.c_void_p(-1), 0, 0, 0, 0,
                               0x0001 | 0x0002 | 0x0010 | 0x0040)
        except Exception:
            pass
        self.root.after(250, self.keep_on_top)

    # ---- main loop ------------------------------------------------------
    def tick(self):
        a = self.args
        try:
            if not self.ready:
                self.render({})
            else:
                img = da.grab(a.monitor)
                self.last_img = img
                if a.preview:
                    da.save_preview(img, str(cs.DATA_DIR / "preview.jpg"))
                if a.debug:
                    da.debug_report(img, self.templates, self.names)
                picks = self.memory.update(da.read_draft(img, self.templates))
                self.last_picks = picks
                key = self.key_of(picks)
                # act only when two consecutive reads agree (ignores transitions)
                if key == self.prev_key and key != self.shown_key:
                    self.shown_key = key
                    self.render(picks)
                self.prev_key = key
        except Exception as exc:  # keep the overlay alive, show the problem
            self.title.config(text=f"error: {exc}"[:48], fg=BAD)
        self.root.after(int(a.interval * 1000), self.tick)

    def run(self):
        self.root.update_idletasks()
        if not getattr(self.args, "plain_window", False):
            self.setup_window_style()
        self.root.after(250, self.keep_on_top)
        self.root.after(300, self.tick)
        if not self.ready or not cs.get_token():
            self.root.after(700, self.open_settings)      # first run: set everything up
        self.root.mainloop()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--version", action="version", version=f"Dota Draft Overlay {__version__}")
    p.add_argument("--position", type=int, choices=range(1, 6))
    p.add_argument("--meta", action="store_true")
    p.add_argument("--team", choices=["radiant", "dire"], default=None)
    p.add_argument("--me", default=None)
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--monitor", type=int, default=1)
    p.add_argument("--interval", type=float, default=1.0)
    p.add_argument("--pos", default="20,160")
    p.add_argument("--alpha", type=float, default=0.88)
    p.add_argument("--slots-size", default="1920x1080")
    p.add_argument("--plain-window", action="store_true")
    p.add_argument("--dev", action="store_true")
    p.add_argument("--preview", action="store_true")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    try:
        da.SLOT_REF = tuple(int(v) for v in args.slots_size.lower().split("x"))
        args.pos = tuple(int(v) for v in args.pos.split(","))
        assert len(da.SLOT_REF) == 2 and len(args.pos) == 2
    except (ValueError, AssertionError):
        sys.exit("--slots-size looks like 1920x1080, --pos looks like 20,160")

    if da.use_slots_file():
        print(f"Using {da.SLOTS_FILE} for slot boxes")

    # keep window and capture coordinates in real pixels on scaled Windows displays
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    Overlay(args).run()


if __name__ == "__main__":
    main()
