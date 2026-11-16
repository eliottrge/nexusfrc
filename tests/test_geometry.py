from frcsim.schema import Frame, RobotState
from frcsim.geometry import pairwise_distances


def test_pairwise():
    f = Frame(t=0, robots=[RobotState(team=1, alliance="red", x=0, y=0, heading=0),
                           RobotState(team=2, alliance="blue", x=3, y=4, heading=0)])
    assert pairwise_distances(f)[(1, 2)] == 5
