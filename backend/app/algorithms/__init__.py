"""The strategy registry. Heavy solvers (SciPy for Hungarian, PyVRP) are imported on first use,
not at startup: on serverless every cold instance pays for its imports, and most requests
(sign-in, metadata, cached plans) never solve anything."""

from collections.abc import Callable
from importlib import import_module

from ..planner import Planner
from .alns import run_alns
from .base import Decision
from .greedy import run_greedy
from .regret import run_regret

Algorithm = Callable[[Planner], dict[str, Decision]]


def _lazy(module: str, name: str) -> Algorithm:
    """A runner that imports ``module`` the first time it's called."""

    def run(p: Planner, *args, **kwargs) -> dict[str, Decision]:
        return getattr(import_module(f"{__name__}.{module}"), name)(p, *args, **kwargs)

    run.__name__ = run.__qualname__ = name
    return run


ALGORITHMS: dict[str, tuple[str, Algorithm]] = {
    "greedy": ("Greedy (priority, then deadline)", run_greedy),
    "hungarian": ("Hungarian (batch rounds)", _lazy("hungarian", "run_hungarian")),
    "regret": ("Regret-2 insertion", run_regret),
    "alns": ("ALNS (adaptive large neighbourhood search)", run_alns),
    "pyvrp": ("PyVRP iterated local search", _lazy("pyvrp_ils", "run_pyvrp")),
}

__all__ = ["ALGORITHMS", "Algorithm", "Decision"]
