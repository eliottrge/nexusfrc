"""Web UI: paste a YouTube link, wait for the analysis, then pick any two times on the
match timeline and see how many balls each alliance scored between them.

    python -m frcsim.web            # then open http://127.0.0.1:8000

Every analysis is stored in samples/<video id>/, so a match is only analyzed once and
earlier ones can be reopened from the list.
"""
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import pipeline, query, youtube

STATIC = Path(__file__).parent / "static"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # video ids and folder names; blocks path tricks

app = FastAPI(title="nexusfrc")
jobs: dict[str, dict] = {}
_lock = threading.Lock()
_analyses: dict[str, tuple[float, dict, dict]] = {}  # match id -> (mtime, timeline meta, analysis)


class JobRequest(BaseModel):
    url: str
    blue: list[int] = []
    red: list[int] = []
    force: bool = False  # re-run even if this match was analyzed before


def _timeline_path(match):
    if not ID_RE.match(match):
        raise HTTPException(404, "unknown match")
    p = youtube.SAMPLES_DIR / match / "timeline.json"
    if not p.exists():
        raise HTTPException(404, "unknown match")
    return p


def _load(match):
    """Timeline analysis for a stored match, cached until its file changes."""
    p = _timeline_path(match)
    mtime = p.stat().st_mtime
    hit = _analyses.get(match)
    if hit and hit[0] == mtime:
        return hit[1], hit[2]
    tl = query.load(p)
    meta = {"id": match, "match_id": tl.match_id, "teams": tl.teams, "final_score": tl.final_score,
            "auto_winner": tl.auto_winner, "duration": tl.duration}
    _analyses[match] = (mtime, meta, query.analyze(tl))
    return _analyses[match][1], _analyses[match][2]


def _set(job, **kw):
    with _lock:
        job.update(kw)


def _run_job(job, req):
    try:
        _set(job, stage="looking up the video", progress=0.02)
        info = youtube.fetch_info(req.url)
        match = info["id"]
        out = youtube.SAMPLES_DIR / match
        _set(job, match=match, title=info.get("title", match))
        if (out / "timeline.json").exists() and not req.force:
            _set(job, status="done", stage="already analyzed", progress=1.0)
            return

        _set(job, stage="downloading the video", progress=0.05)
        video, info = youtube.download(
            req.url, out, on_progress=lambda f: _set(job, progress=0.05 + 0.15 * f))

        def stage(step, total, msg):
            _set(job, stage=msg, progress=0.2 + 0.8 * (step - 1) / total)

        pipeline.run(video, out, req.blue, req.red, info.get("title", match), progress=stage)
        _set(job, status="done", stage="finished", progress=1.0)
    except (Exception, SystemExit) as e:  # the pipeline reports problems with SystemExit
        _set(job, status="error", error=str(e) or type(e).__name__)


@app.post("/api/jobs")
def start_job(req: JobRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "Paste a YouTube link first.")
    with _lock:
        running = next((j for j in jobs.values() if j["status"] == "running"), None)
        if running:
            raise HTTPException(409, f"Already analyzing \"{running.get('title') or running['url']}\"; wait for it to finish.")
        job = {"id": uuid.uuid4().hex[:8], "url": url, "status": "running", "stage": "starting",
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


@app.get("/api/matches")
def list_matches():
    items = []
    for p in sorted(youtube.SAMPLES_DIR.glob("*/timeline.json"), key=lambda p: -p.stat().st_mtime):
        if ID_RE.match(p.parent.name):
            meta, _ = _load(p.parent.name)
            items.append({"id": meta["id"], "match_id": meta["match_id"], "final_score": meta["final_score"]})
    return items


@app.get("/api/matches/{match}")
def get_match(match: str):
    meta, analysis = _load(match)
    return {**meta, **analysis}


@app.get("/api/matches/{match}/count")
def count(match: str, start: float, end: float):
    _, analysis = _load(match)
    if end < start:
        start, end = end, start
    return query.count_range(analysis, start, end)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


def main():
    import uvicorn
    print("open http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


# The guard matters: the parallel worker processes re-import this module on Windows.
if __name__ == "__main__":
    main()
