# nexusfrc

A local app that analyzes FRC matches (2026 REBUILT) from match video and says how each
robot did: where it went, when it shot, roughly how many balls it scored, when it touched
other robots, what its strategy seems to be, and what it could do in a coming match.

## Run it

Requires Python 3.11+ and Node.js (yt-dlp needs a JavaScript runtime for YouTube).

```powershell
pip install -e ".[dev]"
python -m frcsim.web        # or just: nexusfrc     -> opens http://127.0.0.1:8000
```

The robot detector is a 114 MB file that is not in the repo: put it at `models/robots.onnx`
(the Roboflow model `robot-and-hoop-tracking/2`, exported as ONNX; class names are in
`models/robots.classes.txt`). Without it everything still works except robot tracking.

## What the app does

| Tab | What you get |
|---|---|
| **Analyze** | Paste a YouTube link, or load an event from The Blue Alliance and click a match. Analysis takes about 3-5 minutes and is stored, so each match is analyzed once. |
| **Match** | 2D replay (robots, hub on/off, shots, contacts, events list), a robot table (role, balls, shots, defence, contacts, distance, zones, notes), the balls-per-second chart with any time range, and the official TBA breakdown when known. "Check on video" draws the tracked robots back onto the real frame. |
| **Teams** | Every team seen, averaged over all analyzed matches; a report per team (strategy, does well, could improve, caveats) and "plan a match": advice given partners and opponents. |
| **Settings** | TBA key (stored in your user folder), model status, and a drag-and-drop field calibration editor. |

## How it works

```
video ──> scorebug OCR (clock, scores, team numbers) ──┐
      ──> colour ball counter (balls into each hub) ───┼──> timeline.json (per-second balls)
      ──> robot detector, 3 fps (RF-DETR via ONNX) ────┴──> robot_detections.json
                                                              │
      on page load (fast, no re-analysis):                    v
      calibration (layout JSON) -> field positions -> 6 tracked robots -> shots, contacts,
      roles, balls per robot -> match notes -> team profiles -> coach
```

* **Balls per alliance** (`query.py`): scorebug points while a hub is active (exact), the
  scaled video count otherwise (estimate, hatched on the chart).
* **Robot positions** (`field.py`, `robots.py`): the 2026 Championship webcast top panel is
  a fixed camera, so one homography (fitted to calibration points in
  `frcsim/layouts/einstein2026.json`) maps pixels to metres, about +-0.5 m. Bumper colour
  gives the alliance; robots are kept in 3 slots per alliance by nearest position.
* **Identity**: which slot is which team is a guess (scorebug order matched to starting
  position) until you type the team in the robot table and save.
* **Shots and balls per robot**: a robot slow inside its alliance zone is "shooting"; each
  second's alliance balls are shared between the robots shooting 1 s before. No data
  source counts balls per robot, so this is an estimate.
* **Contacts**: two robot centres closer than 1.05 m for 0.5 s.
* **Coach** (`coach.py`): compares each team with the average of all teams seen; rules
  and thresholds are listed at the top of the file.

Everything is labelled as an estimate in the UI where it is one.

## Changing things

* Every tunable number (frame rate, speeds, distances, role weights, field size) is in
  `frcsim/settings.py`. Things computed on page load change on the next load.
* A different webcast layout: copy `frcsim/layouts/einstein2026.json`, adjust the field
  region, team boxes and calibration points (or use the Settings tab), and the scorebug
  boxes in `frcsim/ingest/video/overlay.py`.
* Data folder: `$NEXUSFRC_DATA` (default `samples/`); model folder: `$NEXUSFRC_MODELS`
  (default `models/`); user settings: `~/.nexusfrc/config.json`.

## Layout

```
frcsim/
  web.py            FastAPI server + API; serves static/
  pipeline.py       video -> stored files (the slow, once-per-match part)
  settings.py       paths, keys, every tunable number
  field.py          field geometry, layouts, pixel <-> metre mapping
  robots.py         tracking, shots, contacts, per-robot stats (fast, on load)
  coach.py          team profiles, strengths/weaknesses, recommendations
  query.py          balls per second / per time range
  schema.py         Timeline format
  youtube.py        download (+ the `python -m frcsim` command line)
  ingest/tba.py     The Blue Alliance API client (optional)
  ingest/video/     overlay.py (scorebug OCR), scorebug_clean.py, hub_counter.py,
                    fuel_per_second.py, robots.py (detector)
  layouts/          webcast layouts with calibration
  static/           index.html, app.js, chart.js, replay.js, app.css
tools/              optional: ball-detector training kit (extract_crops.py, train_yolo.py)
tests/              pytest
```

## Command line

```powershell
python -m frcsim "https://www.youtube.com/watch?v=..."      # download + analyze
python -m frcsim.pipeline VIDEO.mp4 --out samples/<id>      # analyze a local file
pytest                                                       # tests
```

## Making it a downloadable app (later)

The app is already local-first: a Python server plus a static page, data in one folder,
keys in the user folder, the model as one file. To ship it:

1. Bundle with PyInstaller (`pyinstaller --onedir -n nexusfrc frcsim/web.py` with
   `frcsim/static` and `frcsim/layouts` as data files), ship `robots.onnx` next to it, and
   set `NEXUSFRC_DATA` to a user folder (e.g. `%APPDATA%/nexusfrc`).
2. Optionally wrap it in a desktop window (Tauri or pywebview) pointing at the local server.
3. For sharing between up to ~100 users at no cost, see "Infrastructure" in NOTES.md.
