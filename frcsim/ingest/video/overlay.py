"""Read the broadcast scorebug (match clock + both alliance scores) from match video.

Crop boxes are for the 640x360 FIRST Championship webcast layout, as (x0, y0, x1, y1).
OCR runs in recognition-only mode: the number positions are fixed, so the slow
text-detection and orientation models are skipped.
"""
import json
import os
import re
import sys
import time

import cv2
from rapidocr_onnxruntime import RapidOCR

# Boxes measured on the 640x360 webcast; scaled to the actual frame width (works for 1080p too).
BOXES = {"blue": (258, 20, 302, 44), "clock": (302, 18, 340, 44), "red": (340, 20, 384, 44)}
_REF_WIDTH = 640
_OCR_HEIGHT = 96  # crops are resized to this height before OCR
_ocr = None
_ocr_threads = -1  # onnxruntime threads; -1 = all cores. Parallel workers each get a share.


def _engine():
    global _ocr
    if _ocr is None:
        _ocr = RapidOCR(intra_op_num_threads=_ocr_threads, inter_op_num_threads=1)
    return _ocr


def _init_worker(threads):
    global _ocr_threads
    _ocr_threads = threads


def _read(img, box, pattern):
    k = img.shape[1] / _REF_WIDTH
    x0, y0, x1, y1 = (int(v * k) for v in box)
    crop = img[y0:y1, x0:x1]
    scale = _OCR_HEIGHT / crop.shape[0]
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    res, _ = _engine()(crop, use_det=False, use_cls=False, use_rec=True)
    text = "".join(r[0] for r in (res or [])).replace(" ", "").replace("O", "0")
    m = re.search(pattern, text)
    return m.group(0) if m else None


def read_frame(img):
    clock = _read(img, BOXES["clock"], r"\d:\d\d")
    secs = int(clock[0]) * 60 + int(clock[2:]) if clock else None
    blue = _read(img, BOXES["blue"], r"\d+")
    red = _read(img, BOXES["red"], r"\d+")
    return {"clock": secs, "blue": int(blue) if blue else None, "red": int(red) if red else None}


def read_teams(path, times, boxes):
    """Team numbers per alliance, read from the scorebug at several video times (majority vote).

    boxes: {"blue": (x0, y0, x1, y1), "red": ...} in pixels of a 1920-wide frame (from the layout).
    Returns {"blue": [n1, n2, n3], "red": [...]} in the order shown on the scorebug, or empty lists.
    """
    from collections import Counter

    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    votes = {a: Counter() for a in boxes}
    for t in times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, round(t * fps))
        ok, img = cap.read()
        if not ok:
            continue
        k = img.shape[1] / 1920
        for a, box in boxes.items():
            x0, y0, x1, y1 = (int(v * k) for v in box)
            crop = cv2.resize(img[y0:y1, x0:x1], None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            res, _ = _engine()(crop)  # detection on: three numbers between team logos
            nums = []
            for n in re.findall(r"\d{1,5}", " ".join(r[1] for r in (res or []))):
                if len(n) >= 2 and n not in nums:
                    nums.append(n)
            if len(nums) >= 3:
                votes[a][tuple(int(n) for n in nums[:3])] += 1
    return {a: list(v.most_common(1)[0][0]) if v else [] for a, v in votes.items()}


def scan(path, t0, t1, step=1.0, out_path=None, progress=True):
    """Sample the scorebug every `step` seconds of video between t0 and t1.

    Seeks once, then reads forward, skipping unneeded frames with grab() (seeking for
    every sample is ~25x slower). Prints progress and, if out_path is given, writes one
    JSON line per frame as it goes.
    """
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(round((t1 - t0) / step, 6)) + 1
    rows, start = [], time.time()
    out = open(out_path, "w") if out_path else None
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(t0 * fps))
    pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))  # index of the next frame read() returns
    for i in range(n):
        t = t0 + i * step
        target = round(t * fps)  # same frame a millisecond seek lands on
        ok = True
        while ok and pos < target:
            ok = cap.grab()
            pos += 1
        ok, frame = cap.read() if ok else (False, None)
        pos += 1
        if not ok:
            break
        row = {"video_t": round(t, 2), **read_frame(frame)}
        rows.append(row)
        if out:
            out.write(json.dumps(row) + "\n")
            out.flush()
        if progress and i % 20 == 0:
            print(f"{i + 1}/{n} frames, {time.time() - start:.0f}s elapsed", flush=True)
    if out:
        out.close()
    return rows


def _scan_chunk(args):
    path, a, b, step = args
    return scan(path, a, b, step, progress=False)


def scan_parallel(path, t0, t1, step, workers, out_path=None):
    """Same result as scan(), split into time chunks processed on several CPU cores."""
    from concurrent.futures import ProcessPoolExecutor

    n = int(round((t1 - t0) / step, 6)) + 1
    workers = max(1, min(workers, n))
    bounds = [n * i // workers for i in range(workers + 1)]
    jobs = [(path, t0 + i0 * step, t0 + (i1 - 1) * step, step) for i0, i1 in zip(bounds, bounds[1:]) if i1 > i0]
    rows = []
    threads = max(1, (os.cpu_count() or 1) // len(jobs))
    with ProcessPoolExecutor(len(jobs), initializer=_init_worker, initargs=(threads,)) as ex:
        for part in ex.map(_scan_chunk, jobs):
            rows.extend(part)
    if out_path:
        with open(out_path, "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    return rows


if __name__ == "__main__":
    scan(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), out_path=sys.argv[4])
