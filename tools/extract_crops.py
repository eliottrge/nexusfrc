"""Extract hub crops + pre-labels (YOLO format) for fine-tuning a fuel detector.

Usage:
    python tools/extract_crops.py samples/<id>/video.mp4 T0 T1 --out dataset/raw [--every 1.0]

For each sample time in [T0, T1] it reads WARM frames before the sample (to settle the
background model), runs the existing colour+motion detector on both hub regions, and
writes the crop (jpg) plus a YOLO .txt with one box per detected blob. These pre-labels
are only a starting point: open the folder in a labeling tool (CVAT, Label Studio,
Roboflow) and fix them by hand, adding the balls the old detector missed.
"""
import argparse
import math
from pathlib import Path

import cv2

from frcsim.ingest.video import hub_counter as hc

WARM = 20          # frames fed to the background subtractor before each sample
BOX = 18           # px side of the pre-label box (a ball is ~17 px across)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("t0", type=float)
    ap.add_argument("t1", type=float)
    ap.add_argument("--out", default="dataset/raw")
    ap.add_argument("--every", type=float, default=1.0, help="seconds between samples")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.video).parent.name
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_saved = 0
    t = args.t0
    while t <= args.t1:
        start = max(0, round(t * fps) - WARM)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        subs = {k: cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=25, detectShadows=False)
                for k in hc.HUBS}
        frame, dets = None, {}
        for _ in range(WARM + 1):
            ok, frame = cap.read()
            if not ok:
                break
            for k, h in hc.HUBS.items():
                x0, y0, x1, y1 = h["region"]
                dets[k] = hc._detect(frame[y0:y1, x0:x1], subs[k])
        if frame is not None:
            for k, h in hc.HUBS.items():
                x0, y0, x1, y1 = h["region"]
                crop = frame[y0:y1, x0:x1]
                h_px, w_px = crop.shape[:2]
                name = f"{stem}_{k}_{t:07.2f}"
                cv2.imwrite(str(out / f"{name}.jpg"), crop)
                lines = []
                for x, y, n in dets[k]:
                    side = BOX * math.sqrt(n)  # clusters get a larger box; split these by hand
                    lines.append(f"0 {x / w_px:.6f} {y / h_px:.6f} {side / w_px:.6f} {side / h_px:.6f}")
                (out / f"{name}.txt").write_text("\n".join(lines))
                n_saved += 1
        t += args.every
    print(f"wrote {n_saved} crops to {out}")


if __name__ == "__main__":
    main()
