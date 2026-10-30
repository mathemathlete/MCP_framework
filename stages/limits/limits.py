from pathlib import Path

import hist
import numpy as np
import uproot
from scipy.interpolate import LinearNDInterpolator

from core import cross_sections as xsec_module
from core.paths import RESULTS
from core.scratch import data_path
from core.selection import SELECTIONS, get_selection  # noqa: F401


N_SIGNAL_95 = 2.3
N_EVENTS_68 = 1.14

LUMINOSITIES = xsec_module.LUMINOSITIES

MAPS_DIR = data_path(RESULTS / "efficiency_map")


def map_file(channel, maps_dir=MAPS_DIR):
    """`<plot_dir>/map.root` of the efficiency_map stage, or a flat directory of maps."""
    maps_dir = Path(maps_dir)
    selection = get_selection(channel)
    names = (f"{selection.channel.plot_dir or channel}/map.root",
             f"map_{selection.key}.root",
             f"map_{channel}.root",
             f"map_{channel}_trg.root")
    for name in names:
        if (maps_dir / name).exists():
            return maps_dir / name
    raise FileNotFoundError(f"no map for '{channel}' in {maps_dir}, tried {names}")


def read_map(path):
    with uproot.open(path) as f:
        efficiency = f["efficacity_Comb"]
        initial = f["initial"].values()
        mass_edges = efficiency.axis(0).edges()
        charge_edges = efficiency.axis(1).edges()
        return mass_edges, charge_edges, efficiency.values(), initial


class Scan:
    def __init__(self, channel, cross_sections, lumi, lumi_key, mass_edges,
                 charge_edges, efficiency, initial, source):
        self.channel = channel
        self.cross_sections = cross_sections
        self.lumi = lumi
        self.lumi_key = lumi_key
        self.mass_edges = mass_edges
        self.charge_edges = charge_edges
        self.efficiency = efficiency
        self.initial = initial
        self.source = source

        # grid values are the bin left edges, both in the reference maps and in efficiency_map
        self.masses = mass_edges[:-1]
        self.charges = charge_edges[:-1]
        self.xsec = cross_sections.on_grid(self.masses, self.charges)

        self.n_pred = efficiency * self.xsec * lumi * 1000
        with np.errstate(divide="ignore", invalid="ignore"):
            self.r = np.where(self.n_pred > 0, N_SIGNAL_95 / self.n_pred, np.inf)
            self.r_lower = np.where(
                (efficiency == 0) & (initial > 0),
                N_SIGNAL_95 / (N_EVENTS_68 / np.maximum(initial, 1)
                               * self.xsec * lumi * 1000),
                np.nan)
        self.r[~np.isfinite(self.xsec)] = np.nan

    @property
    def key(self):
        return f"{self.channel}_{self.cross_sections.key}_{self.lumi_key}"

    @property
    def label(self):
        selection = get_selection(self.channel)
        return f"{selection.channel.label}, {self.cross_sections.label}"

    @property
    def plot_dir(self):
        selection = get_selection(self.channel)
        return selection.channel.plot_dir or self.channel

    @property
    def lumi_label(self):
        return f"{self.lumi:g} fb$^{{-1}}$ ({self.cross_sections.sqrt_s} TeV)"

    def _points(self, mask):
        i, j = np.nonzero(mask)
        return self.masses[i], self.charges[j], i, j

    def measured(self):
        mask = np.isfinite(self.r) & (self.r > 0)
        x, y, i, j = self._points(mask)
        return x, y, self.r[i, j]

    def empty(self):
        """Sample present, no selected event: r is only bounded from below."""
        mask = (self.efficiency == 0) & (self.initial > 0) & np.isfinite(self.xsec)
        x, y, _, _ = self._points(mask)
        return x, y

    def interpolate(self, n_mass=800, n_charge=400):
        x, y, r = self.measured()
        if len(x) < 3:
            return None
        interp = LinearNDInterpolator(np.column_stack((x, y)), np.log10(r),
                                      fill_value=np.nan)
        grid_x = np.linspace(x.min(), x.max(), n_mass)
        grid_y = np.linspace(y.min(), y.max(), n_charge)
        X, Y = np.meshgrid(grid_x, grid_y)
        return X, Y, 10 ** interp(X, Y)

    def reach(self):
        """Per charge, the largest mass with r < 1, log-linear between points."""
        out = []
        for j, charge in enumerate(self.charges):
            r = self.r[:, j]
            ok = np.isfinite(r) & (r > 0)
            masses, values = self.masses[ok], np.log10(r[ok])
            if not len(masses) or values[0] >= 0:
                out.append((charge, None))
                continue
            crossing = masses[-1] if values[-1] < 0 else None
            for a, b in zip(range(len(masses) - 1), range(1, len(masses))):
                if values[a] < 0 <= values[b]:
                    crossing = masses[a] + (masses[b] - masses[a]) * (
                        -values[a] / (values[b] - values[a]))
            out.append((charge, crossing))
        return out

    def table(self):
        lines = [f"{'Q [e]':>6} {'excluded up to [GeV]':>22}"]
        for charge, mass in self.reach():
            if mass is None:
                lines.append(f"{charge:6.0f} {'--':>22}")
            elif mass >= self.masses[-1]:
                lines.append(f"{charge:6.0f} {'> ' + str(int(mass)):>22}")
            else:
                lines.append(f"{charge:6.0f} {mass:22.0f}")
        return "\n".join(lines)

    def _hist(self, values):
        axes = (hist.axis.Variable(self.mass_edges, name="mass", label="mass [GeV]"),
                hist.axis.Variable(self.charge_edges, name="charge",
                                   label="charge [e]"))
        h = hist.Hist(*axes, storage=hist.storage.Double())
        h.view()[:] = np.nan_to_num(values, nan=0.0, posinf=0.0)
        return h

    def write(self, outpath):
        outpath = Path(outpath)
        outpath.parent.mkdir(parents=True, exist_ok=True)
        with uproot.recreate(outpath) as f:
            f["N_pred"] = self._hist(self.n_pred)
            f["r"] = self._hist(self.r)
        print(f"[ok] {outpath}")
        return outpath


def scan(channel, spin, lumi_key, maps_dir=MAPS_DIR, lumi=None):
    path = map_file(channel, maps_dir)
    mass_edges, charge_edges, efficiency, initial = read_map(path)
    return Scan(channel, xsec_module.SPINS[spin],
                LUMINOSITIES[lumi_key] if lumi is None else lumi,
                lumi_key, mass_edges, charge_edges, efficiency, initial, path)
