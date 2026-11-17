"""Paths, API keys and every tunable number, in one place.

Change a number here and the next analysis (or, for anything computed when a match is
opened, the next page load) uses it. Nothing else in the code hard-codes these values.

Where things live:
* DATA_DIR   - one folder per analyzed match (default: <repo>/samples, or $NEXUSFRC_DATA).
* MODELS_DIR - the robot detector, robots.onnx (default: <repo>/models, or $NEXUSFRC_MODELS).
* CONFIG     - user settings such as API keys (<user home>/.nexusfrc/config.json). Keys are
               also read from environment variables and from a .env file in the repo root.
               They are never written into the repo or sent to the browser.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("NEXUSFRC_DATA", ROOT / "samples"))
MODELS_DIR = Path(os.environ.get("NEXUSFRC_MODELS", ROOT / "models"))
CONFIG_PATH = Path(os.environ.get("NEXUSFRC_CONFIG", Path.home() / ".nexusfrc" / "config.json"))
LAYOUTS_DIR = Path(__file__).parent / "layouts"

KEY_NAMES = ("TBA_API_KEY",)  # keys the settings page may set


# ---------------------------------------------------------------- keys / user config
def _dotenv():
    p = ROOT / ".env"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("\"'")
    return out


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_config(**values):
    cfg = load_config()
    for k, v in values.items():
        if v is None or v == "":
            cfg.pop(k, None)
        else:
            cfg[k] = v
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=1))


def get_key(name):
    """Environment variable first, then the user config file, then the repo .env file."""
    return os.environ.get(name) or load_config().get(name) or _dotenv().get(name)


# ---------------------------------------------------------------- field (2026 REBUILT)
FIELD_LENGTH = 16.54      # m, x axis: blue alliance wall at x=0, red at x=FIELD_LENGTH
FIELD_WIDTH = 8.07        # m, y axis: y=0 is the side nearest the main camera
HUB_FROM_WALL = 4.03      # m from each alliance wall to its hub centre
HUB_SIZE = 1.19           # m, hub footprint side
ALLIANCE_ZONE = 4.03      # m from the wall: the zone a robot normally scores from (up to the hub line)
ROBOT_SIZE = 0.9          # m, a robot with bumpers (used for contact distance)

# ---------------------------------------------------------------- robot detection (video)
ROBOT_MODEL = "robots.onnx"   # in MODELS_DIR; RF-DETR exported by Roboflow (classes in robots.classes.txt)
ROBOT_FPS = 3.0               # frames per second sent to the detector (0.22 s each on CPU)
ROBOT_CONFIDENCE = 0.45       # min detector score for a robot
ROBOT_GROUND_DEPTH = 0.4      # m added behind the box's bottom edge to reach the robot centre

# ---------------------------------------------------------------- tracking (cheap, recomputed on open)
TRACK_MAX_JUMP = 3.0      # m a robot may move between two samples (about 9 m/s at 3 fps)
TRACK_SMOOTH = 3          # samples in the moving average applied to positions (1 = off)
REPLAY_HZ = 3.0           # position rate stored for the 2D replay

# ---------------------------------------------------------------- behaviour rules
SHOOT_MAX_SPEED = 1.5     # m/s: a robot slower than this inside its alliance zone counts as shooting
SHOOT_ZONE_MARGIN = 0.5   # m beyond the alliance zone still counted (position error is about 0.5 m)
FALLBACK_SHOOT_RANGE = 6.0  # m from its hub: when nobody is "shooting", the closest robot this near gets the balls
SHOT_FLIGHT = 1.0         # s between a shot and the ball counting in the hub
MIN_BURST = 0.5           # s: shorter shooting spells are ignored
CONTACT_DIST = 1.05       # m between two robot centres = touching (about ROBOT_SIZE + slack)
CONTACT_MIN = 0.5         # s of contact before it is reported
DEFENSE_DIST = 2.0        # m: an opponent this close while in the opponent's half counts as defence
ROLE_WEIGHTS = {"scorer": 1.0, "defender": 1.0, "collector": 1.0}  # bias the role guess
ENDGAME_PARK_WALL = 2.5   # m from own wall at the end of the match = parked / climbing (guess)


def model_path():
    p = MODELS_DIR / ROBOT_MODEL
    if p.exists():
        return p
    # fall back to the Roboflow inference cache, if the model was downloaded with the inference package
    alt = Path.home() / ".roboflow" / "cache" / "robot-and-hoop-tracking" / "2" / "weights.onnx"
    return alt if alt.exists() else None
