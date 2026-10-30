from pathlib import Path

from .paths import RESULTS, SCRATCH


def data_path(path):
    """results/<x> -> SCRATCH/<x>, where the data files (.root, .json) go; unchanged
    outside results/ (--results elsewhere, e.g. a test)."""
    try:
        return SCRATCH / Path(path).resolve().relative_to(RESULTS)
    except ValueError:
        return Path(path)
