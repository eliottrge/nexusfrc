"""Count FUEL balls entering each HUB, per second, from 1080p broadcast video.

Method (per hub, per frame, main camera view only):
1. Detect moving yellow balls in a region around the hub's funnel: a yellow colour
   mask combined with a background subtractor, so stationary balls on the floor and
   the crowd are ignored.
2. Track each ball frame to frame (nearest neighbour).
3. A ball counts as ENTERED when its track ends inside the hub "mouth" zone (and, if
   MIN_DESCENT > 0, has moved downward), and it does not reappear nearby within a few frames.

Zones are in 1920x1080 pixel coordinates for the 2026 Einstein webcast camera and
must be re-measured for other events or camera angles.
"""
import json
import math
import sys
import time
from bisect import bisect_right

import cv2
import numpy as np

# Search region around each hub (x0, y0, x1, y1) and the mouth zone inside it.
HUBS = {
    # Mouth zones stop short of the hub exits (blue exits on its right, red on its left),
    # so balls leaving a hub are not counted as entering.
    "blue": {"region": (240, 165, 660, 330), "mouth": (360, 185, 560, 290)},
    "red": {"region": (1250, 165, 1660, 330), "mouth": (1350, 185, 1560, 290)},
}
BALL_AREA = (60, 1500)       # px area of one ball blob (bigger blobs = several balls)
SINGLE_BALL_AREA = 230       # measured px area of one ball, used to split clusters
MIN_CIRCULARITY = 0.5        # single-ball blobs must be round (rejects yellow shirts)
MAX_STEP = 60                # max px a ball moves between frames
LOST_FRAMES = 6              # frames unseen before a track is closed
MIN_TRACK = 2                # ignore tracks shorter than this (noise)
MIN_DESCENT = 0              # px a ball must have dropped from its highest point. 0 = off: requiring
                             # 12 px lost balls that enter fast/level (69% -> 79% of scorebug points)


def _detect(crop, subtractor):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(hsv, (18, 110, 120), (38, 255, 255))
    moving = subtractor.apply(crop)
    mask = cv2.morphologyEx(cv2.bitwise_and(yellow, moving), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for q in contours:
        area = cv2.contourArea(q)
        if not BALL_AREA[0] <= area <= BALL_AREA[1]:
            continue
        n = max(1, round(area / SINGLE_BALL_AREA))
        perim = cv2.arcLength(q, True)
        if n == 1 and perim > 0 and 4 * math.pi * area / perim ** 2 < MIN_CIRCULARITY:
            continue
        m = cv2.moments(q)
        if m["m00"] == 0:
            continue
        out.append((m["m10"] / m["m00"], m["m01"] / m["m00"], n))
    return out


class _Tracker:
    def __init__(self, region, mouth, max_step=MAX_STEP, lost_frames=LOST_FRAMES):
        self.max_step, self.lost_frames = max_step, lost_frames
        x0, y0 = region[:2]
        self.mouth = (mouth[0] - x0, mouth[1] - y0, mouth[2] - x0, mouth[3] - y0)
        self.tracks = []   # dict: pts [(frame,x,y)], last, size
        self.entries = []  # (frame, n_balls)

    def _in_mouth(self, x, y):
        a, b, c, d = self.mouth
        return a <= x <= c and b <= y <= d

    def update(self, frame_i, dets):
        # Global greedy matching: closest (track, detection) pairs first.
        pairs = []
        for ti, tr in enumerate(self.tracks):
            _, lx, ly = tr["pts"][-1]
            for di, d in enumerate(dets):
                dist = math.hypot(d[0] - lx, d[1] - ly)
                if dist <= self.max_step:
                    pairs.append((dist, ti, di))
        used_t, used_d = set(), set()
        for _, ti, di in sorted(pairs):
            if ti in used_t or di in used_d:
                continue
            tr, d = self.tracks[ti], dets[di]
            tr["pts"].append((frame_i, d[0], d[1]))
            tr["counts"].append(d[2])
            tr["last"] = frame_i
            used_t.add(ti)
            used_d.add(di)
        for di, d in enumerate(dets):
            if di not in used_d:
                self.tracks.append({"pts": [(frame_i, d[0], d[1])], "counts": [d[2]], "last": frame_i})
        alive = []
        for tr in self.tracks:
            if frame_i - tr["last"] > self.lost_frames:
                self._close(tr)
            else:
                alive.append(tr)
        self.tracks = alive

    def _close(self, tr):
        pts = tr["pts"]
        if len(pts) < MIN_TRACK:
            return
        f_end, x_end, y_end = pts[-1]
        descended = y_end - min(p[2] for p in pts) >= MIN_DESCENT
        if self._in_mouth(x_end, y_end) and descended:
            # number of balls in the blob, from its last few sightings (pairs often travel together)
            n = int(np.median(tr["counts"][-3:]) + 0.5)
            self.entries.append((f_end, max(1, n)))

    def finish(self, frame_i):
        for tr in self.tracks:
            self._close(tr)
        self.tracks = []


def count(video_path, t0, t1, progress_every=600):
    """Return {hub: [(video_t, n_balls), ...]} for entries between video times t0..t1."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(t0 * fps))
    first = int(cap.get(cv2.CAP_PROP_POS_FRAMES))  # timestamps come from frame numbers, so chunks agree
    subs = {k: cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=25, detectShadows=False) for k in HUBS}
    trackers = {k: _Tracker(h["region"], h["mouth"]) for k, h in HUBS.items()}
    n_frames = int((t1 - t0) * fps)
    start = time.time()
    for i in range(n_frames):
        ok, frame = cap.read()
        if not ok:
            break
        for k, h in HUBS.items():
            x0, y0, x1, y1 = h["region"]
            trackers[k].update(i, _detect(frame[y0:y1, x0:x1], subs[k]))
        if progress_every and i % progress_every == 0:
            print(f"{i}/{n_frames} frames, {time.time() - start:.0f}s elapsed", flush=True)
    for tr in trackers.values():
        tr.finish(n_frames)
    return {k: [(round((first + f) / fps, 3), n) for f, n in tr.entries] for k, tr in trackers.items()}


WARMUP = 4.0  # s read before each chunk so the background model and tracks are already settled
TAIL = 2.0    # s read after each chunk so tracks crossing its end are closed


def _count_chunk(args):
    video_path, a, b, lo, hi = args
    res = count(video_path, a, b, progress_every=0)
    return {k: [(t, n) for t, n in v if lo <= t < hi] for k, v in res.items()}


def count_parallel(video_path, t0, t1, workers):
    """Same result as count(), split into time chunks processed on several CPU cores.

    Each chunk starts WARMUP s early and runs TAIL s late, then keeps only the entries
    in its own [lo, hi) range, so every entry is counted by exactly one chunk.
    """
    from concurrent.futures import ProcessPoolExecutor

    if workers <= 1:
        return count(video_path, t0, t1)
    edges = [t0 + (t1 - t0) * i / workers for i in range(workers + 1)]
    jobs = []
    for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
        a = t0 if i == 0 else lo - WARMUP
        b = t1 if i == workers - 1 else hi + TAIL
        jobs.append((video_path, a, b, lo if i else float("-inf"), hi if i < workers - 1 else float("inf")))
    out = {k: [] for k in HUBS}
    with ProcessPoolExecutor(workers) as ex:
        for res in ex.map(_count_chunk, jobs):
            for k, v in res.items():
                out[k].extend(v)
    return out


def per_second(entries, scorebug_rows):
    """Bin entries into whole video seconds and attach the match clock from the scorebug timeline."""
    times = [r["video_t"] for r in scorebug_rows]
    bins = {}
    for hub, evs in entries.items():
        for t, n in evs:
            s = int(t)
            bins.setdefault(s, {"blue": 0, "red": 0})[hub] += n
    out = []
    for s in sorted(bins):
        i = max(0, bisect_right(times, s) - 1)
        r = scorebug_rows[i]
        out.append({"video_s": s, "phase": r["phase"], "match_t": r["match_t"], "clock": r["clock"], **bins[s]})
    return out


if __name__ == "__main__":
    video, t0, t1, out_path = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
    result = count(video, t0, t1)
    with open(out_path, "w") as f:
        json.dump(result, f)
    print({k: sum(n for _, n in v) for k, v in result.items()})
