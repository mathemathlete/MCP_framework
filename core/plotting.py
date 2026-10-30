"""CMS style from `coffea/plot_style.py`, shared by every analysis."""

import sys
from pathlib import Path

import matplotlib.pyplot as plt

from .paths import COFFEA

sys.path.insert(0, str(COFFEA))
from plot_style import apply_cms_style, cms_label  # noqa: E402,F401


def save(fig, outpath):
    outpath = Path(outpath)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(outpath, bbox_inches="tight")
    plt.close(fig)
    print(f"[ok] {outpath}")
    return outpath
