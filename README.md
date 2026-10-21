# Dota 2 Draft Overlay

A free, open-source overlay that helps you draft in Dota 2. It reads the heroes
that have been picked from your screen and suggests counters and synergies
using current win-rate data for the Legend/Ancient bracket. If you are first
pick and nothing is on screen yet, it shows the current meta win rates for
your position instead.

> **Not affiliated with or endorsed by Valve.** Dota 2 and its hero names and
> artwork belong to Valve Corporation. See [Legal](#legal-and-credits).

## What it does

- **Reads the draft from your screen.** It matches the ten pick portraits at the
  top of the draft screen against Dota's hero portraits.
- **Counter and synergy suggestions.** For every hero it computes win-rate
  advantage against the enemy picks plus synergy with your allies, with
  small-sample shrinkage so rare matchups don't look better than they are.
- **Position and "Meta" filters.** Only suggest heroes that are actually played
  in your position, or only the 15 most played there.
- **First-pick meta table.** With no picks yet, shows win% and pick% per hero
  for your position.
- **Click-to-configure overlay.** Switch team, position, Meta and your own slot
  from the overlay window while you draft.

## Fair play

The overlay only looks at pixels on your own screen. It does **not** read game
memory, inject into the game process, or automate any inputs. It does not look
up or show anything about other players (no profiles, ranks or hero pools), and
it uses only public aggregate hero statistics. Valve's rules about third-party
tools can change, so use it at your own risk.

## Install

Requires Python 3.9+ (on Windows use the python.org installer, which includes
tkinter) and Dota 2 in **borderless windowed** mode.

```
pip install -r requirements.txt
python draft_overlay.py
```

## First run

The Settings window opens by itself the first time. No terminal commands are
needed:

1. **Get a free Stratz API token.** Click the link in the window (it opens
   <https://stratz.com/api>), sign in with Steam, and paste the token into the
   token field.
2. **Pick your bracket** (see [Settings](#settings)).
3. Click **Update everything**. It downloads the hero portraits, the matchup
   data and the position data (about a minute). The log shows progress, and the
   status next to each dataset turns green when it is done.
4. Close the window. Open Dota and start drafting.

After each Dota patch, open Settings and click **Update everything** again.

## Using the overlay

| Control | What it does |
|---|---|
| Team | Which side you are on. Radiant is on the left of the top bar, Dire on the right. |
| Pos | Only suggest heroes played in that position (All = no filter). |
| Meta | With a position: only the most played heroes there. |
| Me | Your own slot, so you are not counted as your own teammate. |
| Settings | Token, bracket, weeks of meta data and downloads. |

Drag the window to move it, right-click to quit. The title shows how many of the
ten slots were read (`read 10/10`), and the line at the bottom shows which
bracket's data you are looking at. Your choices (team, position, Meta, Me) are
remembered between runs.

## Settings

| Setting | What it does |
|---|---|
| Stratz API token | Needed for the downloads. Saved in `config.json` next to the program. If the `STRATZ_TOKEN` environment variable is set, it takes priority. |
| Bracket | Which rank group the matchup and position data is downloaded for (for example Legend / Ancient). The list is asked from Stratz once a token is entered. Changing it needs an update; the overlay warns you if the data does not match. Only Legend / Ancient has been tested by the author. |
| Weeks of meta | How many recent weeks count for the position filters and the first-pick table. The position data is stored week by week, so changing this needs **no** download. |
| Update buttons | Download one dataset or all three. A failed download shows the reason in the log (bad token, no network, rate limit) and does not break the others. |

Everything the program downloads or saves lives next to the program:
`portraits/`, `cache/` and `config.json`. Delete them to reset.

## Command line (optional)

Everything the Settings window does is also available from a terminal:

```
python counter_score.py config --token YOUR_TOKEN --bracket LEGEND_ANCIENT --weeks 2
python draft_reader.py fetch          # portraits
python counter_score.py fetch         # matchups
python counter_score.py fetch-meta    # position data
python draft_overlay.py --team dire --position 4 --meta --me 3
```

Run any command with `--help` for the full list of options.

## Slot boxes (`slots.json`)

`slots.json` holds the ten pick boxes for a **2560x1440** capture. They are
scaled automatically to other 16:9 resolutions, assuming Dota's default UI
scale. The boxes are 156x92 px, just below the coloured player bar, and the Dire
boxes start 12 px left of the Dire bar because those portraits lean the other
way. If your layout differs (different UI scale or aspect ratio), make a new
file in the same format:

```json
{"ref_size": [2560, 1440], "slots": {"radiant_1": [281, 6, 156, 92], "...": "..."}}
```

`python draft_reader.py calibrate screenshot.png` helps you find box corners.
Automatic detection of the boxes would be a great contribution.

## Troubleshooting

- **Overlay disappears when you click Dota.** The overlay re-asserts "always on
  top" several times a second, but it cannot draw over true exclusive
  fullscreen. Set Dota's display mode to borderless windowed.
- **Nothing is read / black capture.** Same cause, or wrong monitor
  (`--monitor N`).
- **A slot is misread or missing.** Start the overlay with `--dev` to get a Snap
  button. Click it while it happens and look at `snapshot.txt` (best guess,
  runner-up and margin per slot). If a hero looks different from its default
  portrait (cosmetic sets), teach the reader:
  `python draft_assistant.py learn snapshot.png radiant_4 "Tidehunter"`.
- **An update fails.** The Settings log says why. "Rejected the token" means the
  token is wrong or expired; "Network error" means no connection to Stratz;
  repeated failures right after each other can be Stratz's rate limit, so wait a
  few minutes.
- **The bracket list only shows four options.** That is the built-in list, used
  until a token is entered or if Stratz cannot be reached.

## How the scoring works

All numbers are percentage points of win rate. A hero's matchup against an enemy
is its win rate against that enemy minus its own baseline. Synergy with an ally
is the pair's win rate minus the average of the two baselines. Each delta is
shrunk toward zero by `n / (n + 300)`, so a pairing needs a few hundred games to
count fully. The total is the sum over your allies and the enemies. The first-pick
table ranks heroes by win rate pulled toward the average with 200 games of
prior. Constants such as `K`, `MIN_SHARE`, `META_TOP` and `SHRINK_K` sit at the
top of `counter_score.py`, and the screen-reading thresholds (`MIN_SCORE`,
`MIN_MARGIN`, `HUB_WEIGHT`) at the top of `draft_assistant.py`.

## Legal and credits

- Not affiliated with, authorized or endorsed by Valve Corporation. Dota 2,
  hero names and hero artwork are Valve's property.
- Hero portraits are **not** included in this repository. `draft_reader.py fetch`
  downloads them to your own machine at runtime. Please keep it that way if you
  fork the project, and do not commit the `portraits/` folder.
- Win-rate data comes from [STRATZ](https://stratz.com) through their API. You
  need your own free token and must follow STRATZ's API terms. Hero list and
  portrait paths come from the [OpenDota](https://www.opendota.com) API.
- There is no telemetry. The only network calls are to Stratz, OpenDota and
  Valve's CDN. Your token is stored only in `config.json` on your machine; it is
  listed in `.gitignore`, so never commit that file.

## Support the project

This project is, and will stay, free and open source. If it helps your drafts
and you would like to chip in, donations are very welcome and entirely
voluntary. They don't unlock anything.

- [GitHub Sponsors](https://github.com/sponsors/gestevao04)
- [Ko-fi](https://ko-fi.com/gestevao04)
- Pix (BR): `5c92a994-5074-4932-a2d5-e49d00cb5a47`

## Contributing

Issues and pull requests are welcome. Good first contributions: automatic slot
detection, tests, other aspect ratios and UI scales, other languages of the
Dota client, and macOS/Linux window handling.

## License

[MIT](LICENSE)
