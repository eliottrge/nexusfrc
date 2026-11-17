"""Field geometry and the image -> field mapping for a broadcast layout.

A layout (frcsim/layouts/<name>.json) describes one webcast design: the frame size, the
part of the frame that shows the field, where the team numbers
are on the scorebug, and calibration points (a field position in metres and the pixel
where it appears; field positions are always given with blue's wall at x=0, so a
layout with blue on the right just has mirrored points). The mapping is a homography fitted to those points, so adding or
moving points in the JSON (or in the UI's calibration view) changes it.

Field coordinates: x along the field (0 = blue alliance wall), y across it (0 = the side
nearest the camera), metres.
"""
import json
import math

import cv2
import numpy as np

from . import settings

DEFAULT_LAYOUT = "einstein2026"


def hub_xy(alliance):
    x = settings.HUB_FROM_WALL if alliance == "blue" else settings.FIELD_LENGTH - settings.HUB_FROM_WALL
    return x, settings.FIELD_WIDTH / 2


def wall_x(alliance):
    return 0.0 if alliance == "blue" else settings.FIELD_LENGTH


def zone_of(x, alliance):
    """'own' (own alliance zone), 'neutral' or 'opponent' for a robot of `alliance` at x."""
    d_own = abs(x - wall_x(alliance))
    d_opp = abs(x - wall_x("red" if alliance == "blue" else "blue"))
    if d_own <= settings.ALLIANCE_ZONE:
        return "own"
    if d_opp <= settings.ALLIANCE_ZONE:
        return "opponent"
    return "neutral"


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def layout_path(name=DEFAULT_LAYOUT):
    return settings.LAYOUTS_DIR / f"{name}.json"


def load_layout(name=DEFAULT_LAYOUT):
    return json.loads(layout_path(name).read_text())


def save_layout(layout, name=DEFAULT_LAYOUT):
    layout_path(name).write_text(json.dumps(layout, indent=1))


class Mapper:
    """Pixel <-> field conversion for one layout, scaled to the actual video size."""

    def __init__(self, layout, frame_w=None, frame_h=None):
        self.layout = layout
        ref_w, ref_h = layout["frame_size"]
        self.kx = (frame_w or ref_w) / ref_w
        self.ky = (frame_h or ref_h) / ref_h
        pts = layout["calibration"]
        if len(pts) < 4:
            raise ValueError("a layout needs at least 4 calibration points")
        field = np.float32([p["field"] for p in pts])
        image = np.float32([[p["image"][0] * self.kx, p["image"][1] * self.ky] for p in pts])
        self.H, _ = cv2.findHomography(image, field)       # image -> field
        self.Hinv = np.linalg.inv(self.H)                   # field -> image
        x0, y0, x1, y1 = layout["field_region"]
        self.region = (x0 * self.kx, y0 * self.ky, x1 * self.kx, y1 * self.ky)

    def to_field(self, px, py):
        v = self.H @ np.array([px, py, 1.0])
        return float(v[0] / v[2]), float(v[1] / v[2])

    def to_image(self, x, y):
        v = self.Hinv @ np.array([x, y, 1.0])
        return float(v[0] / v[2]), float(v[1] / v[2])

    def in_region(self, px, py):
        x0, y0, x1, y1 = self.region
        return x0 <= px <= x1 and y0 <= py <= y1

    def robot_position(self, box):
        """Field position of a robot from its pixel box (x0, y0, x1, y1): the bottom-centre of
        the box is the bumper on the camera side; the centre is ROBOT_GROUND_DEPTH behind it."""
        x, y = self.to_field((box[0] + box[2]) / 2, box[3])
        y += settings.ROBOT_GROUND_DEPTH
        return x, y

    def on_field(self, x, y, margin=0.5):
        return -margin <= x <= settings.FIELD_LENGTH + margin and -margin <= y <= settings.FIELD_WIDTH + margin
