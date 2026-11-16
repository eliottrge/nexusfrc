import math
from itertools import combinations
from .schema import Frame


def distance(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def pairwise_distances(frame: Frame) -> dict[tuple[int, int], float]:
    return {(a.team, b.team): distance(a, b) for a, b in combinations(frame.robots, 2)}
