"""Plot of the 2D efficiency map (the cutflows are drawn by `control_plots`).

CMS style via `coffea/plot_style.py`, histograms drawn with their own `.plot()`,
PDF output.

A white cell means no sample, a hatched cell a sample with no selected event,
labelled with its 68% CL upper limit.
"""

import hist
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm
from matplotlib.patches import Rectangle

from core.plotting import apply_cms_style, cms_label  # noqa: F401
from core.plotting import save as _save

RLABEL = "MiniAOD 2024 (13.6 TeV)"


def _grid_hists(emap):
    """Efficiency and N-generated on uniform cells, so the labels stay readable.

    The ROOT output keeps the variable binning of the reference map; here the
    mass axis is categorical, otherwise the 100 GeV cells are 4x narrower than
    the 2400 GeV ones and the numbers no longer fit.
    """
    axes = (hist.axis.IntCategory(emap.grid_masses, name="mass", label="mass [GeV]"),
            hist.axis.IntCategory(emap.grid_charges, name="charge", label="charge [e]"))
    h_eff = hist.Hist(*axes, storage=hist.storage.Double())
    h_initial = hist.Hist(*axes, storage=hist.storage.Double())
    for p in emap.points.values():
        h_eff[hist.loc(p.mass), hist.loc(p.charge)] = p.efficiency
        h_initial[hist.loc(p.mass), hist.loc(p.charge)] = p.n_total
    return h_eff, h_initial


def plot_map(emap, outpath):
    h_eff, h_initial = _grid_hists(emap)
    values, initial = h_eff.values(), h_initial.values()

    fig, ax = plt.subplots(figsize=(16, 8))

    nonzero = values[values > 0]
    norm = LogNorm(vmin=nonzero.min(), vmax=nonzero.max()) if nonzero.size else None
    cmap = plt.get_cmap("cividis").copy()
    cmap.set_bad("white")

    art = h_eff.plot2d(ax=ax, cmap=cmap, norm=norm)
    colorbar = getattr(art, "cbar", None) or fig.axes[-1]
    (colorbar.ax if hasattr(colorbar, "ax") else colorbar).set_ylabel("Efficiency")

    vmid = np.sqrt(nonzero.min() * nonzero.max()) if nonzero.size else 0.0
    for i in range(len(emap.grid_masses)):
        for j in range(len(emap.grid_charges)):
            if initial[i, j] <= 0:
                continue
            if values[i, j] > 0:
                ax.text(i + 0.5, j + 0.5, f"{values[i, j]:.3g}", ha="center",
                        va="center", fontsize=9,
                        color="black" if values[i, j] > vmid else "white")
            else:
                ax.add_patch(Rectangle((i, j), 1, 1, facecolor="0.85",
                                       edgecolor="0.5", hatch="///", linewidth=0.8))
                ax.text(i + 0.5, j + 0.5, f"< {1.14 / initial[i, j]:.1g}",
                        ha="center", va="center", fontsize=8)

    ax.text(0.0, -0.13, emap.channel_label, transform=ax.transAxes,
            ha="left", va="top", fontsize=13)
    cms_label(ax, "Preliminary", data=False, rlabel=RLABEL)
    return _save(fig, outpath)
