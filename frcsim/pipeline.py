"""Video -> Match Timeline pipeline.

    python -m frcsim.pipeline VIDEO.mp4 --out samples/<id> [--blue 868 2046 2910 --red 4065 4414 1323]

Steps (outputs in the --out folder)
1. Read the broadcast scorebug (clock + scores) every 0.5 s       -> scorebug_raw.jsonl
2. Clean it into a match-time score timeline; read team numbers   -> scorebug_clean.json
3. Count balls entering each hub on every frame (colour counter)  -> hub_entries.json
   and, at the same time, detect robots at settings.ROBOT_FPS      -> robot_detections.json
4. Build the per-second table (counted vs scored, hub state)      -> fuel_per_second.csv
5. Write the Timeline, run info and an accuracy report            -> timeline.json, meta.json, report.txt

Robot tracks, shots and contacts are computed from robot_detections.json when a match is
opened (frcsim/robots.py), so they follow settings and calibration changes without a re-run.
The match window is found automatically from the frames where the scorebug clock is readable.
"""
import argparse
import csv
import json
import os
from pathlib import Path

from .ingest.video import fuel_per_second, hub_counter, overlay, scorebug_clean
from .schema import Event, PeriodSummary, Timeline


def find_match_window(raw_rows):
    """Longest run of consecutive samples with a readable clock -> (video_t_start, video_t_end)."""
    best, cur = (0, -1), None
    for i, r in enumerate(raw_rows):
        if r["clock"] is not None:
            cur = i if cur is None else cur
            if i - cur > best[1] - best[0]:
                best = (cur, i)
        else:
            cur = None
    return raw_rows[best[0]]["video_t"], raw_rows[best[1]]["video_t"]


def video_to_match_t(clean_rows):
    """Return f(video_t) -> match_t using the nearest earlier scorebug sample."""
    from bisect import bisect_right
    times = [r["video_t"] for r in clean_rows]

    def f(t):
        r = clean_rows[max(0, bisect_right(times, t) - 1)]
        return float(r["match_t"]) if r["match_t"] is not None else 0.0
    return f


def summarize_periods(table):
    out = {}
    for row in table:
        p = out.setdefault(row["period"], {
            "name": row["period"], "start": None, "end": None,
            "blue_active": row["blue_active"], "red_active": row["red_active"],
            "blue_scored": 0, "red_scored": 0, "blue_counted": 0, "red_counted": 0})
        p["start"] = row["video_s"] if p["start"] is None else p["start"]
        p["end"] = row["video_s"] + 1
        for k in ("blue_scored", "red_scored", "blue_counted", "red_counted"):
            p[k] += row[k]
    return [PeriodSummary(**p) for p in out.values()]


def report_text(periods, final):
    lines = ["Video ball count vs scorebug (scorebug is exact for the ACTIVE hub only)",
             f"{'period':11s} {'blue cnt/scored':>16s} {'red cnt/scored':>15s}"]
    for p in periods:
        b = f"{p.blue_counted}/{p.blue_scored}" + ("" if p.blue_active else " (off)")
        r = f"{p.red_counted}/{p.red_scored}" + ("" if p.red_active else " (off)")
        lines.append(f"{p.name:11s} {b:>16s} {r:>15s}")
    lines.append(f"last scorebug reading: blue {final['blue']}  red {final['red']}"
                 " (the final 3-second scoring window may be missing)")
    return "\n".join(lines)


def default_workers():
    return max(1, min(8, (os.cpu_count() or 2) // 2))


STEPS = 5


def run(video, out_dir, blue=(), red=(), match_id="", workers=None, progress=None, layout=None,
        robots=True, meta=None):
    """Analyze one match video into out_dir. Returns the Timeline.

    progress(step, total, message, fraction) is called as stages advance (used by the web UI).
    blue/red: team numbers; read from the scorebug when not given.
    robots: also run the robot detector (skipped with a note if the model file is missing).
    meta: extra facts saved in meta.json (video id, TBA match key, ...).
    """
    from .field import load_layout, DEFAULT_LAYOUT

    workers = default_workers() if workers is None else max(1, workers)
    layout_name = layout or DEFAULT_LAYOUT
    lay = load_layout(layout_name)

    def say(step, msg, frac=0.0):
        if frac == 0.0:
            print(f"{step}/{STEPS} {msg}...")
        if progress:
            progress(step, STEPS, msg, frac)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    import cv2
    say(1, f"reading the scorebug ({workers} workers)")
    cap = cv2.VideoCapture(str(video))
    vfps = cap.get(cv2.CAP_PROP_FPS) or 0
    dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / vfps if vfps else 0
    vw, vh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if dur <= 1:
        raise SystemExit(f"Could not open {video} as a video.")
    if workers > 1:
        raw = overlay.scan_parallel(str(video), 0, dur - 0.5, 0.5, workers, out_path=str(out / "scorebug_raw.jsonl"))
    else:
        raw = overlay.scan(str(video), 0, dur - 0.5, step=0.5, out_path=str(out / "scorebug_raw.jsonl"))
    if not raw:
        raise SystemExit(
            f"Could not decode any frame of {video}. OpenCV opened the file but cannot read it; "
            "the codec is probably unsupported (often AV1 from YouTube downloads). "
            "Re-encode to H.264, e.g.: ffmpeg -i in.mp4 -c:v libx264 -crf 18 -an out.mp4")
    if all(r["clock"] is None for r in raw):
        raise SystemExit(
            "The scorebug clock was never readable. The video must be the FIRST Championship "
            "webcast layout (see BOXES in frcsim/ingest/video/overlay.py).")
    t0, t1 = find_match_window(raw)
    raw = [r for r in raw if t0 <= r["video_t"] <= t1]
    print(f"   match found at video {t0:.1f}s - {t1:.1f}s")

    say(2, "cleaning the scorebug and reading team numbers")
    clean, quality = scorebug_clean.clean(raw)
    if not any(r["phase"] == "teleop" for r in clean):
        raise SystemExit(
            "No TELEOP found on the scorebug clock (it never restarted at 2:20). "
            "The video must contain the whole match, AUTO and TELEOP.")
    (out / "scorebug_clean.json").write_text(json.dumps(clean))
    teams = {"blue": list(blue), "red": list(red)}
    if (not blue or not red) and lay.get("team_boxes"):
        read = overlay.read_teams(video, [t0 + (t1 - t0) * k / 6 for k in range(1, 6)], lay["team_boxes"])
        teams = {a: teams[a] or read.get(a, []) for a in teams}
        print(f"   teams: blue {teams['blue']}  red {teams['red']}")

    # 3 + 4: ball counter (CPU processes) and robot detector (onnxruntime threads) run at the same time
    from concurrent.futures import ThreadPoolExecutor
    from .field import Mapper
    from .ingest.video import robots as robot_det
    from . import settings

    have_model = robots and settings.model_path() is not None
    robot_note = None if have_model else ("robot model missing: put robots.onnx in " + str(settings.MODELS_DIR)
                                          if robots else "robot detection turned off")
    say(3, "counting balls and finding robots" if have_model else f"counting balls ({workers} workers)")
    with ThreadPoolExecutor(2) as ex:
        balls_f = ex.submit(hub_counter.count_parallel, str(video), t0, t1 + 1, max(1, workers - 1) if have_model else workers)
        robots_f = None
        if have_model:
            region = Mapper(lay, vw, vh).region
            robots_f = ex.submit(robot_det.detect, video, t0, t1 + 1, None, region,
                                 lambda f: say(3, f"counting balls and finding robots ({f:.0%})", f))
        entries = balls_f.result()
        if robots_f:
            try:
                robot_det.save(robots_f.result(), out / "robot_detections.json")
            except Exception as e:  # the timeline is still useful without robots
                robot_note = f"robot detection failed: {e}"
                print("   " + robot_note)
    (out / "hub_entries.json").write_text(json.dumps(entries))

    say(4, "building the per-second table")
    table, auto_winner = fuel_per_second.build(clean, entries)
    with open(out / "fuel_per_second.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)

    say(5, "writing the timeline")
    to_mt = video_to_match_t(clean)
    events = []
    for row in table:
        for a in ("blue", "red"):
            mt = to_mt(row["video_s"])
            if row[f"{a}_scored"] > 0:
                events.append(Event(t=mt, kind="fuel_scored", alliance=a, count=row[f"{a}_scored"],
                                    hub_active=row[f"{a}_active"], source="scorebug_ocr"))
            if row[f"{a}_counted"] > 0:
                events.append(Event(t=mt, kind="fuel_entry", alliance=a, count=row[f"{a}_counted"],
                                    hub_active=row[f"{a}_active"], source="video_counter"))
    periods = summarize_periods(table)
    final = {"blue": clean[-1]["blue"] or 0, "red": clean[-1]["red"] or 0}
    timeline = Timeline(match_id=match_id, teams=teams,
                        auto_winner=auto_winner, final_score=final, events=events, periods=periods)
    (out / "timeline.json").write_text(timeline.model_dump_json(indent=1))
    info = {**(meta or {}), "layout": layout_name, "frame_size": [vw, vh], "video_window": [t0, t1],
            "robot_note": robot_note}
    (out / "meta.json").write_text(json.dumps(info, indent=1))

    text = report_text(periods, final) + f"\nscorebug quality: {quality}"
    (out / "report.txt").write_text(text)
    print(text)
    return timeline


def main():
    ap = argparse.ArgumentParser(description="Turn a match video into a Match Timeline.")
    ap.add_argument("video")
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--blue", type=int, nargs="*", default=[])
    ap.add_argument("--red", type=int, nargs="*", default=[])
    ap.add_argument("--match-id", default="")
    ap.add_argument("--workers", type=int, help="CPU processes (default: half the cores, max 8; "
                    "1 = single process, exactly reproducible ball counts)")
    ap.add_argument("--no-robots", action="store_true", help="skip robot detection")
    a = ap.parse_args()
    run(a.video, a.out, a.blue, a.red, a.match_id, a.workers, robots=not a.no_robots)


if __name__ == "__main__":
    main()
