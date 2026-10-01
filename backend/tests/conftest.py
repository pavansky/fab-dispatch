import pytest

from app.models import Engineer, Job, Scenario


@pytest.fixture
def greedy_trap() -> Scenario:
    """Two engineers, two jobs. Greedy serves the critical job first with the nearby
    engineer E-A, which leaves the tight tool-down J2 with nobody who can reach
    it in time. A global or regret view sends the far engineer E-B to J1 instead."""
    return Scenario(
        engineers=[
            Engineer(id="E-A", name="Near", x=0, y=0, skills={"etch": 2}),
            Engineer(id="E-B", name="Far", x=3000, y=0, skills={"etch": 2}),
        ],
        jobs=[
            Job(id="J1", x=100, y=0, skill="etch", priority=3, earliest=0, latest=60, duration=60),
            Job(id="J2", x=0, y=50, skill="etch", priority=2, earliest=0, latest=5, duration=60),
        ],
    )
