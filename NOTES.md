# Notes: where the project stands and what to do next

## Start here (state after session 4, 2026-11-16)

The app is built as described in README.md: Analyze / Match (2D replay, robots, balls) /
Teams (profiles + coach) / Settings (keys + calibration). Sessions 1-3 below are history;
where they disagree with this section, this section wins.

What was done in session 4:
- Removed: Roboflow Docker workflow (`run_roboflow.ps1`, `roboflow_workflow.py`), the model
  ball counter (`hub_counter_model.py` + UI checkbox), `tools/cache_roboflow_model.py`,
  `geometry.py` and the empty `rules/` package, the incomplete `samples/*_model` folders,
  the `inference` dependency. The robot model now runs straight through onnxruntime
  (`models/robots.onnx`, copied from the Roboflow cache; identical detections, 0.22 s/frame).
- Kept but parked: `tools/extract_crops.py`, `tools/train_yolo.py` and `dataset/` (ball
  detector training kit, now git-ignored). Not on the app's path.
- New: `settings.py` (all tunables, paths, keys), `field.py` + `layouts/einstein2026.json`
  (homography calibration, editable in the UI), `ingest/video/robots.py` (detector),
  `robots.py` (tracking, shots, contacts, per-robot stats, computed on page load),
  `coach.py` (profiles, strengths/weaknesses, recommendations), `ingest/tba.py` (optional
  TBA client with disk cache), team-number OCR from the scorebug (`overlay.read_teams`),
  and the new UI (`static/app.js`, `chart.js`, `replay.js`, `app.css`).
- Pipeline runs the ball counter and the robot detector at the same time.
- Tests: 17 pass (`pytest`).

Measured on the two Einstein matches:
- The webcast's top panel is a fixed camera covering the whole field, so one homography
  works for the whole match. Calibration residual about 0.4 m (6 points, eyeballed).
- Robots detected per frame: about 4 of 6 (others hidden behind field staff); each robot is
  seen about 60-70% of the time; the rest of the time it keeps its last position (drawn hollow).
- Bumper colour gives the alliance for about 96% of boxes.
- Team numbers read from the scorebug correctly in both matches.
- With the hidden-robot rule and the nearest-to-hub fallback, all alliance balls are
  attributed to a robot (before: 40-60% unattributed). Per-robot balls are not validated.
- Full analysis time on this PC (j8wz5vw5XfE, 172 s match): 237 s for the whole pipeline
  (scorebug, team OCR, ball counter and robot detector in parallel), plus 30-60 s download.
  So about 4-5 minutes per new match, inside the 5-minute target with little slack.

Known weak points (in order of impact):
1. **Identity is a guess** (scorebug order matched to start position, far side first). It
   swapped 1323/4414 between two code versions. Fix: label robots in the UI (Save team
   labels); a later version could read bumper numbers or use TBA starting positions.
2. **Per-robot balls are unvalidated.** Needs a hand count of one robot's shots on 2-3 clips.
3. **Shooting rule** (slow inside own zone + 0.5 m) is a guess tuned on one match.
4. **Contacts** use centre distance only; positions are +-0.5 m, so some are missed or false.
5. **Only the 2026 Championship webcast layout** has a calibration. Other events need a new
   layout JSON (copy + adjust in the Settings tab) and scorebug boxes in `overlay.py`.
6. TBA integration is untested against real 2026 data (no key yet); `score_breakdown`
   fields are shown raw.

Next steps:
1. Add a TBA key (Settings tab) and load an event; check the breakdown fields; if per-period
   fuel exists, use it to correct `query.py` period totals.
2. Label the 6 robots in both sample matches, then hand-count shots of one robot on a clip.
3. Analyze 3+ more matches of the same teams so profiles mean something.
4. Package: PyInstaller one-folder build (see README), data in %APPDATA%.

## History: sessions 1-3 (written at the end of each session)


## How to run

```powershell
cd C:\source\eliottrge\nexusfrc
pip install -e ".[dev]"        # once
python -m frcsim.web           # then open http://127.0.0.1:8000
```

Paste a YouTube link of a full match, press Analyze, then drag across the timeline to
pick two times and see the balls each alliance scored in between. Terminal version:
`python -m frcsim`. Tests: `pytest` (11 pass).

## What was done this session

- Found why `IndexError: list index out of range` happened: OpenCV could not decode the
  video (usually AV1 from YouTube), so no scorebug frames were read. The pipeline now stops
  with a clear message instead (`frcsim/pipeline.py`).
- `python -m frcsim` asks for a YouTube link and team numbers, downloads video-only H.264
  (no ffmpeg needed) and analyzes it (`frcsim/youtube.py`). Needs Node.js or deno, and
  `yt-dlp[default]`.
- Sped up the analysis about 4x (match of 3.5 min: ~4 min -> ~65 s, 1-2 min when the PC is
  busy): scorebug reading seeks once instead of per sample, and both the scorebug and the
  ball counter run in parallel time chunks (`--workers`, default half the cores, max 8).
  Scorebug results are identical; ball counts differ ~1% between chunked and single runs.
- Web UI (`frcsim/web.py`, `frcsim/static/index.html`): link -> progress -> timeline chart
  (blue up, red down, hatched = estimated from video) -> drag to choose a range -> counts.
  Chart colors were validated for color-blind safety in light and dark mode.
- `frcsim/query.py`: answers "balls between t=a and t=b" from a timeline (see below).
- Counter tweak: `MIN_DESCENT = 0` in `hub_counter.py` raised the video count from 69% to
  79% of the scorebug points on active hubs.
- README documents all of this. `samples/j8wz5vw5XfE/` was re-analyzed with the improved
  counter (the old output was overwritten).

## How the ball number is computed (`frcsim/query.py`)

- Active hub, before END GAME: the scorebug points (1 point = 1 ball, exact).
- Otherwise (inactive hub, END GAME; hatched on the chart): the video count times a
  calibration factor (scorebug / video on the trusted seconds, about 1.3-1.5).
- The scorebug trails the video by about 1 s; this is measured per match and corrected.

## How accurate it is (one match: Einstein Final Tiebreaker, j8wz5vw5XfE)

- Video count vs scorebug points on active hubs before END GAME: 598 vs 756 = 79%.
  Per period it ranges from 59% (blue AUTO) to over 100%. SHIFT 1 blue is an outlier
  (29 counted vs 11 scored), probably a timing mismatch.
- Whole match estimate: blue 414 / red 770, final scoreboard 403 / 690. The excess is mostly
  END GAME, where the scorebug includes tower points that cannot be separated from balls.
- Tuned on this one match only, so the 79% may not hold on others.

## Known problems

- The video counter cannot be made miss-free by tuning. I tried removing the 1,500 px blob
  cap (no change) and a faster-adapting background (worse). Most lost balls are fast
  balls against a crowd in yellow shirts; many tracks never end in the hub mouth zone.
  Of 116 tracks over 12-20 s on blue, 46 were counted, 42 never reached the mouth.
- Over-counting is untested: the scorebug comparison only exposes misses.
- Inactive hubs have no ground truth, so their estimate has an unknown error.
- SHIFT 1: red's hub should be inactive, yet the scorebug rises by about 35 points. Likely
  a short scoring grace period after a hub deactivates, not modelled. Check the manual.
- Pixel zones are for the 2026 Einstein webcast only (`overlay.py`, `hub_counter.py`).
- The web analysis took 110 s once vs 65 s on the command line; not investigated.

## Next steps (in order)

1. **Get a real error rate.** Pick a 20-30 s clip, count the balls by hand, compare with the
   counter. This also shows whether it over-counts.
2. **Trained detector (the main improvement).** Fine-tune a pretrained YOLO nano model
   (ultralytics, built on PyTorch) to find individual balls:
   - Write a script that extracts a few hundred hub crops from match videos, favouring
     moments where the counter and the scorebug disagree most (dense volleys).
   - Pre-label them with the existing counter's blobs; the user fixes the boxes in a
     labeling tool (a few hours).
   - Fine-tune on CPU (minutes to under an hour), export to ONNX so the pipeline runs it
     with onnxruntime (already a dependency); PyTorch is then only needed for training.
   - Run it only on frames where the old counter sees something, so run time barely grows.
     Estimate: 10-20 ms per crop on CPU, about 6-12 s extra spread over 7 workers.
   - Measure against the scorebug again (baseline 79%) before switching over.
3. Optional idea, untested: the bottom half of the broadcast frame shows the hubs from a
   second angle; it could back up the main view.
4. Later stages from the README: robot tracking, 2D replay, penalty checks, coach.

## Product roadmap (this will become an app)

Main risk: the detector must work on matches it has never seen (other events, other
webcast layouts). The second sample already fails (blue AUTO 49 counted vs 154 scored).
Hosting a YouTube downloader is also risky: yt-dlp from cloud IPs gets blocked and may
break YouTube's terms. So: local-first, generalize first, host later only if needed.

1. **Make the engine general.**
   - Train the fuel detector on crops from several events, not just Einstein.
   - Detect hub openings (or the scorebug) instead of hard-coded pixel zones in
     `hub_counter.py` / `overlay.py`; otherwise every new layout breaks.
   - Keep scorebug OCR as the anchor and show each count with an error range.
   - Hand-count 2-3 test clips (one from `EjF9we707DA`, one with END GAME) as a
     regression suite for every model. Save as `dataset/groundtruth.csv`
     (`clip_start, clip_end, hub, count`).
2. **Ship a local app first.** Package the existing FastAPI + web UI (Tauri/Electron or
   PyInstaller). The user downloads video on their own machine; the model runs as ONNX on
   CPU through onnxruntime; ship `fuel.onnx` as a versioned, updatable file.
3. **Hosted version, only on demand.** Queue + workers (e.g. Azure Container Apps jobs),
   Blob Storage, results cached by video id. Accept uploads rather than links unless the
   download question is settled. Azure ML GPU jobs for training are worth it only once
   there is a lot of multi-event data.
4. **Data flywheel.** Let users correct counts in the UI; corrected frames become training
   data. Periodically mine frames where video and scorebug disagree most, label, retrain.

## YOLO training: how to run it

Tools: `tools/extract_crops.py` (crops + pre-labels) and `tools/train_yolo.py` (train + ONNX export).

1. Extract crops (match windows come from `scorebug_clean.json`):
   `python tools/extract_crops.py samples/j8wz5vw5XfE/video.mp4 5 175 --out dataset/raw --every 1.0`
   `python tools/extract_crops.py samples/EjF9we707DA/video.mp4 5 175 --out dataset/raw --every 0.7`
2. Label in CVAT / Label Studio / Roboflow: one class `fuel`, import the pre-labels, fix
   boxes (delete shirts and floor balls, add missed balls, one box per ball), export as
   YOLO format. Aim for 300-500 crops, favouring AUTO and END GAME.
3. Lay out the dataset, splitting by match (put `EjF9we707DA` in val if possible, to test
   on a match the model never saw):
   `dataset/images/{train,val}`, `dataset/labels/{train,val}`, and `dataset/data.yaml`:
   ```
   path: dataset
   train: images/train
   val: images/val
   names: {0: fuel}
   ```
4. Install training deps (not needed to run the app): `pip install ultralytics`
5. Train and export: `python tools/train_yolo.py dataset/data.yaml --epochs 60 --imgsz 448`
   (CPU, under about an hour). Output: `models/fuel.onnx`; training logs in `runs/fuel/`.
6. Check `runs/fuel/results.csv` / the val plots: look at recall first, since misses were
   the problem. Then swap the detector into `hub_counter.py` and compare against the
   hand-counted clips and the scorebug (baseline 79%; target 95%+ with no over-counting).

## Not worth doing

- More frames: the counter already reads every frame (about 60 fps) and 1080p is the
  maximum YouTube resolution, so the misses are not caused by skipped frames.
- Using PyTorch alone: it is only a framework, not a model. COCO-pretrained weights know
  "sports ball" but not FRC fuel, so fine-tuning on labeled crops is needed.

## Session 3: Roboflow model, new direction, infrastructure

### What was tried: Roboflow model `robot-and-hoop-tracking/2`

- RF-DETR small, input 512x512 (stretched), classes `ball` and `robot` (no hoop class).
  Weights cached locally with `tools/cache_roboflow_model.py` (needs `ROBOFLOW_API_KEY`;
  never hard-code it; the original paste used the key as the env var NAME, which fails).
  Cache dir: `~/.roboflow/cache` (set `MODEL_CACHE_DIR` before importing `inference`).
- Speed on CPU: about 0.27 s per full frame (0.27 s per hub crop too, so crops do not help).
- Robots: found well (0.77-0.93 confidence on a full 1080p frame).
- Balls: weak. Balls are about 4 px at 512 input. On a 20 s clip (video 60-80 s of
  `j8wz5vw5XfE`, red scorebug +90, colour counter 72) the model counter gave 20 at
  confidence 0.3 and 60 at 0.1 (tuned on that one clip only).
- Built, off by default: `frcsim/ingest/video/hub_counter_model.py`, `detector="model"` in
  `pipeline.run`, `raw_from=` to reuse an earlier scorebug reading, a UI checkbox
  "Count balls with the Roboflow model", results stored in `samples/<id>_model/`.
  `_Tracker` in `hub_counter.py` now takes `max_step` / `lost_frames`.
- A full-match model run was never finished: about 330 s per 200 of 2,587 sampled frames
  while the web server also ran, so well over an hour. Alone it is roughly 20 min.
  `samples/j8wz5vw5XfE_model/` is incomplete and can be deleted.
- Verdict: the model is not a good ball counter at this resolution. It is a good robot
  detector. Do not build on its ball detections.
- `pytest` passes 11/11 after these changes.

### Direction change (decided this session)

The real goal is a **coach for one robot**: what it did well, what it did not, what its
strategy seems to be, and what it could logically do given what the others do. That needs:

1. **Per-robot behaviour** from video: robot tracking, field positions, role per period
   (scorer / feeder / defender / parked / climber). Per-robot balls do not exist in any
   data source; the best is an estimate (alliance balls split by cycling share).
2. **Many matches per team**, aggregated, because a strategy is a pattern. One match cannot
   tell "always defends" from "was told to defend today".
3. **The whole event**, so a team can be compared with partners and opponents and
   recommendations can be made.

Core change of approach: use **official data as the backbone**, video only for what official
data cannot give.

| Information | Best source |
|---|---|
| Teams, alliances, times, final score, winner, match video link | The Blue Alliance (TBA) API |
| Balls per alliance per period, tower points, fouls | TBA `score_breakdown` (UNVERIFIED for 2026; check first) |
| Second-by-second timing | Scorebug OCR (exists) |
| Robot positions, paths, time near hub | Video + Roboflow `robot` class |
| Per-robot balls | Nowhere; estimate only |

### Plan (saved at `~/.claude/plans/i-need-an-actual-staged-brook.md`, revised here)

0. **Check TBA** (needs a free read key in `.env` as `TBA_API_KEY`; not set yet): fetch one
   2026 match, print `score_breakdown` and `videos`. If per-period fuel is there, it replaces
   the ball counter; if not, keep the scorebug + colour counter blend and use TBA for
   metadata only.
1. **TBA backbone**: `frcsim/ingest/tba.py`; UI takes event + match; teams filled
   automatically; `query.py` scales per-second estimates to the exact TBA period totals.
2. **Robots** (the main work): run the model for the `robot` class only at 2-5 fps; track
   inside one camera shot and split at camera cuts (frame-difference spike); user tags which
   robot is which team once per shot; calibrate image to field positions; rule-based roles.
   **Test this on a few matches before building 3 and 4**: if tracks are unreliable, the
   coach would sit on bad data.
3. **Team profiles**: aggregate per team across an event; compare with the event average.
4. **Coach output**: strengths, weaknesses, strategy, suggestions, each with its source and
   confidence. Do not hand advice to a team until someone with FRC experience has checked
   a few examples.

Avoid: following one robot through a whole match across camera cuts; per-event pixel-zone
hacks; hosting a YouTube downloader (yt-dlp is blocked from cloud IPs and may break
YouTube's terms).

### Difficulty (honest)

- Easy: TBA data, match lists, exact alliance totals, aggregation, UI, writing coach text.
- Medium: field-position calibration (camera moves), strategy logic.
- Hard: tracking robots through broadcast video (cuts, zooms, occlusion), identifying
  which robot is which team, reliable role labels (needs labelled examples).
- Very hard: per-robot ball counts.
- Needs a human: API key, hand-labelled ground-truth clips, an FRC mentor to judge whether
  the advice is useful.
- Realistic solo effort: a useful TBA-based version in weeks; a coach that describes strategy
  from video alone, months.

### Infrastructure proposal (max 100 users, zero cost, an analysis in 5 minutes)

Key idea: **analyse each match once, share the result with everyone.** The 5-minute limit
then applies only to the first analysis of a match; opening an analysed match is instant.
Most of the 100 users only read.

| Part | Choice | Free-tier limit that matters |
|---|---|---|
| Web app (UI) | Static site on Cloudflare Pages or GitHub Pages | Unlimited at this size |
| Data + accounts | Supabase free (Postgres + auth + storage) | 500 MB DB, 1 GB files; store only compact JSON timelines and team profiles, never video |
| TBA data refresh | Scheduled GitHub Actions job writing to the database | Free for public repos (private: 2,000 min/month) |
| Video analysis worker | A Python worker on a PC you control that takes requests from a queue table, downloads the video, analyses it, uploads the JSON | Free; the only place with heavy CPU and the only place that calls YouTube |
| Optional later | A free cloud VM (e.g. Oracle Cloud Always Free) for the worker | Availability varies; YouTube may block datacenter IPs, so keep the downloader on a home IP |

Why this shape:
- Free clouds have no GPU and few CPUs, and YouTube blocks their IPs, so heavy video work
  stays on a home machine and only small results go to the cloud.
- Videos are never stored (too big); only results are kept (a timeline is about 50 KB).
- Users never wait on a download: they request a match, the worker picks it up, and the page
  fills in when the result lands (realtime or polling).
- If the worker is off, the app still serves every match analysed so far plus all TBA data.

Time budget for one new match, to stay under 5 minutes on the worker (8 cores):
- Download 1080p H.264: 30-60 s.
- Scorebug OCR (parallel, 0.5 s step): about 60 s, or skipped if TBA gives period totals.
- Robot detection at 3 fps over about 3.5 min of match = about 630 frames x 0.27 s = about
  3 min single process; faster with 2-3 processes sharing cores. This is the tight part.
- Tracking, roles, JSON upload: seconds.
- Total about 4-5 minutes: feasible but with no slack. The colour ball counter is dropped
  from the critical path (1-2 min, optional). Do not run the model on balls.
- Fallback if it runs over: lower the fps, or show TBA-based results first and fill in the
  robot data when it is ready.

Rules to keep it free:
- Cache everything by TBA match key; never re-analyse.
- Rate-limit requests per user and allow one job at a time (as `web.py` does now).
- Keep API keys (TBA, Roboflow, Supabase service key) in `.env` / secrets, never in the repo
  or the browser; the browser only gets the Supabase publishable key.
- Watch the Supabase 500 MB cap: about 50 KB per match is roughly 10,000 matches.

Not decided yet: whether the first users are teams scouting a rival across an event (my
suggestion; strategy needs several matches per team) or people analysing one match in depth.

### Added requirements: shooting stats and a 2D replay

Wanted per robot: how much it shoots, an estimate of how many balls go in (make rate), and
a simplified 2D simulation of the match showing roughly where each robot is over time,
when it shoots, and when collisions happen.

Everything here depends on **robot positions in field coordinates (metres)**. That makes
"detect robots, then convert image positions to field positions" the foundation; shots,
collisions and the replay are all built on it. `Timeline.frames` / `RobotState` (x, y,
heading, metres) and the `shot` / `foul_call` event kinds already exist in `schema.py`,
and `geometry.py` holds the distance helpers.

**Field calibration (the crux).** The broadcast camera pans and zooms, so one fixed
mapping does not work. Approach: find field landmarks (hubs, tower, field lines) in each
shot and estimate an image-to-field homography per shot (OpenCV `findHomography`), reusing
it while the shot lasts and re-estimating at each camera cut. Fallback: ask the user to
click 4 known field points per shot. Without calibration, only image-space stats are
possible (no replay, no collisions in metres).

**Shots per robot (estimate, with a range).**
- Candidate shot: a robot is slow or stopped inside shooting range of its alliance hub,
  facing it, and balls are seen leaving it (the model does see some balls; it is weak, so
  use it only as supporting evidence, not as a count).
- Made balls: take the alliance's exact balls per period (TBA or scorebug) and split them
  across the alliance's robots by how much each one spent in shooting position at that time.
- Shots = made / assumed make rate, or counted candidates; report **made, estimated shots,
  and a make-rate range**, never a single exact number. Per-robot numbers stay estimates.
- Accuracy cannot be known without hand-labelled clips (count one robot's shots by eye on
  a few matches, then compare).

**Collisions.** Two robots are in contact when their field-space distance is below about
one robot width and at least one shows a sudden velocity change. Image-space box overlap
alone is wrong (perspective makes distant robots overlap). Flag them as "possible contact"
with a confidence; penalty judgement (pinning, etc.) is a later rule-check in
`frcsim/rules/`.

**2D replay.** A canvas page in the web UI: top-down field with hubs (active/inactive
colour), 6 robot markers with team numbers, time slider and play button, shot arcs to the
hub, collision flashes, scoreboard from the timeline. Data is the robot positions at
5-10 Hz, interpolated in the browser; about 6 robots x 160 s x 5 Hz = under 5,000 points,
so storage and the free infrastructure are unaffected. Position gaps (camera on another
area, robot out of shot) must be drawn as "estimated / not seen", not invented.

**Revised build order**
1. TBA backbone (Phase 0 check, then Phase 1), as before.
2. Robot detection + per-shot tracking + field calibration. **Gate: check on 3 matches by
   eye that the markers sit where the robots really are.** If not, stop and fix before
   anything below.
3. 2D replay of positions only (also the best tool for checking step 2 visually).
4. Shot candidates and make-rate estimates; collisions.
5. Team profiles across matches, coach output.

Honest limits: positions are rough whenever the camera does not show a robot; shot counts
and collisions are estimates; the replay is a visualisation of the best guess, not ground
truth, and should say so on screen.
