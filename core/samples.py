"""Samples: what a run reads. One per signal grid point or per background dataset.

Built from the `samples` section of a run config (`config/runs/*.yaml`), one
group per entry:

    samples:
      signal:
        production: MCP_spin0p5_Q1to20   CRAB production(s), a name or a list, each at its
                                     latest version (production/logs/<prod>/v<n>/files.txt)
        split: grid                  one sample per grid point, named M<m>_Q<q>
        mass: [1200]                 grid only, default: all
        charge: [1, 4]               grid only, default: all
        xsec: spin0p5                grid: a key of core.cross_sections.SPINS (default)
      DY:
        production: BKG_DY_2024
        split: dataset               one sample per primary dataset, named after it
        match: DYto2Mu               regex on the file URLs, default: every file
        xsec: data/cross_sections/bkg_DY_2024.csv   dataset: CSV relative to framework/
        label: Drell-Yan             legend and tables, default: the group name
      data:
        production: Run2024
        split: data                  one sample per primary dataset and era, Muon0_Run2024C
      one_file:
        files: [root://.../output_1.root]   given files instead of a production,
                                            <prod>/<version> read from their path

`version: v1` pins a single production to a version. A sample (same name) met
twice, in two productions or two groups, is kept from the first one only: listing
[MCP_spin0p5_Q1to20, MCP_spin0p5_M1600_allQ] adds to the first grid the charges it
lacks (24e and 30e at 1600 GeV).
Without a run config, the default is the signal grid alone (`default_groups`);
ntuples given directly are one group of grid points (`files_group`).
"""

import re
from dataclasses import dataclass

from . import cross_sections
from .checkpoint import checkpoint_root, point_key
from .datasets import catalog

GRID = "grid"
DATASET = "dataset"
DATA = "data"
SPLITS = (GRID, DATASET, DATA)
GROUP_KEYS = {"production", "files", "version", "split", "match", "mass", "charge", "xsec",
              "label"}
# .../store/user/<user>/HSCP/<prod>/<version>/...
PRODUCTION_RE = re.compile(r"/HSCP/([^/]+)/(v\d+)/")
DEFAULT_PRODUCTION = "MCP_spin0p5_Q1to20"
DEFAULT_SPIN = "spin0p5"


class SampleError(ValueError):
    pass


@dataclass(frozen=True)
class Sample:
    name: str
    group: str
    label: str
    files: tuple
    production: str
    mass: int | None = None
    charge: int | None = None
    xsec: float | None = None
    is_data: bool = False

    @property
    def is_signal(self):
        return self.mass is not None

    @property
    def is_background(self):
        return not self.is_signal and not self.is_data

    @property
    def primary_dataset(self):
        """Data: <primary dataset>_<era> -> the primary dataset."""
        return self.name.rsplit("_", 1)[0]


def default_groups(production=DEFAULT_PRODUCTION, version=None):
    return {"signal": {"production": production, "version": version, "split": GRID}}


def files_group(files):
    if not all(catalog.POINT_RE.search(f) for f in files):
        raise SampleError("background ntuples need their cross sections: list them in a run "
                          "config (samples.<group>.xsec)")
    return {"ntuples": {"files": list(files), "split": GRID}}


def build(groups, masses=None, charges=None, production=None, version=None, rescan=False):
    """-> {name: Sample}, in config order. masses/charges/production/version, from the
    command line, override those of the grid groups."""
    samples = {}
    for group, entry in groups.items():
        entry = dict(entry or {})
        unknown = set(entry) - GROUP_KEYS
        if unknown:
            raise SampleError(f"samples.{group}: unknown key(s) {sorted(unknown)}, "
                              f"expected {sorted(GROUP_KEYS)}")
        split = entry.get("split", GRID)
        if split not in SPLITS:
            raise SampleError(f"samples.{group}: split '{split}' not in {SPLITS}")
        if split == GRID:
            if production:
                entry["production"] = production
                entry.pop("files", None)
            entry["version"] = version or entry.get("version")
            entry["mass"] = masses or entry.get("mass")
            entry["charge"] = charges or entry.get("charge")
            if not entry.get("production") and not entry.get("files"):
                entry["production"] = DEFAULT_PRODUCTION

        make = {GRID: _grid, DATASET: _datasets, DATA: _data}[split]
        for prod_tag, urls in _sources(group, entry, rescan):
            skipped = []
            for sample in make(group, entry, prod_tag, urls):
                if sample.name in samples:
                    skipped.append(sample.name)
                else:
                    samples[sample.name] = sample
            if skipped:
                print(f"[info] {group}: {len(skipped)} sample(s) of {prod_tag} already taken "
                      f"from an earlier production, skipped: {', '.join(skipped[:5])}"
                      f"{' ...' if len(skipped) > 5 else ''}")
    return samples


def _as_list(value):
    return [value] if isinstance(value, (str, int)) else list(value or [])


def _sources(group, entry, rescan):
    """-> [(<prod>/<version>, [url, ...])], productions first, in config order."""
    productions, files = _as_list(entry.get("production")), _as_list(entry.get("files"))
    if not productions and not files:
        raise SampleError(f"samples.{group}: needs a production or files")
    if entry.get("version") and len(productions) != 1:
        raise SampleError(f"samples.{group}: version needs a single production")

    sources = []
    for prod in productions:
        version = entry.get("version") or catalog.latest_version(prod)
        sources.append((checkpoint_root(prod, version),
                        catalog.files(prod, version, rescan_first=rescan)))
    by_tag = {}
    for url in files:
        match = PRODUCTION_RE.search(url)
        if not match:
            raise SampleError(f"samples.{group}: no /HSCP/<prod>/<version>/ in {url}")
        by_tag.setdefault(checkpoint_root(*match.groups()), []).append(url)
    sources += list(by_tag.items())

    if entry.get("match"):
        pattern = re.compile(entry["match"])
        sources = [(tag, [u for u in urls if pattern.search(u)]) for tag, urls in sources]
    return sources


def _grid(group, entry, production, urls):
    spin = entry.get("xsec", DEFAULT_SPIN)
    if spin not in cross_sections.SPINS:
        raise SampleError(f"samples.{group}: xsec '{spin}' not in {sorted(cross_sections.SPINS)}")
    table = cross_sections.SPINS[spin].table()
    points = catalog.select(catalog.by_point(urls), entry.get("mass"), entry.get("charge"))
    return [Sample(point_key(m, q), group, entry.get("label", group), tuple(files), production,
                   mass=m, charge=q, xsec=table.get((m, float(q))))
            for (m, q), files in sorted(points.items())]


def _datasets(group, entry, production, urls):
    for key in ("mass", "charge"):
        if entry.get(key) is not None:
            raise SampleError(f"samples.{group}: '{key}' needs split: {GRID}")
    if not entry.get("xsec"):
        raise SampleError(f"samples.{group}: split: {DATASET} needs an xsec CSV")
    xsecs = cross_sections.read_background(entry["xsec"])
    datasets = catalog.by_dataset(urls)
    missing = sorted(set(datasets) - set(xsecs))
    if missing:
        raise SampleError(f"samples.{group}: no cross section in {entry['xsec']} for {missing}")
    return [Sample(name, group, entry.get("label", group), tuple(files), production,
                   xsec=xsecs[name])
            for name, files in sorted(datasets.items())]


def _data(group, entry, production, urls):
    for key in ("mass", "charge", "xsec"):
        if entry.get(key) is not None:
            raise SampleError(f"samples.{group}: '{key}' makes no sense for data")
    return [Sample(name, group, entry.get("label", group), tuple(files), production,
                   is_data=True)
            for name, files in sorted(catalog.by_era(urls).items())]


def summary(samples):
    lines = []
    for group in dict.fromkeys(s.group for s in samples.values()):
        members = [s for s in samples.values() if s.group == group]
        n_files = sum(len(s.files) for s in members)
        productions = ", ".join(dict.fromkeys(s.production for s in members))
        lines.append(f"{group}: {len(members)} sample(s), {n_files} file(s), {productions}")
    return "\n".join(lines)
