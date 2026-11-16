# nexusfrc

Turns recorded FRC matches (2026 REBUILT) into a simplified, time-accurate match
timeline. Later stages add a 2D replay, penalty checks, and a coach that analyzes a
robot's performance.

## Goal

The end goal is a **coach that analyzes a robot's performance** from a match video.
The project is built in stages, all sharing one data format, the Match Timeline
(`timeline.json`, defined in `frcsim/schema.py`):

1. **Video -> Match Timeline (working now).** Reads the clock and both scores from the
   broadcast scorebug, counts fuel (balls) entering each hub, works out each hub's
   active/inactive state over time (Table 6-3), and combines everything into
   `timeline.json`.
2. **2D replay (planned).** Draws the match from the timeline.
3. **Penalty checks (planned).** Rule checks on the timeline (`frcsim/rules/`), using
   distances between robots from `geometry.py`.
4. **Coach (planned).** Judges how well a robot did from its timeline.

Current limits:

- The scorebug is exact only for the active hub; the video counter sees both hubs but
  misses balls in dense volleys (about 20% of the scorebug points on the test match). The two sources are used together.
- Pixel zones are measured for one camera (2026 Einstein webcast).
- Individual robots are not tracked yet. Per-robot coaching will need robot positions
  and per-robot fuel from the video, which is the largest piece still to build.

## Setup

Requires Python 3.11 or newer. From the repo root (PowerShell):

```powershell
python -m venv .venv            # optional
.venv\Scripts\Activate.ps1      # optional
pip install -e ".[dev]"
```

## Web UI (recommended)

```powershell
python -m frcsim.web
```

Open http://127.0.0.1:8000. Paste a YouTube link of a full match and press **Analyze**
(optionally add team numbers). It downloads and analyzes the match, showing progress; this
takes about one to two minutes plus the download. Matches you already analyzed are in the
**Already analyzed** list and open instantly, so a match is only analyzed once.

The page then shows a timeline of the match: blue bars up, red bars down, one per second.
**Drag across the timeline** to choose two times (or type them, or click a quick range such
as SHIFT 2) and it shows how many balls each alliance scored in between. Hover for the
numbers of any second; the table view lists every selected second.

### What the ball number means

Both sources are shown, and the big number is the best estimate of the two:

| Source | Good at | Bad at |
|---|---|---|
| Scorebug points | Exact while a hub is **active** (1 point per ball) | Hubs that are inactive; END GAME, where tower points are mixed in; foul points |
| Video count | Sees every hub, active or not | Misses balls (about 20% of the scorebug's points on the test match) |

- A second where the hub is active (and not END GAME) uses the **scorebug points**. The
  scorebug shows a ball about a second after it entered the hub; this lag is measured per
  match and corrected, so points land in the right period.
- Any other second (inactive hub, END GAME; hatched on the chart) uses the **video count
  multiplied by a calibration factor**: the ratio scorebug / video measured on the trusted
  seconds of the same match (about 1.3-1.5).
- So ranges inside an active period are exact; ranges with hatched seconds are estimates.
  On the test match the whole-match estimate was 414 / 770 against a final scoreboard of
  403 / 690. The red excess is mostly END GAME, where the scorebug contains tower points
  that cannot be separated from balls.

The logic is in `frcsim/query.py` and has tests; the server is `frcsim/web.py`.

## Analyze a match from the terminal

```powershell
python -m frcsim
```

It asks for the YouTube link and (optionally) the team numbers of each alliance,
downloads the match as 1080p H.264 (video only, no ffmpeg needed) to
`samples/<video id>/video.mp4`, then runs the pipeline below and writes the results in
the same folder. You can also pass everything on the command line:

```powershell
python -m frcsim "https://www.youtube.com/watch?v=..." --blue 868 2046 2910 --red 4065 4414 1323
```

Needs Node.js (or deno) installed: YouTube requires a JavaScript runtime to list the
1080p formats. The link must point to the match itself (the whole match, FIRST
Championship webcast layout), not a full-day livestream.

## Run the video pipeline on a local file

PowerShell (the backtick continues the line; use `^` in cmd.exe, or one line):

```powershell
python -m frcsim.pipeline "path	o\match.mp4" --out samples/my_match `
    --blue 868 2046 2910 --red 4065 4414 1323 --match-id "Einstein Final Tiebreaker"
```

| Argument | |
|---|---|
| `video` | Path to the match video (required) |
| `--out` | Output folder (required) |
| `--blue`, `--red` | Team numbers of each alliance (optional) |
| `--match-id` | Label for the match (optional) |
| `--workers` | CPU processes (default: half the cores, max 8). `1` = single process |

The scorebug and the ball counter are split into time chunks processed in parallel
(a 3.5-minute video takes about 1 minute on 14 cores, versus 4 minutes on one).
Scorebug results are identical either way. Ball counts can differ by about 1%, because
the counter's background model depends on where in the video it starts; use
`--workers 1` when you need exactly reproducible counts.

Run the tests with `pytest`.

Use a 1080p video of the FIRST Championship webcast containing the whole match (AUTO
and TELEOP) with the scorebug visible. The video must be encoded in a codec OpenCV can
decode (H.264 is safe). The pipeline writes to the `--out` folder:

| File | What it is |
|---|---|
| `scorebug_raw.jsonl` | Clock and scores read from the broadcast scorebug every 0.5 s |
| `scorebug_clean.json` | Same, cleaned, with match time and period |
| `hub_entries.json` | Every ball the video counter saw entering each hub (video time, count) |
| `fuel_per_second.csv` | Per second: period, hub active?, balls counted on video, points scored on scorebug |
| `timeline.json` | The canonical Match Timeline (`frcsim/schema.py`) used by the rest of the project |
| `report.txt` | Video count vs scorebug, per period |

## How to read the fuel numbers

- `*_scored` (scorebug) is exact for the **active** hub when there are no tower or foul points.
  It cannot see fuel shot into an inactive hub.
- `*_counted` (video) sees every hub, but currently undercounts dense volleys. On the test
  match it finds about 80% of the scorebug's points on active hubs (it was 69% before
  `MIN_DESCENT` was set to 0), with large differences between periods (59%-106%). Use it for timing and for inactive-hub shots, not as an exact total.

## Troubleshooting

- **`Could not decode any frame` (older versions: `IndexError: list index out of range`
  in `find_match_window`).** OpenCV opened the video but could not read frames, so
  `scorebug_raw.jsonl` is empty. The codec is usually unsupported, most often AV1 from
  YouTube downloads. Check with `ffprobe -v error -select_streams v:0 -show_entries stream=codec_name "match.mp4"`
  and re-encode to H.264:
  `ffmpeg -i match.mp4 -c:v libx264 -crf 18 -an match_h264.mp4`
- **`The scorebug clock was never readable`.** The video is not the Championship webcast
  layout, or the scorebug is hidden. The crop boxes are `BOXES` in
  `frcsim/ingest/video/overlay.py`.
- **`No TELEOP found`.** The video is cut and does not contain the clock restarting at
  2:20 for TELEOP.

## Layout

```
frcsim/
  schema.py                 Match Timeline format
  geometry.py               distances between robots
  web.py, static/index.html Web UI: link -> analysis -> pick a time range (python -m frcsim.web)
  query.py                  balls between two times, from a timeline (scorebug + video + calibration)
  youtube.py                YouTube link -> download -> pipeline (python -m frcsim)
  pipeline.py               video -> timeline (entry point)
  ingest/video/
    overlay.py              scorebug OCR
    scorebug_clean.py       cleaning + match time
    hub_counter.py          ball tracking into each hub
    fuel_per_second.py      per-second table + hub active state (manual Table 6-3)
tests/
samples/                    pipeline outputs (videos are not committed)
```

Pixel zones in `overlay.py` and `hub_counter.py` are measured for the 2026 Einstein
camera and must be re-measured for other events.
