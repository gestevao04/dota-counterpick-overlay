"""
Dota 2 counter + synergy scorer, Stratz data.

Settings live in config.json next to this file (token, bracket, weeks). The
overlay's Settings window edits it; from a terminal use the `config` command.
The environment variable STRATZ_TOKEN, if set, takes priority over the token
in config.json.

Commands:
  python counter_score.py config [--token T] [--bracket LEGEND_ANCIENT] [--weeks 2]
      Show or change the settings. Brackets: HERALD_GUARDIAN, CRUSADER_ARCHON,
      LEGEND_ANCIENT, DIVINE_IMMORTAL (Stratz may offer others).

  python counter_score.py fetch
      Downloads matchup + synergy data for every hero into ./cache/
      (about 16 requests, batched). Re-run after each patch.

  python counter_score.py fetch-meta
      Downloads weekly per-position pick and win counts so suggestions can be
      filtered by position and by "Meta Only", and for the first-pick table.
      The number of weeks that count is a setting and can change without
      downloading again.

  python counter_score.py suggest --enemy "Lifestealer, Doom" --ally "Tiny" --top 10
      Ranks heroes by synergy with your allies + matchup against the enemies.
      Add --position 4 [--meta] to filter (needs fetch-meta).

  python counter_score.py first-pick --position 1 --meta --top 15
      Win rate and pick rate per hero for a position (or all positions), for
      when you pick first and nothing is on screen yet. Needs fetch-meta.

  python counter_score.py meta
      DISCOVERY: lists what Stratz's winWeek query accepts and returns.

How the score works (all in percentage points of win rate):
  matchup(c, e)  = winrate(c vs e)   - baseline(c)
  synergy(c, a)  = winrate(c with a) - average(baseline(c), baseline(a))
  meta(c)        = pick_rate_pct(c)  * META_LEVERAGE
  Each delta is shrunk toward 0 by  n / (n + K)  so small samples count less.
  total = sum of synergies with allies + sum of matchups vs enemies + meta
"""

import argparse
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

import paths

URL = "https://api.stratz.com/graphql"
DATA_DIR = paths.data_dir()      # see paths.py for where this is
CACHE = DATA_DIR / "cache"
CONFIG_FILE = DATA_DIR / "config.json"
K = 300      # shrinkage strength: a pair needs ~K games to count at half weight
BATCH = 8    # heroes per request
META_TAKE = 20000   # row limit per position query (Stratz may cap this lower)
META_TOP = 15       # --meta keeps the N most played heroes per position
MIN_SHARE = 0.01    # --position keeps heroes with >= 1% of that position's picks
SHRINK_K = 200      # first-pick table: games of prior pulling win rates toward the average
MIN_SHARE_ALL = 0.004  # first-pick table with no position: ignore heroes under 0.4% of picks
MAX_WEEKS = 12

# Restrict downloaded meta data to standard ranked games. Stratz's winWeek
# accepts gameModeIds, but matchUp does NOT.
GAME_MODE = "ALL_PICK_RANKED"
# How much to reward heroes with high pick rates from the ranked meta.
# E.g., a hero with a 20% pick rate gets +10.0 points to their total score.
META_LEVERAGE = 0.5

# Individual rank names Stratz uses for winWeek; a bracket group is two of them
# joined by "_" (LEGEND_ANCIENT -> LEGEND, ANCIENT).
RANKS = {"UNCALIBRATED", "HERALD", "GUARDIAN", "CRUSADER", "ARCHON",
         "LEGEND", "ANCIENT", "DIVINE", "IMMORTAL"}
FALLBACK_BRACKETS = ["HERALD_GUARDIAN", "CRUSADER_ARCHON", "LEGEND_ANCIENT", "DIVINE_IMMORTAL"]

DEFAULT_CONFIG = {
    "token": "", "bracket": "LEGEND_ANCIENT", "weeks": 2,
    # overlay choices, remembered between runs
    "team": "radiant", "position": None, "meta": False, "me": None,
}


class StratzError(Exception):
    """Something went wrong talking to Stratz. The message is safe to show a user."""


# ------------------------------------------------------------------ Config --
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text()))
    except (FileNotFoundError, ValueError):
        pass
    return cfg


def save_config(**changes):
    cfg = load_config()
    cfg.update(changes)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=1))
    return cfg


def get_token():
    """STRATZ_TOKEN from the environment wins over the one in config.json."""
    return (os.environ.get("STRATZ_TOKEN") or load_config().get("token") or "").strip()


def current_weeks():
    try:
        return max(1, min(MAX_WEEKS, int(load_config().get("weeks", 2))))
    except (TypeError, ValueError):
        return 2


def bracket_ranks(bracket):
    """'LEGEND_ANCIENT' -> ['LEGEND', 'ANCIENT']; rejects anything unexpected."""
    parts = str(bracket).upper().split("_")
    if not parts or any(p not in RANKS for p in parts):
        raise StratzError(f"Unknown bracket {bracket!r}")
    return parts


def bracket_label(bracket):
    return " / ".join(p.title() for p in str(bracket).split("_"))


def get_info():
    """What each downloaded dataset was fetched with (bracket, date)."""
    try:
        return json.loads((CACHE / "info.json").read_text())
    except (FileNotFoundError, ValueError):
        return {}


def set_info(key, **fields):
    CACHE.mkdir(parents=True, exist_ok=True)
    info = get_info()
    info[key] = dict(fields, fetched=time.strftime("%Y-%m-%d %H:%M"))
    (CACHE / "info.json").write_text(json.dumps(info, indent=1))


# ----------------------------------------------------------------- Stratz --
def gql(query, token=None):
    token = (token or get_token()).strip()
    if not token:
        raise StratzError("No Stratz token yet. Get a free one at stratz.com/api and "
                          "enter it in Settings.")
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "STRATZ_API",  # required by Stratz's Cloudflare
        "Content-Type": "application/json",
    }
    r = None
    for attempt in range(4):
        try:
            r = requests.post(URL, json={"query": query}, headers=headers, timeout=90)
        except requests.RequestException as exc:
            raise StratzError(f"Network error talking to Stratz: {exc}") from exc
        if r.status_code == 429:  # rate limited
            time.sleep(5 * (attempt + 1))
            continue
        break
    if r.status_code in (401, 403):
        raise StratzError(f"Stratz rejected the token (HTTP {r.status_code}). "
                          "Check it at stratz.com/api.")
    try:
        data = r.json()
    except ValueError:
        raise StratzError(f"Unexpected answer from Stratz (HTTP {r.status_code}).") from None
    if "errors" in data:
        first = data["errors"][0].get("message", "unknown error")
        raise StratzError(f"Stratz error: {first}"[:300])
    return data["data"]


def fetch(progress=print):
    """Download every hero's matchup and synergy data for the configured bracket."""
    bracket = load_config()["bracket"]
    bracket_ranks(bracket)  # validates before it goes into a query
    CACHE.mkdir(parents=True, exist_ok=True)
    progress("Downloading the hero list...")
    heroes = gql("query { constants { heroes { id displayName } } }")["constants"]["heroes"]
    names = {h["id"]: h["displayName"] for h in heroes}
    (CACHE / "heroes.json").write_text(json.dumps(names))
    ids = sorted(names)

    matrix = {}
    for i in range(0, len(ids), BATCH):
        chunk = ids[i : i + BATCH]
        body = "".join(
            f"h{hid}: matchUp(heroId: {hid}, bracketBasicIds: {bracket}, take: 200) "
            "{ heroId vs { heroId2 matchCount winCount } "
            "with { heroId2 matchCount winCount } } "
            for hid in chunk
        )
        data = gql("query { heroStats { " + body + " } }")["heroStats"]
        for hid in chunk:
            rows = data.get(f"h{hid}") or []
            if not rows:
                continue
            row = rows[0]
            matrix[hid] = {
                "vs": {r["heroId2"]: [r["matchCount"], r["winCount"]] for r in row["vs"]},
                "with": {r["heroId2"]: [r["matchCount"], r["winCount"]] for r in row["with"]},
            }
        progress(f"Matchups: {min(i + BATCH, len(ids))}/{len(ids)} heroes")
        time.sleep(1)
    (CACHE / "matchups.json").write_text(json.dumps(matrix))
    set_info("matchups", bracket=bracket)
    progress(f"Matchups saved: {len(matrix)} heroes, {bracket_label(bracket)}.")


# ---------------------------------------------------------------- Scoring --
def load():
    names = {int(k): v for k, v in json.loads((CACHE / "heroes.json").read_text()).items()}
    raw = json.loads((CACHE / "matchups.json").read_text())
    matrix = {
        int(h): {
            kind: {int(k): v for k, v in rows.items()} for kind, rows in d.items()
        }
        for h, d in raw.items()
    }
    return names, matrix


def baselines(matrix):
    """A hero's overall win rate, pooled across all its matchup rows."""
    base = {}
    for h, d in matrix.items():
        n = sum(r[0] for r in d["vs"].values())
        w = sum(r[1] for r in d["vs"].values())
        base[h] = w / n if n else 0.5
    return base


def shrink(delta, n):
    return delta * n / (n + K)


def matchup_score(matrix, base, c, e):
    n, w = matrix[c]["vs"].get(e, (0, 0))
    if n == 0:
        return 0.0
    return shrink(w / n - base[c], n) * 100


def synergy_score(matrix, base, c, a):
    n, w = matrix[c]["with"].get(a, (0, 0))
    if n == 0:
        return 0.0
    expected = (base[c] + base.get(a, 0.5)) / 2
    return shrink(w / n - expected, n) * 100


def rank(allies, enemies, pool=None):
    """Return (names, rows) with rows = [(total, synergy, matchup, hero_id)] best first."""
    names, matrix = load()
    base = baselines(matrix)
    taken = set(allies) | set(enemies)

    # Calculate pick rates from the ranked meta data for leverage
    pick_rates = {}
    try:
        meta_data = _load_meta()
        all_games = sum(v[0] for pos in meta_data.values() for v in pos.values())
        if all_games > 0:
            raw_picks = {}
            for pos in meta_data.values():
                for h, v in pos.items():
                    raw_picks[h] = raw_picks.get(h, 0) + v[0]
            for h, games in raw_picks.items():
                pick_rates[h] = (games / all_games) * 100  # convert to percentage
    except (FileNotFoundError, ValueError, KeyError):
        pass # If meta.json is missing, pick_rates is empty and leverage is 0

    rows = []
    for c in matrix:
        if c in taken or (pool is not None and c not in pool):
            continue
        syn = sum(synergy_score(matrix, base, c, a) for a in allies)
        mat = sum(matchup_score(matrix, base, c, e) for e in enemies)
        meta = pick_rates.get(c, 0.0) * META_LEVERAGE
        total = syn + mat + meta
        rows.append((total, syn, mat, c))
    rows.sort(reverse=True)
    return names, rows


def suggest(allies, enemies, top, pool=None):
    names, rows = rank(allies, enemies, pool)
    print(f"{'Hero':<22}{'Syn':>7}{'Mat':>7}{'Total':>8}")
    for total, syn, mat, c in rows[:top]:
        print(f"{names[c]:<22}{syn:>+7.1f}{mat:>+7.1f}{total:>+8.1f}")


def resolve(text, names):
    """Turn 'lifestealer, doom' into hero ids, with forgiving matching."""
    lookup = {v.lower(): k for k, v in names.items()}
    out = []
    for part in [p.strip().lower() for p in text.split(",") if p.strip()]:
        if part in lookup:
            out.append(lookup[part])
            continue
        subs = [n for n in lookup if part in n]
        if len(subs) == 1:
            out.append(lookup[subs[0]])
            continue
        close = difflib.get_close_matches(part, list(lookup), n=1, cutoff=0.6)
        if close:
            out.append(lookup[close[0]])
        else:
            sys.exit(f"Unknown hero: {part!r}")
    return out


# ---------------------------------------------------------- Position meta --
def fetch_meta(progress=print):
    """Download weekly games and wins per hero for each position.

    Stored per week (not pre-summed) so the number of weeks that count can be
    changed in Settings without downloading again.
    """
    bracket = load_config()["bracket"]
    ranks = ", ".join(bracket_ranks(bracket))
    CACHE.mkdir(parents=True, exist_ok=True)
    mode = f", gameModeIds: [{GAME_MODE}]" if GAME_MODE else ""

    positions, all_weeks = {}, set()
    for pos in range(1, 6):
        progress(f"Position data: {pos}/5")
        q = (
            "query { heroStats { winWeek(take: %d, bracketIds: [%s], "
            "positionIds: [POSITION_%d]%s) { week heroId matchCount winCount } } }"
            % (META_TAKE, ranks, pos, mode)
        )
        rows = gql(q)["heroStats"]["winWeek"]
        if len(rows) >= META_TAKE:
            progress("  Warning: hit Stratz's row limit, counts may be truncated.")
        heroes = {}
        for r in rows:
            wk = str(r["week"])
            all_weeks.add(r["week"])
            cell = heroes.setdefault(str(r["heroId"]), {}).setdefault(wk, [0, 0])
            cell[0] += r["matchCount"]
            cell[1] += r["winCount"]
        positions[str(pos)] = heroes
        time.sleep(1)
    data = {"version": 2, "weeks": sorted(all_weeks), "positions": positions}
    (CACHE / "meta.json").write_text(json.dumps(data))
    set_info("meta", bracket=bracket, weeks_available=len(all_weeks))
    progress(f"Position data saved: {len(all_weeks)} weeks, {bracket_label(bracket)}.")


def _games(v):
    """Entries are [games, wins]; the oldest files stored just the games."""
    return v[0] if isinstance(v, list) else v


def meta_weeks_available():
    """How many weeks the downloaded position data covers (None if unknown)."""
    try:
        raw = json.loads((CACHE / "meta.json").read_text())
    except (FileNotFoundError, ValueError):
        return None
    return len(raw["weeks"]) if isinstance(raw, dict) and raw.get("version") == 2 else None


def _load_meta(weeks=None):
    """-> {position: {hero_id: [games, wins]}} over the most recent `weeks` weeks."""
    raw = json.loads((CACHE / "meta.json").read_text())
    if isinstance(raw, dict) and raw.get("version") == 2:
        recent = {str(w) for w in raw["weeks"][-(weeks or current_weeks()):]}
        out = {}
        for pos, heroes in raw["positions"].items():
            out[pos] = {}
            for hid, per_week in heroes.items():
                g = sum(v[0] for wk, v in per_week.items() if wk in recent)
                w = sum(v[1] for wk, v in per_week.items() if wk in recent)
                if g:
                    out[pos][int(hid)] = [g, w]
        return out
    # older files were already summed over a fixed number of weeks
    return {pos: {int(h): v for h, v in heroes.items()} for pos, heroes in raw.items()}


def meta_pool(position, top=None):
    counts = {h: _games(v) for h, v in _load_meta()[str(position)].items()}
    total = sum(counts.values()) or 1
    ranked = sorted(counts, key=counts.get, reverse=True)
    if top:
        return set(ranked[:top])
    return {h for h in ranked if counts[h] / total >= MIN_SHARE}


def meta_table(position=None, meta=False):
    """First-pick table for when nothing is picked yet.

    Returns [(hero_id, win_pct, pick_pct, games)] best first. Ranked by a
    shrunk win rate (pulled toward the average with SHRINK_K games of prior,
    so a hero with a lucky small sample doesn't top the list). position=None
    combines all five positions. Raises ValueError if the downloaded data has
    no win counts (download it again).
    """
    data = _load_meta()
    positions = [str(position)] if position else list(data)
    games, wins = {}, {}
    for pos in positions:
        for h, v in data[pos].items():
            if not isinstance(v, list):
                raise ValueError("the position data has no win counts")
            games[h] = games.get(h, 0) + v[0]
            wins[h] = wins.get(h, 0) + v[1]
    total = sum(games.values()) or 1
    prior = sum(wins.values()) / total
    if position:
        pool = meta_pool(position, META_TOP if meta else None)
    else:
        pool = {h for h in games if games[h] / total >= MIN_SHARE_ALL}
    rows = []
    for h in pool:
        if games[h] == 0:
            continue
        shrunk = (wins[h] + SHRINK_K * prior) / (games[h] + SHRINK_K)
        rows.append((shrunk, h, 100 * wins[h] / games[h], 100 * games[h] / total, games[h]))
    rows.sort(reverse=True)
    return [(h, win, pick, g) for _, h, win, pick, g in rows]


def first_pick(position, meta, top):
    names, _ = load()
    try:
        rows = meta_table(position, meta)
    except (FileNotFoundError, ValueError):
        sys.exit("Download the position data first: python counter_score.py fetch-meta")
    label = f"position {position}" + (" (meta only)" if meta else "") if position else "all positions"
    bracket = get_info().get("meta", {}).get("bracket", load_config()["bracket"])
    print(f"First-pick meta, {label}, {bracket_label(bracket)}, last {current_weeks()} week(s)")
    print(f"{'Hero':<22}{'Win%':>7}{'Pick%':>8}{'Games':>9}")
    for h, win, pick, g in rows[:top]:
        print(f"{names[h]:<22}{win:>7.1f}{pick:>8.1f}{g:>9}")


# ------------------------------------------------------------ Meta probe --
def _tname(t):
    while t and t.get("name") is None and t.get("ofType"):
        t = t["ofType"]
    return t.get("name") if t else None


def _fields(type_name):
    q = (
        'query { __type(name: "%s") { fields { name args { name type { name kind '
        'ofType { name kind ofType { name kind ofType { name kind } } } } } '
        'type { name kind ofType { name kind ofType { name kind } } } } } }' % type_name
    )
    return gql(q)["__type"]["fields"]


def available_brackets():
    """Bracket groups Stratz offers for matchup data. Asks Stratz, and falls back
    to a fixed list if that fails (no token yet, no network, schema change)."""
    try:
        mu = next(f for f in _fields("HeroStatsQuery") if f["name"] == "matchUp")
        arg = next(a for a in mu["args"] if a["name"] == "bracketBasicIds")
        enum = _tname(arg["type"])
        vals = gql('query { __type(name: "%s") { enumValues { name } } }' % enum)["__type"]["enumValues"]
        names = [v["name"] for v in vals
                 if all(part in RANKS for part in v["name"].split("_"))]
        return names or FALLBACK_BRACKETS
    except Exception:
        return FALLBACK_BRACKETS


def meta():
    """Discovery: what does Stratz's winWeek accept and return?"""
    win = next(f for f in _fields("HeroStatsQuery") if f["name"] == "winWeek")
    print("winWeek returns:", _tname(win["type"]))
    print("winWeek arguments:")
    for a in win["args"]:
        print(f"  {a['name']}: {_tname(a['type'])}")
    for a in win["args"]:
        if "bracket" in a["name"].lower() or "position" in a["name"].lower() \
                or "lobby" in a["name"].lower() or "gameMode" in a["name"].lower():
            enum = _tname(a["type"])
            vals = gql(
                'query { __type(name: "%s") { enumValues { name } } }' % enum
            )["__type"]
            if vals and vals.get("enumValues"):
                names = ", ".join(v["name"] for v in vals["enumValues"])
                print(f"\n{a['name']} values ({enum}): {names}")
    print("\nFields on", _tname(win["type"]) + ":")
    for f in _fields(_tname(win["type"])):
        print(f"  {f['name']}: {_tname(f['type'])}")


# -------------------------------------------------------------------- CLI --
def show_config():
    cfg = load_config()
    token = get_token()
    shown = (token[:4] + "..." + token[-4:]) if len(token) > 10 else ("(set)" if token else "(none)")
    src = "environment" if os.environ.get("STRATZ_TOKEN") else "config.json"
    print(f"token  : {shown}  [{src}]")
    print(f"bracket: {cfg['bracket']} ({bracket_label(cfg['bracket'])})")
    print(f"weeks  : {current_weeks()}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("config")
    c.add_argument("--token")
    c.add_argument("--bracket")
    c.add_argument("--weeks", type=int)
    sub.add_parser("fetch")
    sub.add_parser("meta")
    sub.add_parser("fetch-meta")
    f = sub.add_parser("first-pick")
    f.add_argument("--position", type=int, choices=range(1, 6))
    f.add_argument("--meta", action="store_true")
    f.add_argument("--top", type=int, default=15)
    s = sub.add_parser("suggest")
    s.add_argument("--enemy", default="")
    s.add_argument("--ally", default="")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--position", type=int, choices=range(1, 6),
                   help="only heroes commonly played in this position (1-5)")
    s.add_argument("--meta", action="store_true",
                   help="with --position: only the %d most played heroes there" % META_TOP)
    args = p.parse_args()

    try:
        if args.cmd == "config":
            changes = {}
            if args.token is not None:
                changes["token"] = args.token.strip()
            if args.bracket:
                bracket_ranks(args.bracket)
                changes["bracket"] = args.bracket.upper()
            if args.weeks:
                changes["weeks"] = max(1, min(MAX_WEEKS, args.weeks))
            if changes:
                save_config(**changes)
            show_config()
        elif args.cmd == "fetch":
            fetch()
        elif args.cmd == "fetch-meta":
            fetch_meta()
        elif args.cmd == "first-pick":
            first_pick(args.position, args.meta, args.top)
        elif args.cmd == "meta":
            meta()
        elif args.cmd == "suggest":
            names, _ = load()
            if args.meta and not args.position:
                sys.exit("--meta needs --position")
            pool = None
            if args.position:
                if not (CACHE / "meta.json").exists():
                    sys.exit("Run `fetch-meta` first.")
                pool = meta_pool(args.position, META_TOP if args.meta else None)
            suggest(resolve(args.ally, names), resolve(args.enemy, names), args.top, pool)
        else:
            p.print_help()
    except StratzError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()