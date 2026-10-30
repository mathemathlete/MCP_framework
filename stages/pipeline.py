"""The stages of the analysis, in order. Each one reads what the stages before it
wrote (checkpoints on the scratch, results/) and writes its own outputs: a run can
start, stop or be restricted to any of them."""

from dataclasses import dataclass
from typing import Callable

from . import preselection, regions, selection
from .control_plots import plots
from .efficiency_map import map as efficiency_map
from .limits import limit


@dataclass(frozen=True)
class Stage:
    """run(samples, args). run=None: not implemented yet. samples=False: reads none.
    data=False: the data samples are left out (blinded)."""

    name: str
    run: Callable | None = None
    samples: bool = True
    data: bool = False

    @property
    def implemented(self):
        return self.run is not None


STAGES = (
    Stage("calibration"),
    Stage("weights"),
    Stage("preselection", preselection.run, data=True),
    Stage("selection", selection.run),
    Stage("efficiency_map", efficiency_map.run),
    Stage("regions", regions.run),
    Stage("control_plots", plots.run, data=True),
    Stage("limits", limit.run, samples=False),
)

STAGE_NAMES = tuple(s.name for s in STAGES)


def select_stages(start=None, stop=None, only=None, skip=None):
    """Ordered subset of STAGES: [start, stop] or `only`, minus `skip`."""
    if only and (start or stop):
        raise ValueError("--only cannot be combined with --from/--to")
    first = STAGE_NAMES.index(start) if start else 0
    last = STAGE_NAMES.index(stop) if stop else len(STAGES) - 1
    if first > last:
        raise ValueError(f"--from {start} comes after --to {stop}")
    chosen = set(only) if only else set(STAGE_NAMES[first:last + 1])
    chosen -= set(skip or ())
    return [s for s in STAGES if s.name in chosen]
