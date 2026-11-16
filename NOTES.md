# Notes: where the project stands and what to do next

Written at the end of a working session so we can pick it up later.

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
- `samples/einstein_final_tiebreaker/` holds the same match as `j8wz5vw5XfE` (older run).

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

## Not worth doing

- More frames: the counter already reads every frame (about 60 fps) and 1080p is the
  maximum YouTube resolution, so the misses are not caused by skipped frames.
- Using PyTorch alone: it is only a framework, not a model. COCO-pretrained weights know
  "sports ball" but not FRC fuel, so fine-tuning on labeled crops is needed.
