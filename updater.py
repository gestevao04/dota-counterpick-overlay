"""
Downloads and data status for the overlay's Settings window.

Three datasets make the overlay work:
  portraits  hero portraits + names (OpenDota list, Valve's CDN)   -> portraits/
  matchups   hero-vs-hero and hero-with-hero win rates (Stratz)    -> cache/
  meta       weekly per-position games and wins (Stratz)           -> cache/

`run` never raises: it returns a result per task so a UI can show what failed.
"""

import requests

import counter_score as cs
import draft_reader as dr

TASKS = ("portraits", "matchups", "meta")   # also the order they run in
LABELS = {
    "portraits": "Hero portraits",
    "matchups": "Matchups and synergies",
    "meta": "Position data (meta, first pick)",
}


def run(tasks, progress=print):
    """Run the selected downloads in a fixed order.

    Returns [(task, ok, message)]. A failed task does not stop the others,
    except that Stratz tasks are skipped after a Stratz error that would hit
    them all (bad or missing token).
    """
    results = []
    stratz_blocked = None
    for task in TASKS:
        if task not in tasks:
            continue
        if task != "portraits" and stratz_blocked:
            results.append((task, False, stratz_blocked))
            continue
        try:
            if task == "portraits":
                dr.fetch(progress)
                cs.set_info("portraits")
            elif task == "matchups":
                cs.fetch(progress)
            else:
                cs.fetch_meta(progress)
            results.append((task, True, "ok"))
        except cs.StratzError as exc:
            results.append((task, False, str(exc)))
            if "token" in str(exc).lower():
                stratz_blocked = str(exc)
        except requests.RequestException as exc:
            results.append((task, False, f"Network error: {exc}"))
        except Exception as exc:  # keep the UI alive whatever happens
            results.append((task, False, f"Unexpected error: {exc}"))
    return results


def is_ready():
    """True when portraits and matchups exist, i.e. drafts can be read and scored."""
    return dr.HEROES_JSON.exists() and (cs.CACHE / "matchups.json").exists()


def status():
    """{task: (state, text)} with state 'missing', 'ok' or 'stale'."""
    info, cfg = cs.get_info(), cs.load_config()
    out = {}

    when = info.get("portraits", {}).get("fetched", "")
    out["portraits"] = (("ok", f"Downloaded {when}".strip())
                        if dr.HEROES_JSON.exists() else ("missing", "Not downloaded yet"))

    for task, fname in (("matchups", "matchups.json"), ("meta", "meta.json")):
        if not (cs.CACHE / fname).exists():
            out[task] = ("missing", "Not downloaded yet")
            continue
        got = info.get(task, {})
        bracket = got.get("bracket")
        text = f"{cs.bracket_label(bracket)}, {got.get('fetched', '')}".strip(", ") if bracket else "Downloaded"
        if task == "meta":
            weeks = cs.meta_weeks_available()
            if weeks:
                text += f" ({weeks} weeks available, using {cs.current_weeks()})"
            else:
                text += " (old format: update once so the weeks setting works)"
        if bracket and bracket != cfg["bracket"]:
            out[task] = ("stale", f"{text} - bracket changed, update to match")
        else:
            out[task] = ("ok", text)
    return out
