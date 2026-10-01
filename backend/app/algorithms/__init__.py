from collections.abc import Callable

from ..planner import Planner
from .alns import run_alns
from .base import Decision
from .greedy import run_greedy
from .hungarian import run_hungarian
from .pyvrp_ils import run_pyvrp
from .regret import run_regret

Algorithm = Callable[[Planner], dict[str, Decision]]

ALGORITHMS: dict[str, tuple[str, Algorithm]] = {
    "greedy": ("Greedy (priority, then deadline)", run_greedy),
    "hungarian": ("Hungarian (batch rounds)", run_hungarian),
    "regret": ("Regret-2 insertion", run_regret),
    "alns": ("ALNS (adaptive large neighbourhood search)", run_alns),
    "pyvrp": ("PyVRP iterated local search", run_pyvrp),
}

__all__ = ["ALGORITHMS", "Algorithm", "Decision"]
