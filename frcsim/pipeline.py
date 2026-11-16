"""Video -> Match Timeline pipeline.

    python -m frcsim.pipeline VIDEO.mp4 --out samples/einstein_final \
        --blue 868 2046 2910 --red 4065 4414 1323 --match-id "2026cmptx_f1m3"

Steps
1. Read the broadcast scorebug (clock + scores) every 0.5 s     -> scorebug_raw.jsonl
2. Clean it into a match-time score timeline                     -> scorebug_clean.json
3. Count balls entering each hub on every video frame            -> hub_entries.json
4. Build the per-second table (counted vs scored, hub state)     -> fuel_per_second.csv
5. Write the canonical Timeline (events + period summaries)      -> timeline.json
6. Print an accuracy report: video count vs scorebug, per period -> report.txt

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


def run(video, out_dir, blue=(), red=(), match_id="", workers=None, progress=None):
    """progress(step, total, message) is called as each stage starts (used by the web UI)."""
    workers = default_workers() if workers is None else max(1, workers)

    def say(step, msg):
        print(f"{step}/5 {msg}...")
        if progress:
            progress(step, 5, msg)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    say(1, f"reading scorebug ({workers} workers)")
    import cv2
    dur = cv2.VideoCapture(str(video)).get(cv2.CAP_PROP_FRAME_COUNT) / cv2.VideoCapture(str(video)).get(cv2.CAP_PROP_FPS)
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

    say(2, "cleaning scorebug")
    clean, quality = scorebug_clean.clean(raw)
    if not any(r["phase"] == "teleop" for r in clean):
        raise SystemExit(
            "No TELEOP found on the scorebug clock (it never restarted at 2:20). "
            "The video must contain the whole match, AUTO and TELEOP.")
    (out / "scorebug_clean.json").write_text(json.dumps(clean))

    say(3, f"counting balls entering each hub ({workers} workers)")
    entries = hub_counter.count_parallel(str(video), t0, t1 + 1, workers)
    (out / "hub_entries.json").write_text(json.dumps(entries))

    say(4, "building per-second table")
    table, auto_winner = fuel_per_second.build(clean, entries)
    with open(out / "fuel_per_second.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)

    say(5, "writing timeline")
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
    timeline = Timeline(match_id=match_id, teams={"blue": list(blue), "red": list(red)},
                        auto_winner=auto_winner, final_score=final, events=events, periods=periods)
    (out / "timeline.json").write_text(timeline.model_dump_json(indent=1))

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
    a = ap.parse_args()
    run(a.video, a.out, a.blue, a.red, a.match_id, a.workers)


if __name__ == "__main__":
    main()
