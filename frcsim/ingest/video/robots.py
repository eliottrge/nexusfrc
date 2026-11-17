"""Detect robots in match video with the RF-DETR model (models/robots.onnx).

Only this step is slow (about 0.22 s per frame on CPU), so it runs once per match and
stores the raw boxes in robot_detections.json. Everything after it (field positions,
tracking, shots, contacts) is cheap and recomputed from that file whenever a match is
opened (frcsim/robots.py), so settings and calibration can change without re-running it.

The model is run straight through onnxruntime (no Roboflow packages needed): RGB, stretched
to 512x512, ImageNet normalisation; outputs boxes (cx, cy, w, h, 0-1) and class logits.
Each robot box also gets the share of red and blue pixels in its lower half (the bumpers),
which tells the alliance.
"""
import json
import time

import cv2
import numpy as np

from ... import settings

_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)


class Detector:
    def __init__(self, path=None, threads=0):
        import onnxruntime as ort

        path = path or settings.model_path()
        if not path:
            raise FileNotFoundError(
                f"Robot model not found. Put robots.onnx in {settings.MODELS_DIR} (see README).")
        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        self.size = self.session.get_inputs()[0].shape[-1]
        names_file = settings.MODELS_DIR / "robots.classes.txt"
        names = names_file.read_text().split() if names_file.exists() else ["background", "ball", "robot"]
        self.robot_class = names.index("robot")

    def __call__(self, frame, min_conf=None):
        """Robot boxes in pixels: [(x0, y0, x1, y1, confidence), ...]."""
        min_conf = settings.ROBOT_CONFIDENCE if min_conf is None else min_conf
        h, w = frame.shape[:2]
        x = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (self.size, self.size)).astype(np.float32) / 255
        x = ((x - _MEAN) / _STD).transpose(2, 0, 1)[None]
        boxes, logits = self.session.run(None, {self.input: x})
        prob = 1 / (1 + np.exp(-logits[0]))
        out = []
        for (cx, cy, bw, bh), p in zip(boxes[0], prob):
            if p.argmax() == self.robot_class and p[self.robot_class] >= min_conf:
                out.append((float((cx - bw / 2) * w), float((cy - bh / 2) * h),
                            float((cx + bw / 2) * w), float((cy + bh / 2) * h), float(p[self.robot_class])))
        return _nms(out)


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def _nms(boxes, thr=0.6):
    keep = []
    for b in sorted(boxes, key=lambda b: -b[4]):
        if all(_iou(b, k) < thr for k in keep):
            keep.append(b)
    return keep


def bumper_colour(frame, box):
    """(red share, blue share) of saturated pixels in the lower half of the box."""
    x0, y0, x1, y1 = (int(round(v)) for v in box[:4])
    h = y1 - y0
    crop = frame[max(0, y0 + h // 2):max(0, y1), max(0, x0):max(0, x1)]
    if crop.size == 0:
        return 0.0, 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat = (hsv[..., 1] > 110) & (hsv[..., 2] > 70)
    hue = hsv[..., 0]
    red = sat & ((hue < 8) | (hue > 168))
    blue = sat & (hue > 98) & (hue < 128)
    n = crop.shape[0] * crop.shape[1]
    return round(float(red.sum()) / n, 4), round(float(blue.sum()) / n, 4)


def detect(video_path, t0, t1, fps=None, region=None, on_progress=None):
    """Run the detector every 1/fps s of video between t0 and t1.

    region: (x0, y0, x1, y1) pixels; boxes whose bottom-centre is outside are dropped (other
    camera views, crowd). Returns {"fps", "samples": [{"video_t", "robots": [[x0,y0,x1,y1,conf,red,blue]]}]}.
    """
    fps = fps or settings.ROBOT_FPS
    det = Detector()
    cap = cv2.VideoCapture(str(video_path))
    vfps = cap.get(cv2.CAP_PROP_FPS)
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(t0 * vfps))
    pos = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
    n = int((t1 - t0) * fps) + 1
    samples, start = [], time.time()
    for i in range(n):
        target = round((t0 + i / fps) * vfps)
        ok = True
        while ok and pos < target:
            ok = cap.grab()
            pos += 1
        ok, frame = cap.read() if ok else (False, None)
        pos += 1
        if not ok:
            break
        robots = []
        for b in det(frame):
            cx, by = (b[0] + b[2]) / 2, b[3]
            if region and not (region[0] <= cx <= region[2] and region[1] <= by <= region[3]):
                continue
            robots.append([round(v, 1) for v in b[:4]] + [round(b[4], 3), *bumper_colour(frame, b)])
        samples.append({"video_t": round((pos - 1) / vfps, 3), "robots": robots})
        if on_progress and i % 10 == 0:
            on_progress(i / n)
        if i % 100 == 0:
            print(f"   robots: {i}/{n} frames, {time.time() - start:.0f}s", flush=True)
    return {"fps": fps, "samples": samples}


def save(result, path):
    with open(path, "w") as f:
        json.dump(result, f)
