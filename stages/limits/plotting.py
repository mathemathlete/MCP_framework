import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm

from core.plotting import apply_cms_style, cms_label  # noqa: F401
from core.plotting import save as _save

ATLAS_RUN2 = ([1060, 1390, 1520, 1590, 1600, 1570], [2, 3, 4, 5, 6, 7])

MAX_DECADES = 8


def _decade_ticks(bar, zmin, zmax):
    lo, hi = int(np.ceil(np.log10(zmin))), int(np.floor(np.log10(zmax)))
    decades = [10.0 ** k for k in range(lo, hi + 1)]
    bar.set_ticks(decades)
    bar.set_ticklabels([f"$10^{{{k}}}$" for k in range(lo, hi + 1)])


def plot_exclusion(scan, outpath, atlas=True):
    grid = scan.interpolate()
    if grid is None:
        print(f"[warn] {scan.key}: fewer than 3 measured points, no contour")
        return None
    X, Y, Z = grid

    zmax = np.nanmax(Z)
    zmin = max(np.nanmin(Z), zmax * 10.0 ** -MAX_DECADES)
    levels = np.logspace(np.log10(zmin), np.log10(zmax), 200)

    fig, ax = plt.subplots(figsize=(14, 8.5))
    filled = ax.contourf(X, Y, Z, levels=levels, norm=LogNorm(vmin=zmin, vmax=zmax),
                         cmap="viridis", extend="both")
    filled.set_edgecolor("face")
    bar = fig.colorbar(filled, ax=ax, pad=0.02)
    bar.set_label(r"$r = N_{95} / N_{\mathrm{pred}}$")
    _decade_ticks(bar, zmin, zmax)

    if zmin < 1.0 < zmax:
        line = ax.contour(X, Y, Z, levels=[1.0], colors="black", linewidths=3)
        ax.clabel(line, fmt="r = 1", fontsize=13)

    x, y, _ = scan.measured()
    ax.scatter(x, y, s=22, color="white", edgecolor="black", linewidth=0.6,
               zorder=3, label="grid points")
    x0, y0 = scan.empty()
    if len(x0):
        ax.scatter(x0, y0, s=34, marker="x", color="crimson", linewidth=1.4,
                   zorder=3, label="no selected event")

    if atlas:
        ax.plot(*ATLAS_RUN2, color="red", linewidth=2.5, label="ATLAS Run 2 limit")

    ax.set_xlabel("mass [GeV]")
    ax.set_ylabel("charge [e]")
    ax.legend(loc="upper left", fontsize=11, framealpha=0.9)
    ax.text(0.0, -0.12, scan.label, transform=ax.transAxes, ha="left", va="top",
            fontsize=13)
    cms_label(ax, "Projection", data=False, rlabel=scan.lumi_label)
    return _save(fig, outpath)


def _charge_colors(charges, cmap="plasma"):
    return plt.get_cmap(cmap)(np.linspace(0, 0.88, len(charges)))


def plot_xsec_vs_mass(cross_sections, charges, outpath):
    fig, ax = plt.subplots(figsize=(12, 8))
    for color, charge in zip(_charge_colors(charges), charges):
        mass, sigma, _ = cross_sections.at_charge(charge)
        ax.plot(mass, sigma * 1000, "o-", color=color, markersize=5, linewidth=1.5,
                label=f"Q = {charge:.0f}e")

    ax.set_yscale("log")
    ax.set_xlabel("mass [GeV]")
    ax.set_ylabel(r"$\sigma$ [fb]")
    ax.legend(loc="upper right", fontsize=11, ncol=2)
    ax.text(0.03, 0.06, f"HECO pair production, {cross_sections.label}",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=14)
    cms_label(ax, "", data=False, rlabel=f"({cross_sections.sqrt_s} TeV)")
    return _save(fig, outpath)


def plot_xsec_by_charge(cross_sections, charges, outpath, ncols=3):
    nrows = int(np.ceil(len(charges) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 4.5 * nrows),
                             sharex=True)
    axes = np.atleast_1d(axes).flatten()

    for index, (ax, color, charge) in enumerate(
            zip(axes, _charge_colors(charges), charges)):
        mass, sigma, unc = cross_sections.at_charge(charge)
        ax.errorbar(mass, sigma, yerr=unc, fmt="o-", color=color, markersize=5,
                    capsize=3, linewidth=1.5)
        ax.set_yscale("log")
        if index >= len(charges) - ncols:
            ax.set_xlabel("mass [GeV]")
        ax.set_ylabel(r"$\sigma$ [pb]")
        ax.text(0.95, 0.94, f"Q = {charge:.0f}e", transform=ax.transAxes,
                ha="right", va="top", fontsize=15)
        ax.grid(True, alpha=0.3, which="both")

    for ax in axes[len(charges):]:
        ax.set_visible(False)

    fig.suptitle(f"HECO pair production, {cross_sections.label} "
                 f"({cross_sections.sqrt_s} TeV)", fontsize=17)
    fig.tight_layout()
    return _save(fig, outpath)
