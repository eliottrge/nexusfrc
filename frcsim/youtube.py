"""Ask for a YouTube link, download the match, and run the video pipeline on it.

    python -m frcsim                      # asks for the link and the teams
    python -m frcsim URL --blue 868 2046 2910 --red 4065 4414 1323

The video is downloaded as a video-only H.264 stream (no audio), which OpenCV can decode
and which needs no ffmpeg. Everything is written to samples/<video id>/.
(The web UI, `python -m frcsim.web`, uses the same functions.)
"""
import argparse
import re
from pathlib import Path

from . import pipeline

# Every analysis lives in SAMPLES_DIR/<video id>/, wherever the program is started from.
SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"

# H.264 ("avc1") video-only, 1080p preferred. The pipeline cannot decode AV1, and VP9 is unreliable.
FORMAT = "bv*[vcodec^=avc1][height<=1080][ext=mp4]/bv*[vcodec^=avc1][height<=1080]"
# YouTube needs a JavaScript runtime to list all formats (Node.js or deno must be installed).
YDL_BASE = {"noplaylist": True, "js_runtimes": {"node": {}, "deno": {}}}


def fetch_info(url):
    """Look the video up on YouTube without downloading it (id, title, ...)."""
    from yt_dlp import YoutubeDL
    with YoutubeDL({**YDL_BASE, "quiet": True}) as ydl:
        return ydl.extract_info(url, download=False)


def download(url, out_dir, on_progress=None):
    """Download the video to out_dir/video.mp4 and return (path, info).

    on_progress(fraction 0..1) is called while downloading.
    """
    from yt_dlp import YoutubeDL

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "video.mp4"

    def hook(d):
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                on_progress(min(1.0, d["downloaded_bytes"] / total))

    opts = {**YDL_BASE, "format": FORMAT, "outtmpl": str(path), "overwrites": False,
            "progress_hooks": [hook]}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if info.get("height") and info["height"] < 1080:
        print(f"   warning: only {info['height']}p available in H.264; scorebug OCR may be less reliable")
    return path, info


def _ask_teams(color):
    text = input(f"{color} alliance team numbers (space separated, Enter to skip): ").strip()
    return [int(t) for t in re.findall(r"\d+", text)]


def main():
    ap = argparse.ArgumentParser(description="Analyze an FRC match from a YouTube link.")
    ap.add_argument("url", nargs="?", help="YouTube link (asked for if missing)")
    ap.add_argument("--out", help="output folder (default: samples/<video id>)")
    ap.add_argument("--blue", type=int, nargs="*")
    ap.add_argument("--red", type=int, nargs="*")
    ap.add_argument("--match-id")
    ap.add_argument("--workers", type=int, help="CPU processes (default: half the cores, max 8)")
    a = ap.parse_args()

    asked = a.url is None
    url = a.url or input("YouTube link of the match: ").strip()
    if not url:
        raise SystemExit("No link given.")
    blue = a.blue if a.blue is not None else (_ask_teams("Blue") if asked else [])
    red = a.red if a.red is not None else (_ask_teams("Red") if asked else [])

    vid = fetch_info(url)["id"]
    out = Path(a.out or SAMPLES_DIR / vid)

    if (out / "video.mp4").exists():
        print(f"already downloaded: {out / 'video.mp4'}")
    print(f"downloading {url} -> {out / 'video.mp4'}")
    video, info = download(url, out)
    pipeline.run(video, out, blue, red, a.match_id or info.get("title", vid), a.workers)
    print(f"\ndone. results in {out}")


if __name__ == "__main__":
    main()
