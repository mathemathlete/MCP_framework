"""Efficiency maps, cutflows and background yields, read off the selection checkpoints.

Map definition, unchanged from `limit_test/data/map_muon_trg.root`:

    efficacity_Comb[m][q] = N(events with >= 1 selected candidate
                              [+ trigger if the channel applies one])
                            / N(ntuple entries)
    initial[m][q]         = N(ntuple entries)

Binning covers the whole produced grid: 16 masses x 9 charges. The reference map
stopped at 9 x 8, dropping Q-27 (9e) into overflow; `limit_test/scripts/extrap.py`
reads the edges off the histogram, so the wider binning stays compatible.
"""

import json
from pathlib import Path

import hist
import numpy as np
import uproot

from core import checkpoint
from core.datasets.catalog import CHARGES, MASSES
from core.selection import CombinedSelection

from ..selection import selection_texts

# upper edges of the last mass and charge bins: 2400 -> 2800 GeV, 9 -> 10e on the nominal grid
LAST_MASS_WIDTH = 400
LAST_CHARGE_WIDTH = 1


class Point:
    """One grid point: (mass, charge in e) -> efficiency."""

    __slots__ = ("mass", "charge", "n_total", "n_pass")

    def __init__(self, mass, charge, n_total, n_pass):
        self.mass = mass
        self.charge = charge
        self.n_total = n_total
        self.n_pass = n_pass

    @property
    def efficiency(self):
        return self.n_pass / self.n_total if self.n_total else 0.0

    @property
    def error(self):
        if not self.n_total:
            return 0.0
        eff = self.efficiency
        return np.sqrt(eff * (1 - eff) / self.n_total)

    @property
    def upper_limit(self):
        """68% CL upper limit, for points measured at 0 (Poisson)."""
        return 1.14 / self.n_total if self.n_total else np.nan

    def as_dict(self):
        return {"mass": self.mass, "charge": self.charge,
                "n_total": self.n_total, "n_pass": self.n_pass}


class EfficiencyMap:
    def __init__(self, key, label, channel_label, points):
        self.key = key
        self.label = label
        self.channel_label = channel_label
        self.points = {(p.mass, p.charge): p for p in points}

    def __len__(self):
        return len(self.points)

    def __bool__(self):
        return bool(self.points)

    def get(self, mass, charge):
        return self.points.get((mass, charge))

    def merged_with(self, older):
        """Keep the points of `older` that this run did not recompute."""
        self.points = {**older.points, **self.points}
        return self

    @property
    def masses(self):
        return sorted({m for m, _ in self.points})

    @property
    def charges(self):
        return sorted({q for _, q in self.points})

    @property
    def grid_masses(self):
        """The nominal grid (catalog.MASSES), extended to the masses of the map."""
        return sorted(set(MASSES) | set(self.masses))

    @property
    def grid_charges(self):
        return sorted(set(CHARGES) | set(self.charges))

    def edges(self):
        masses, charges = self.grid_masses, self.grid_charges
        return ([float(m) for m in masses] + [float(masses[-1] + LAST_MASS_WIDTH)],
                [float(q) for q in charges] + [float(charges[-1] + LAST_CHARGE_WIDTH)])

    def at_mass(self, mass):
        return [p for _, p in sorted(((p.charge, p) for p in self.points.values()
                                      if p.mass == mass))]

    def at_charge(self, charge):
        return [p for _, p in sorted(((p.mass, p) for p in self.points.values()
                                      if p.charge == charge))]

    def table(self):
        lines = [f"{'M [GeV]':>8} {'Q [e]':>6} {'N total':>9} {'N sel':>7} {'eff':>20}"]
        for key in sorted(self.points):
            p = self.points[key]
            lines.append(f"{p.mass:8d} {p.charge:6d} {p.n_total:9d} {p.n_pass:7d} "
                         f"{p.efficiency:9.5f} +/- {p.error:.5f}")
        return "\n".join(lines)

    def to_hists(self):
        mass_edges, charge_edges = self.edges()
        axes = (
            hist.axis.Variable(mass_edges, name="mass", label="mass [GeV]"),
            hist.axis.Variable(charge_edges, name="charge", label="charge [e]"),
        )
        h_eff = hist.Hist(*axes, storage=hist.storage.Double())
        h_initial = hist.Hist(*axes, storage=hist.storage.Double())

        for p in self.points.values():
            h_eff.fill(mass=p.mass, charge=p.charge, weight=p.efficiency)
            h_initial.fill(mass=p.mass, charge=p.charge, weight=p.n_total)

        return h_eff, h_initial

    def write(self, outpath):
        h_eff, h_initial = self.to_hists()
        outpath = Path(outpath)
        outpath.parent.mkdir(parents=True, exist_ok=True)
        with uproot.recreate(outpath) as f:
            f["efficacity_Comb"] = h_eff
            f["initial"] = h_initial
        print(f"[ok] {outpath}")
        return outpath

    def as_dict(self):
        return {"key": self.key, "label": self.label,
                "channel_label": self.channel_label,
                "points": [p.as_dict() for p in self.points.values()]}

    @classmethod
    def from_dict(cls, data):
        return cls(data["key"], data["label"], data["channel_label"],
                   [Point(**p) for p in data["points"]])


class Cutflow:
    def __init__(self, key, label, mass, charge, n_total, rows,
                 ylabel="Cumulative efficiency"):
        self.key = key
        self.label = label
        self.mass = mass
        self.charge = charge
        self.n_total = n_total
        self.rows = rows
        self.ylabel = ylabel

    @property
    def labels(self):
        return [label for label, _ in self.rows]

    @property
    def efficiencies(self):
        return [n / self.n_total if self.n_total else 0.0 for _, n in self.rows]

    def table(self):
        lines = [f"{'cut':<26} {'N evt >=1 cand':>14} {'cumulative eff':>15}"]
        for label, n in self.rows:
            lines.append(f"{label:<26} {n:>14d} "
                         f"{n / self.n_total if self.n_total else 0:>15.5f}")
        return "\n".join(lines)

    def as_dict(self):
        return {"key": self.key, "label": self.label, "mass": self.mass,
                "charge": self.charge, "n_total": self.n_total, "rows": self.rows,
                "ylabel": self.ylabel}

    @classmethod
    def from_dict(cls, data):
        return cls(data["key"], data["label"], data["mass"], data["charge"],
                   data["n_total"], [tuple(r) for r in data["rows"]],
                   data.get("ylabel", "Cumulative efficiency"))


def read_selection(selection, samples, cutflow_mass=None):
    """Selection checkpoint(s) of the signal samples
    -> (EfficiencyMap, [Cutflow at cutflow_mass])."""
    if isinstance(selection, CombinedSelection):
        return _read_combined(selection, samples, cutflow_mass)

    step, texts = selection.channel.name, selection_texts(selection)
    grid_points, cutflows = [], []
    for sample in sorted(samples, key=lambda s: (s.mass, s.charge)):
        n_total, rows = checkpoint.read_cutflow(
            checkpoint.sample_file(step, sample.name, sample.production), texts,
            sample.production, len(sample.files))
        grid_points.append(Point(sample.mass, sample.charge, n_total, rows[-1]))
        if sample.mass == cutflow_mass:
            cutflows.append(Cutflow(selection.key, selection.label, sample.mass, sample.charge,
                                    n_total, list(zip(selection.cut_labels(), rows)),
                                    selection.cutflow_ylabel))
    return EfficiencyMap(selection.key, selection.label, selection.channel.label,
                         grid_points), cutflows


def _read_combined(selection, samples, cutflow_mass):
    """OR of the parts on (run, lumi, event); the first part to fire keeps the event."""
    grid_points, cutflows = [], []
    for sample in sorted(samples, key=lambda s: (s.mass, s.charge)):
        parts = []
        for part in selection.selections:
            path = checkpoint.sample_file(part.channel.name, sample.name, sample.production)
            n_total, _ = checkpoint.read_cutflow(path, selection_texts(part), sample.production,
                                                 len(sample.files))
            parts.append((part.channel.name, checkpoint.read_event_ids(path)))

        rows = [(name, len(ids)) for name, ids in parts]
        taken = set()
        for name, ids in parts:
            rows.append((f"{name} kept", len(ids - taken)))
            taken |= ids
        rows.append(("combined", len(taken)))

        grid_points.append(Point(sample.mass, sample.charge, n_total, len(taken)))
        if sample.mass == cutflow_mass:
            cutflows.append(Cutflow(selection.key, selection.label, sample.mass, sample.charge,
                                    n_total, rows, selection.cutflow_ylabel))
    return EfficiencyMap(selection.key, selection.label, selection.channel.label,
                         grid_points), cutflows


class Yield:
    """One background sample after a selection, raw and weighted (generator x pileup)."""

    __slots__ = ("sample", "group", "label", "xsec", "n_total", "n_pass", "sumw", "sumw_pass")

    def __init__(self, sample, group, label, xsec, n_total, n_pass, sumw, sumw_pass):
        self.sample = sample
        self.group = group
        self.label = label
        self.xsec = xsec
        self.n_total = n_total
        self.n_pass = n_pass
        self.sumw = sumw
        self.sumw_pass = sumw_pass

    def expected(self, lumi):
        """Events expected for `lumi` fb^-1, xsec in pb."""
        return self.xsec * lumi * 1000 * self.sumw_pass / self.sumw if self.sumw else 0.0

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


def read_yields(selection, samples):
    """Selection checkpoint(s) of the background samples -> [Yield]."""
    parts = selection.selections if isinstance(selection, CombinedSelection) else [selection]
    yields = []
    for sample in samples:
        weights = {}
        for part in parts:
            path = checkpoint.sample_file(part.channel.name, sample.name, sample.production)
            n_total, _ = checkpoint.read_cutflow(path, selection_texts(part), sample.production,
                                                 len(sample.files))
            weights.update(checkpoint.read_weighted_ids(path))
        sumw = checkpoint.stored_sumw(path)
        if sumw is None:
            raise checkpoint.CheckpointError(f"{path} has no sum of weights, rerun the "
                                             "preselection")
        yields.append(Yield(sample.name, sample.group, sample.label, sample.xsec, n_total,
                            len(weights), sumw, float(sum(weights.values()))))
    return yields


def yields_table(yields, lumi):
    lines = [f"expected events for {lumi:g} fb^-1 (xsec x lumi x sum w selected / sum w)",
             f"{'sample':<60} {'N total':>11} {'N sel':>9} {'xsec [pb]':>11} {'expected':>12}"]
    for group in dict.fromkeys(y.group for y in yields):
        members = [y for y in yields if y.group == group]
        for y in members:
            lines.append(f"{y.sample:<60} {y.n_total:>11d} {y.n_pass:>9d} {y.xsec:>11.4g} "
                         f"{y.expected(lumi):>12.4g}")
        total = sum(y.expected(lumi) for y in members)
        lines.append(f"{'= ' + members[0].label:<60} {sum(y.n_total for y in members):>11d} "
                     f"{sum(y.n_pass for y in members):>9d} {'':>11} {total:>12.4g}")
    return "\n".join(lines)


def save_yields(path, yields):
    """{selection key: [Yield]} merged sample by sample into the JSON at `path`."""
    path = Path(path)
    stored = load_yields(path) if path.exists() else {}
    for key, new in yields.items():
        by_sample = {y.sample: y for y in stored.get(key, [])}
        by_sample.update({y.sample: y for y in new})
        stored[key] = list(by_sample.values())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: [y.as_dict() for y in v] for k, v in stored.items()},
                               indent=2))
    print(f"[ok] {path}")
    return stored


def load_yields(path):
    return {k: [Yield.from_dict(y) for y in v]
            for k, v in json.loads(Path(path).read_text()).items()}


def save_cache(path, maps, cutflows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "maps": {key: m.as_dict() for key, m in maps.items()},
        "cutflows": {key: [c.as_dict() for c in cfs] for key, cfs in cutflows.items()},
    }, indent=2))
    print(f"[ok] {path}")


def load_cache(path):
    payload = json.loads(Path(path).read_text())
    maps = {k: EfficiencyMap.from_dict(v) for k, v in payload["maps"].items()}
    cutflows = {k: [Cutflow.from_dict(c) for c in v]
                for k, v in payload["cutflows"].items()}
    return maps, cutflows
