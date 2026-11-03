"""1D distributions and cutflows: one curve per signal point, the backgrounds stacked
per process (group of the run config). CMS style, PDF output.

Normalisations (`norm`):
    shape       signal curves and the background stack each of unit area
    efficiency  fraction of the generated events; a background process is one dashed
                line, its datasets weighted by their cross sections
    events      expected events for `lumi` fb^-1: xsec x lumi / N generated for the
                signal (unweighted, as the maps), xsec x lumi x w / sum w for the
                backgrounds (w = generator x pileup weight)

Data/MC: the backgrounds stacked for the luminosity of the data (events), the data as
points with their Poisson (Garwood) 68% interval, data/MC below.

Out-of-range values are folded into the first/last bin.
"""

import hist
import matplotlib.pyplot as plt
import mplhep
import numpy as np
from scipy.stats import chi2

from core.plotting import apply_cms_style, cms_label  # noqa: F401
from core.plotting import save as _save

RLABEL = "MiniAOD 2024 (13.6 TeV)"
NORMS = ("shape", "efficiency", "events")
YLABELS = {"shape": "Normalized to unit area", "efficiency": "Fraction of generated events",
           "events": "Events"}
BACKGROUND_COLORS = ("#9ecae1", "#fdae6b", "#a1d99b", "#bcbddc", "#fc9272", "#d9d9d9")


def colors(n):
    return plt.get_cmap("plasma")(np.linspace(0, 0.88, max(n, 1)))


def curve_label(data):
    if not data.sample.is_signal:
        return data.sample.label
    return f"M = {data.mass} GeV, Q = {data.charge}e"


def processes(backgrounds):
    """-> [(label, [StepData])], one per group of the run config, in config order."""
    groups = {}
    for data in backgrounds:
        groups.setdefault(data.sample.group, []).append(data)
    return [(members[0].sample.label, members) for members in groups.values()]


def _histogram(values, variable, weight):
    lo, hi = variable.range
    h = hist.Hist(hist.axis.Regular(variable.bins, lo, hi, label=variable.label),
                  storage=hist.storage.Weight())
    half_bin = 0.5 * (hi - lo) / variable.bins
    h.fill(np.clip(values, lo + half_bin, hi - half_bin), weight=weight)
    return h


def _signal_scale(data, norm, lumi):
    if norm == "efficiency":
        return 1.0 / data.n_total if data.n_total else None
    if norm == "events":
        if data.sample.xsec is None or not data.n_total:
            return None
        return data.sample.xsec * lumi * 1000 / data.n_total
    return 1.0


def _process_hist(members, variable, all_candidates, norm, lumi):
    """Sum of the datasets of a process, each weighted by xsec x lumi / sum w; for
    `efficiency`, divided by the cross section of the whole process."""
    xsec_total = sum(d.sample.xsec for d in members)
    h = _histogram(np.array([]), variable, np.array([]))
    for data in members:
        if not data.sumw:
            continue
        values, weights = data.values(variable.name, all_candidates)
        scale = data.sample.xsec * lumi * 1000 / data.sumw
        if norm == "efficiency":
            scale = data.sample.xsec / data.sumw / xsec_total
        h += _histogram(values, variable, weights * scale)
    return h


def plot_variable(samples, variable, title, outpath, norm="shape", all_candidates=False,
                  backgrounds=(), lumi=None):
    fig, ax = plt.subplots(figsize=(12, 8))
    peaks = []

    stack = [(label, _process_hist(members, variable, all_candidates, norm, lumi))
             for label, members in processes(backgrounds)]
    stack = [(label, h) for label, h in stack if h.sum().value > 0]
    if stack:
        palette = [BACKGROUND_COLORS[i % len(BACKGROUND_COLORS)] for i in range(len(stack))]
        hists = [h for _, h in stack]
        if norm == "shape":
            total = sum(h.sum().value for h in hists)
            hists = [h / total for h in hists]
        if norm == "efficiency":
            for (label, _), h, color in zip(stack, hists, palette):
                h.plot(ax=ax, histtype="step", flow="none", linewidth=2, linestyle="--",
                       color=color, label=label)
                peaks.append(h.values())
        else:
            mplhep.histplot(hists, ax=ax, stack=True, histtype="fill", flow="none",
                            color=palette, label=[label for label, _ in stack])
            peaks.append(sum(h.values() for h in hists))

    for color, data in zip(colors(len(samples)), samples):
        values, _ = data.values(variable.name, all_candidates)
        scale = _signal_scale(data, norm, lumi)
        if not values.size or scale is None:
            continue
        h = _histogram(values, variable, scale)
        if norm == "shape":
            h = h / h.sum().value
        h.plot(ax=ax, histtype="step", yerr=True, flow="none", linewidth=1.5, color=color,
               label=curve_label(data))
        peaks.append(h.values())

    if not peaks:
        plt.close(fig)
        return None
    values = np.concatenate(peaks)
    if variable.logy and (values > 0).any():
        ax.set_yscale("log")
        ax.set_ylim(0.5 * values[values > 0].min(), 50 * values.max())
    else:
        ax.set_ylim(0, 1.4 * values.max())
    ax.set_xlim(*variable.range)
    ax.set_xlabel(variable.label)
    ax.set_ylabel(f"Events / {lumi:g} fb$^{{-1}}$" if norm == "events" else YLABELS[norm])
    ax.legend(loc="upper right", fontsize=12, ncol=2)
    ax.text(0.03, 0.94, title, transform=ax.transAxes, ha="left", va="top", fontsize=14)
    cms_label(ax, "Preliminary", data=False, rlabel=RLABEL)
    return _save(fig, outpath)


def _lumi_label(lumi):
    return f"{lumi:.3g} fb$^{{-1}}$ (13.6 TeV)"


def poisson_errors(counts):
    """-> (down, up) of the 68% Garwood interval around each count."""
    low = np.where(counts > 0, chi2.ppf(0.15865, 2 * counts) / 2, 0.0)
    high = chi2.ppf(0.84135, 2 * (counts + 1)) / 2
    return counts - low, high - counts


def plot_data_mc(data, backgrounds, variable, title, outpath, all_candidates=False, lumi=None):
    stack = [(label, _process_hist(members, variable, all_candidates, "events", lumi))
             for label, members in processes(backgrounds)]
    stack = [(label, h) for label, h in stack if h.sum().value > 0]
    values, _ = data.values(variable.name, all_candidates)
    observed = _histogram(values, variable, np.ones_like(values))
    if not stack and not values.size:
        return None

    fig, (ax, ax_ratio) = plt.subplots(2, 1, figsize=(12, 10), sharex=True,
                                       gridspec_kw={"height_ratios": [3, 1], "hspace": 0.05})
    centers = observed.axes[0].centers
    n_data = observed.values()
    mc = np.zeros_like(n_data)
    if stack:
        palette = [BACKGROUND_COLORS[i % len(BACKGROUND_COLORS)] for i in range(len(stack))]
        mplhep.histplot([h for _, h in stack], ax=ax, stack=True, histtype="fill", flow="none",
                        color=palette, label=[label for label, _ in stack])
        mc = sum(h.values() for _, h in stack)
    shown = n_data > 0
    down, up = poisson_errors(n_data)
    ax.errorbar(centers[shown], n_data[shown], yerr=(down[shown], up[shown]), fmt="o",
                color="black", markersize=4, label="Data")

    peaks = np.concatenate([n_data, mc])
    if variable.logy and (peaks > 0).any():
        ax.set_yscale("log")
        ax.set_ylim(0.5 * peaks[peaks > 0].min(), 50 * peaks.max())
    else:
        ax.set_ylim(0, 1.4 * peaks.max())
    ax.set_xlim(*variable.range)
    ax.set_xlabel("")
    ax.set_ylabel("Events")
    ax.legend(loc="upper right", fontsize=12, ncol=2)
    ax.text(0.03, 0.94, title, transform=ax.transAxes, ha="left", va="top", fontsize=14)
    cms_label(ax, "Preliminary", data=True, rlabel=_lumi_label(lumi))

    with np.errstate(divide="ignore", invalid="ignore"):
        filled = mc > 0
        ratio = np.where(filled & shown, n_data / mc, np.nan)
        ratio_err = (np.where(filled & shown, down / mc, np.nan),
                     np.where(filled & shown, up / mc, np.nan))
    ax_ratio.errorbar(centers, ratio, yerr=ratio_err, fmt="o", color="black", markersize=4)
    ax_ratio.axhline(1, color="0.5", linestyle="--", linewidth=1)
    ax_ratio.set_ylim(0.5, 1.5)
    ax_ratio.set_ylabel("Data / MC")
    ax_ratio.set_xlabel(variable.label)
    return _save(fig, outpath)


def data_mc_table(data, backgrounds, lumi, n_lumis):
    """Expected events per process (stat. error), total MC, data and data/MC."""
    lines = [f"{lumi:.4g} fb^-1 recorded, {n_lumis} lumisections",
             f"{'':<20}{'events':>14}{'stat':>12}"]
    total, variance = 0.0, 0.0
    for label, members in processes(backgrounds):
        scaled = [d.weights * d.sample.xsec * lumi * 1000 / d.sumw for d in members if d.sumw]
        n = float(sum(w.sum() for w in scaled))
        err2 = float(sum((w ** 2).sum() for w in scaled))
        lines.append(f"{label:<20}{n:>14.4g}{np.sqrt(err2):>12.3g}")
        total, variance = total + n, variance + err2
    lines.append(f"{'total MC':<20}{total:>14.4g}{np.sqrt(variance):>12.3g}")
    n_data = len(data.ids)
    lines.append(f"{'data':<20}{n_data:>14d}{np.sqrt(n_data):>12.3g}")
    if total > 0:
        ratio = n_data / total
        error = ratio * np.sqrt(1 / max(n_data, 1) + variance / total ** 2)
        lines.append(f"{'data / MC':<20}{ratio:>14.4g}{error:>12.3g}")
    return "\n".join(lines)


def _step_curve(ax, labels, values, color, label, linestyle="-"):
    h = hist.Hist(hist.axis.StrCategory(labels, name="cut", label=""),
                  storage=hist.storage.Double())
    h[...] = np.asarray(values, dtype=float)
    h.plot(ax=ax, histtype="step", yerr=False, linewidth=1.5, color=color, label=label,
           linestyle=linestyle)
    ax.plot(np.arange(len(labels)) + 0.5, values, "o", markersize=4, color=color)


def _cumulative(members):
    """Cumulative efficiency of each cut, the datasets of a process weighted by xsec."""
    counts = [np.array([n for _, n in d.rows], dtype=float) / d.n_total * (d.sample.xsec or 1)
              for d in members if d.n_total]
    return sum(counts) / sum(d.sample.xsec or 1 for d in members if d.n_total)


def plot_cutflow(samples, title, outpath, relative=True, backgrounds=()):
    """Cumulative efficiency per cut, and below it the efficiency of each cut
    relative to the previous one (`relative`). Backgrounds: one dashed curve per process."""
    samples = [s for s in samples if s.rows]
    curves = [(curve_label(s), [s]) for s in samples] + processes(backgrounds)
    if not curves:
        return None
    labels = [label for label, _ in curves[0][1][0].rows]

    if relative:
        fig, (ax, ax_rel) = plt.subplots(2, 1, figsize=(14, 10), sharex=True,
                                         gridspec_kw={"height_ratios": [2, 1], "hspace": 0.05})
    else:
        fig, ax = plt.subplots(figsize=(14, 8))
    palette = list(colors(len(samples))) + \
        [BACKGROUND_COLORS[i % len(BACKGROUND_COLORS)] for i in range(len(curves) - len(samples))]
    shown = []
    for i, (color, (name, members)) in enumerate(zip(palette, curves)):
        if any([label for label, _ in d.rows] != labels for d in members):
            print(f"[warn] cut labels differ for {name}, skipped")
            continue
        linestyle = "-" if i < len(samples) else "--"
        cumulative = _cumulative(members)
        _step_curve(ax, labels, cumulative, color, name, linestyle)
        shown += [e for e in cumulative if e > 0]
        if relative:
            previous = np.concatenate([[1.0], cumulative[:-1]])
            _step_curve(ax_rel, labels, np.divide(cumulative, previous,
                                                  out=np.zeros_like(cumulative),
                                                  where=previous > 0), color, None, linestyle)

    ax.set_yscale("log")
    ax.set_xlabel("")
    ax.set_ylabel(curves[0][1][0].ylabel)
    if shown:
        ax.set_ylim(0.2 * min(shown), 5 * max(shown))
    ax.legend(loc="upper right", fontsize=12, ncol=2)
    ax.text(0.03, 0.94, title, transform=ax.transAxes, ha="left", va="top", fontsize=14)
    cms_label(ax, "Preliminary", data=False, rlabel=RLABEL)
    bottom = ax
    if relative:
        ax_rel.set_ylim(0, 1.1)
        ax_rel.set_ylabel("Relative eff.")
        ax_rel.axhline(1, color="0.5", linestyle="--", linewidth=1)
        ax_rel.set_xlabel("")
        bottom = ax_rel
    plt.setp(bottom.get_xticklabels(), rotation=45, ha="right", fontsize=12)
    return _save(fig, outpath)


def cutflow_table(samples, backgrounds=()):
    """Cut | N and cumulative efficiency of every signal curve, cumulative efficiency
    of every background process."""
    procs = processes(backgrounds)
    reference = (samples or [members[0] for _, members in procs])[0]
    head = (f"{'cut':<28}" + "".join(f"{curve_label(s):>24}" for s in samples)
            + "".join(f"{label:>24}" for label, _ in procs))
    lines = [head, f"{'total':<28}" + "".join(f"{s.n_total:>24d}" for s in samples)
             + "".join(f"{sum(d.n_total for d in m):>24d}" for _, m in procs)]
    efficiencies = [_cumulative(members) for _, members in procs]
    for i, (label, _) in enumerate(reference.rows):
        cells = []
        for s in samples:
            n = s.rows[i][1] if i < len(s.rows) else 0
            cells.append(f"{n:>11d} ({n / s.n_total if s.n_total else 0:.4f})")
        cells += [f"({eff[i]:.3g})" if i < len(eff) else "" for eff in efficiencies]
        lines.append(f"{label:<28}" + "".join(f"{c:>24}" for c in cells))
    return "\n".join(lines)
