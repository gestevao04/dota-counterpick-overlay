# Dota 2 Draft Overlay

A free, open-source overlay that helps you draft in Dota 2. It reads the heroes
that have been picked from your screen and suggests counters and synergies
using current win-rate data for the Legend/Ancient bracket. If you are first
pick and nothing is on screen yet, it shows the current meta win rates for
your position instead.

**[Download for Windows](../../releases)**: open the newest release and get the file ending in `-windows.zip` (details [below](#option-a-windows-download-no-python-needed)).

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

### Option A: Windows download (no Python needed)

1. Open the [Releases page](../../releases). On the repository's main page it is
   the **Releases** link on the right-hand side. Click the newest version at the
   top.
2. Scroll down to **Assets** (click *Show all assets* if the list is collapsed)
   and download the file whose name ends in **`-windows.zip`**. Ignore the
   *Source code* files: those are for developers, and the program will not run
   from them. The `.sha256` file is only for verifying the download (see below).
3. Right-click the zip, choose **Extract All**, and open the folder it creates.
   Extract it somewhere you can write files (not `Program Files`). Everything the
   program saves stays in that folder.
4. Double-click `DotaDraftOverlay.exe` **inside that folder**. It needs the
   `_internal` folder next to it, so do not move or copy the `.exe` on its own.
   For a desktop shortcut, right-click the `.exe` and choose *Send to*, then
   *Desktop (create shortcut)*.

**Windows may warn you.** The program is not code-signed yet, so Windows
SmartScreen can say "Windows protected your PC": click *More info*, then *Run
anyway*. Some antivirus programs also flag unsigned programs that capture the
screen and stay on top of other windows. You can check that your download is the
one the project built: each release has a `.sha256` file, and
`Get-FileHash DotaDraftOverlay-vX.Y.Z-windows.zip` in PowerShell should print the
same value. The release is built from this repository by a public workflow (see
[Building](#building-the-windows-program)), and if you would rather not run a
download at all, Option B runs the same code from source.

### Option B: run from source

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

Everything the program downloads or saves lives in one folder: `portraits/`,
`cache/` and `config.json`. That is the folder of the program itself, so the
whole thing is portable. If that folder is not writable it uses
`%APPDATA%\DotaDraftOverlay` instead, and the `DOTA_OVERLAY_HOME` environment
variable can point it anywhere. Delete those items to reset. If the program ever
crashes, the details are saved to `error.log` in the same folder; please attach
it to your bug report.

To use a different `--dev`, `--team` or other option with the Windows download,
make a shortcut to `DotaDraftOverlay.exe` and add the option at the end of the
shortcut's Target.

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

- **"Failed to load Python DLL ... python312.dll" when starting the Windows
  program.** The `.exe` was separated from its `_internal` folder (usually by
  moving or copying just the `.exe`, or running it from inside the zip). Extract
  the whole zip and run the `.exe` from within the extracted folder. If
  `_internal` is there and the error remains, your antivirus may have
  quarantined `python312.dll`; restore it and add the folder as an exception.
- **Overlay disappears when you click Dota.** The overlay re-asserts "always on
  top" several times a second, but it cannot draw over true exclusive
  fullscreen. Set Dota's display mode to borderless windowed.
- **Nothing is read / black capture.** Same cause, or wrong monitor
  (`--monitor N`).
- **A slot is misread or missing.** Start the overlay with `--dev` to get a Snap
  button. Click it while it happens; it saves `preview.jpg`, `snapshot.png` and
  `snapshot.txt` in the program's folder. Look at `snapshot.txt` (best guess,
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

- [GitHub Sponsors](https://github.com/sponsors/YOUR-USERNAME)
- [Ko-fi](https://ko-fi.com/YOUR-NAME)
- Pix: `YOUR-PIX-KEY`

## Building the Windows program

The release workflow (`.github/workflows/release.yml`) builds the Windows
package with [PyInstaller](https://pyinstaller.org), runs the tests, checks that
the built program starts and contains every library it needs (`--selftest`),
and attaches a zip and its checksum to the GitHub release. To build locally:

```
pip install -r requirements.txt pyinstaller
python -m PyInstaller dota-draft-overlay.spec --noconfirm
```

The result is in `dist/DotaDraftOverlay/`. Maintainers: see
[RELEASING.md](RELEASING.md).

## Running the tests

```
python -m unittest discover -s tests -t . -v
```

The tests use a throw-away data folder and a fake Stratz and tkinter, so they
need no token, no network and no display, and they never touch your real
settings.

## Reporting problems

Please open an [issue](../../issues/new/choose) and pick the form that fits:
**Bug report** (crashes, the window, downloads), **Hero misread or not detected**
(the overlay shows the wrong hero or misses one), or **Feature request**. The
forms ask for your program version, screen resolution and Dota's display mode,
which are usually what is needed to reproduce a problem. Never include your
Stratz token or `config.json`, and blur other players' names in screenshots.

## Contributing

Issues and pull requests are welcome. Good first contributions: automatic slot
detection, tests, other aspect ratios and UI scales, other languages of the
Dota client, and macOS/Linux window handling.

## License

[MIT](LICENSE)