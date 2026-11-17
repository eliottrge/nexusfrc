"""nexusfrc local app: FastAPI server + the single-page UI in frcsim/static.

    python -m frcsim.web          # or: nexusfrc   (after pip install -e .)

Opens http://127.0.0.1:8000. Every analysis is stored in DATA_DIR/<video id>/ (see
settings.py), so a match is analyzed once and can be reopened instantly. Robot tracks,
shots, contacts, team profiles and coaching are computed from the stored files when asked
for, so changing settings, calibration or robot labels never needs a re-analysis.
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import coach, field, pipeline, query, robots, settings, youtube
from .ingest import tba

STATIC = Path(__file__).parent / "static"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # folder names; blocks path tricks

app = FastAPI(title="nexusfrc")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
jobs: dict[str, dict] = {}
_lock = threading.Lock()
_cache: dict[tuple, tuple] = {}  # (kind, match) -> (file mtimes, value)


# ---------------------------------------------------------------- helpers
def _dir(match):
    if not ID_RE.match(match or ""):
        raise HTTPException(404, "unknown match")
    d = settings.DATA_DIR / match
    if not (d / "timeline.json").exists():
        raise HTTPException(404, "unknown match")
    return d


def _mtimes(*paths):
    return tuple(p.stat().st_mtime if p.exists() else 0 for p in paths)


def _cached(kind, match, paths, compute):
    key, stamp = (kind, match), _mtimes(*paths)
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    value = compute()
    _cache[key] = (stamp, value)
    return value


def _meta(d):
    p = d / "meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _balls(match):
    d = _dir(match)

    def compute():
        tl = query.load(d / "timeline.json")
        meta = _meta(d)
        info = {"id": match, "match_id": tl.match_id, "teams": tl.teams, "final_score": tl.final_score,
                "auto_winner": tl.auto_winner, "duration": tl.duration, "tba": meta.get("tba"),
                "robot_note": meta.get("robot_note")}
        return info, query.analyze(tl)
    return _cached("balls", match, [d / "timeline.json", d / "meta.json"], compute)


def _robots(match):
    d = _dir(match)
    det_p = d / "robot_detections.json"
    paths = [det_p, robots.labels_path(d), field.layout_path(_meta(d).get("layout", field.DEFAULT_LAYOUT)),
             d / "timeline.json"]

    def compute():
        if not det_p.exists():
            note = _meta(d).get("robot_note") or "this match was analyzed before robot tracking existed; re-analyze it"
            return {"available": False, "reason": note}
        meta, balls = _balls(match)
        r = robots.analyze(json.loads(det_p.read_text()), json.loads((d / "scorebug_clean.json").read_text()),
                           balls, meta["teams"], robots.load_labels(d),
                           field.load_layout(_meta(d).get("layout", field.DEFAULT_LAYOUT)),
                           tuple(_meta(d).get("frame_size", (1920, 1080))))
        r["notes"] = coach.match_notes(r)
        return r
    return _cached("robots", match, paths, compute)


def _match_ids():
    out = []
    for p in sorted(settings.DATA_DIR.glob("*/timeline.json"), key=lambda p: -p.stat().st_mtime):
        if ID_RE.match(p.parent.name) and not p.parent.name.startswith("_"):
            out.append(p.parent.name)
    return out


def _profiles():
    analyses = {m: _robots(m) for m in _match_ids()}
    return coach.profiles(coach.match_rows(analyses))


# ---------------------------------------------------------------- analysis jobs
class JobRequest(BaseModel):
    url: str = ""
    tba_match: str = ""   # e.g. 2026cmptx_f1m3: video and teams come from TBA
    blue: list[int] = []
    red: list[int] = []
    force: bool = False   # re-run even if this match was analyzed before


def _set(job, **kw):
    with _lock:
        job.update(kw)


def _run_job(job, req):
    try:
        url, blue, red, meta, title = req.url.strip(), req.blue, req.red, {}, None
        if req.tba_match:
            _set(job, stage="looking the match up on The Blue Alliance", progress=0.01)
            m = tba.match(req.tba_match.strip())
            if not m["youtube"]:
                raise ValueError(f"TBA has no YouTube video for {m['key']}.")
            url = url or f"https://www.youtube.com/watch?v={m['youtube'][0]}"
            blue, red = blue or m["teams"]["blue"], red or m["teams"]["red"]
            meta["tba"] = {k: m[k] for k in ("key", "event", "name", "score", "winner", "breakdown")}
            title = f"{m['event']} {m['name']}"
        _set(job, stage="looking up the video", progress=0.02)
        info = youtube.fetch_info(url)
        match = info["id"]
        out = settings.DATA_DIR / match
        title = title or info.get("title", match)
        _set(job, match=match, title=title)
        if (out / "timeline.json").exists() and not req.force:
            if meta:  # attach TBA facts to an existing analysis
                (out / "meta.json").write_text(json.dumps({**_meta(out), **meta}, indent=1))
            _set(job, status="done", stage="already analyzed", progress=1.0)
            return
        _set(job, stage="downloading the video", progress=0.05)
        video, info = youtube.download(url, out, on_progress=lambda f: _set(job, progress=0.05 + 0.1 * f))

        def stage(step, total, msg, frac=0.0):
            _set(job, stage=msg, progress=0.15 + 0.85 * (step - 1 + frac) / total)

        pipeline.run(video, out, blue, red, title, progress=stage, meta={"video_id": match, **meta})
        _set(job, status="done", stage="finished", progress=1.0)
    except (Exception, SystemExit) as e:  # the pipeline reports problems with SystemExit
        _set(job, status="error", error=str(e) or type(e).__name__)


@app.post("/api/jobs")
def start_job(req: JobRequest):
    if not req.url.strip() and not req.tba_match.strip():
        raise HTTPException(400, "Paste a YouTube link or pick a match from The Blue Alliance first.")
    with _lock:
        running = next((j for j in jobs.values() if j["status"] == "running"), None)
        if running:
            raise HTTPException(409, f"Already analyzing \"{running.get('title') or running['url']}\"; wait for it to finish.")
        job = {"id": uuid.uuid4().hex[:8], "url": req.url or req.tba_match, "status": "running", "stage": "starting",
               "progress": 0.0, "match": None, "title": None, "error": None, "started": time.time()}
        jobs[job["id"]] = job
    threading.Thread(target=_run_job, args=(job, req), daemon=True).start()
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, "unknown job")
        return {**job, "elapsed": round(time.time() - job["started"])}


# ---------------------------------------------------------------- matches
@app.get("/api/matches")
def list_matches():
    items = []
    for m in _match_ids():
        info, _ = _balls(m)
        items.append({"id": m, "match_id": info["match_id"], "final_score": info["final_score"],
                      "teams": info["teams"], "robots": (settings.DATA_DIR / m / "robot_detections.json").exists()})
    return items


@app.get("/api/matches/{match}")
def get_match(match: str):
    info, analysis = _balls(match)
    return {**info, **analysis}


@app.get("/api/matches/{match}/count")
def count(match: str, start: float, end: float):
    _, analysis = _balls(match)
    if end < start:
        start, end = end, start
    return query.count_range(analysis, start, end)


@app.get("/api/matches/{match}/robots")
def get_robots(match: str):
    return _robots(match)


@app.put("/api/matches/{match}/labels")
def put_labels(match: str, labels: dict[str, int | None]):
    return robots.save_labels(_dir(match), labels)


@app.get("/api/matches/{match}/frame")
def frame(match: str, t: float = 60.0, grid: bool = True):
    """A video frame at match time t with the calibration grid and tracked robots drawn on it,
    to check by eye that positions are right."""
    import cv2

    d = _dir(match)
    video = d / "video.mp4"
    if not video.exists():
        raise HTTPException(404, "the video file of this match is not stored")
    meta = _meta(d)
    clean = json.loads((d / "scorebug_clean.json").read_text())
    rows = [r for r in clean if r.get("match_t") is not None]
    vt = min(rows, key=lambda r: abs(r["match_t"] - t))["video_t"] + (t - min(rows, key=lambda r: abs(r["match_t"] - t))["match_t"])
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_POS_FRAMES, round(vt * cap.get(cv2.CAP_PROP_FPS)))
    ok, img = cap.read()
    if not ok:
        raise HTTPException(404, "could not read that frame")
    h, w = img.shape[:2]
    mapper = field.Mapper(field.load_layout(meta.get("layout", field.DEFAULT_LAYOUT)), w, h)
    if grid:
        P = lambda x, y: tuple(int(v) for v in mapper.to_image(x, y))
        for x in range(0, int(settings.FIELD_LENGTH) + 1):
            cv2.line(img, P(x, 0), P(x, settings.FIELD_WIDTH), (0, 220, 255), 1)
        for y in range(0, int(settings.FIELD_WIDTH) + 1):
            cv2.line(img, P(0, y), P(settings.FIELD_LENGTH, y), (0, 220, 255), 1)
        for p in mapper.layout["calibration"]:
            cv2.circle(img, (int(p["image"][0] * mapper.kx), int(p["image"][1] * mapper.ky)), 7, (0, 255, 0), -1)
    r = _robots(match)
    if r.get("available"):
        i = min(range(len(r["times"])), key=lambda k: abs(r["times"][k] - t))
        for rb in r["robots"]:
            p = r["positions"][rb["slot"]][i]
            if not p:
                continue
            px, py = mapper.to_image(p[0], p[1] - settings.ROBOT_GROUND_DEPTH)
            col = (255, 140, 40) if rb["alliance"] == "blue" else (60, 60, 230)
            cv2.circle(img, (int(px), int(py)), 11, col, -1 if p[2] else 3)
            label = str(rb["team"] or rb["slot"])
            cv2.putText(img, label, (int(px) + 10, int(py) + 32), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 4)
            cv2.putText(img, label, (int(px) + 10, int(py) + 32), cv2.FONT_HERSHEY_SIMPLEX, 1, col, 2)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(buf.tobytes(), media_type="image/jpeg")


# ---------------------------------------------------------------- calibration
@app.get("/api/layout")
def get_layout(name: str = field.DEFAULT_LAYOUT):
    return field.load_layout(name)


class LayoutUpdate(BaseModel):
    calibration: list[dict]


@app.put("/api/layout")
def put_layout(body: LayoutUpdate, name: str = field.DEFAULT_LAYOUT):
    lay = field.load_layout(name)
    pts = [{"label": str(p.get("label", "")), "field": [float(v) for v in p["field"]],
            "image": [float(v) for v in p["image"]]} for p in body.calibration]
    if len(pts) < 4:
        raise HTTPException(400, "at least 4 calibration points are needed")
    lay["calibration"] = pts
    field.Mapper(lay)  # raises if the points are degenerate
    field.save_layout(lay, name)
    return lay


# ---------------------------------------------------------------- teams and coach
@app.get("/api/teams")
def list_teams():
    profs = _profiles()
    return {"field": coach.field_average(profs), "metrics": coach.METRICS,
            "teams": sorted(profs.values(), key=lambda p: -p["avg"]["balls_est"])}


@app.get("/api/teams/{team}")
def team_report(team: int):
    rep = coach.report(team, _profiles())
    if not rep:
        raise HTTPException(404, f"no analyzed match with team {team} yet")
    rep["metrics"] = coach.METRICS
    return rep


@app.get("/api/recommend")
def recommend(team: int, partners: str = "", opponents: str = ""):
    nums = lambda s: [int(x) for x in re.findall(r"\d+", s)]
    return coach.recommend(team, nums(partners), nums(opponents), _profiles())


# ---------------------------------------------------------------- The Blue Alliance
@app.get("/api/tba/events")
def tba_events(year: int):
    try:
        return tba.events(year)
    except tba.TBAError as e:
        raise HTTPException(400, str(e))


@app.get("/api/tba/event/{event_key}")
def tba_event(event_key: str):
    try:
        ms = tba.event_matches(event_key)
    except tba.TBAError as e:
        raise HTTPException(400, str(e))
    done = set(_match_ids())
    for m in ms:
        m["analyzed"] = next((v for v in m["youtube"] if v in done), None)
        m.pop("breakdown", None)
    return ms


# ---------------------------------------------------------------- settings
@app.get("/api/settings")
def get_settings():
    return {"tba_key_set": bool(settings.get_key("TBA_API_KEY")),
            "model_found": settings.model_path() is not None,
            "data_dir": str(settings.DATA_DIR), "models_dir": str(settings.MODELS_DIR),
            "config_file": str(settings.CONFIG_PATH)}


class SettingsUpdate(BaseModel):
    TBA_API_KEY: str | None = None


@app.put("/api/settings")
def put_settings(body: SettingsUpdate):
    if body.TBA_API_KEY is not None:
        settings.save_config(TBA_API_KEY=body.TBA_API_KEY.strip())
    return get_settings()


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def main():
    import webbrowser

    import uvicorn
    url = "http://127.0.0.1:8000"
    print("nexusfrc running at " + url)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


# The guard matters: the parallel worker processes re-import this module on Windows.
if __name__ == "__main__":
    main()
