"""Grid points -> ntuple URLs, from the CRAB production catalog.

The ntuples stay on the T2_FR_IPHC SE and are read over xrootd; nothing is
downloaded. `files.txt` is written by `production/submit_crab_production.sh
--catalog`, which resolves CRAB's unpredictable <timestamp> level.
"""

import re
import subprocess

from ..paths import PRODUCTION

SUBMIT = PRODUCTION / "submit_crab_production.sh"

MASSES = [100, 200, 300, 400, 500, 600, 700, 800, 900,
          1000, 1200, 1400, 1600, 1800, 2000, 2400]
CHARGES = [1, 2, 3, 4, 5, 6, 7, 8, 9]

# .../MCP_spin0p5/Q-<charge>e/M-<mass>/<primaryDataset>/<tag>/<timestamp>/0000/*.root
POINT_RE = re.compile(r"/Q-(\d+)e/M-(\d+)/")
# .../<primaryDataset>/<tag>/<timestamp>/0000/output_<n>.root
DATASET_RE = re.compile(r"/([^/]+)/[^/]+/\d{6}_\d{6}/\d{4}/[^/]+\.root$")
# .../data/Run<year><era>/<primaryDataset>/<tag>/...
DATA_RE = re.compile(r"/data/(Run\d{4}[A-Z])/([^/]+)/")


def latest_version(prod):
    versions = [p.name for p in (PRODUCTION / "logs" / prod).glob("v*") if p.is_dir()]
    if not versions:
        raise FileNotFoundError(f"no version of '{prod}' under {PRODUCTION}/logs")
    return max(versions, key=lambda v: int(v[1:]))


def rescan(prod, version):
    """Re-run the SE scan, rewriting files.txt and catalog.csv."""
    subprocess.run([str(SUBMIT), "-p", prod, "-v", version, "--catalog"], check=True)


def files(prod, version=None, rescan_first=False):
    """-> [xrootd url, ...] of a production, from its files.txt."""
    version = version or latest_version(prod)
    listing = PRODUCTION / "logs" / prod / version / "files.txt"

    if rescan_first or not listing.exists():
        rescan(prod, version)
    if not listing.exists():
        raise FileNotFoundError(
            f"{listing} missing: run {SUBMIT.name} -p {prod} -v {version} --catalog")
    return [url for line in listing.read_text().splitlines() if (url := line.strip())]


def grid(prod, version=None, rescan_first=False):
    """-> {(mass_gev, charge_e): [xrootd url, ...]}"""
    return by_point(files(prod, version, rescan_first))


def by_point(urls):
    points = {}
    for url in urls:
        if match := POINT_RE.search(url):
            charge, mass = int(match.group(1)), int(match.group(2))
            points.setdefault((mass, charge), []).append(url)
    return points


def by_dataset(urls):
    """-> {primary dataset: [xrootd url, ...]}"""
    datasets = {}
    for url in urls:
        if match := DATASET_RE.search(url):
            datasets.setdefault(match.group(1), []).append(url)
    return datasets


def by_era(urls):
    """-> {<primary dataset>_<era>: [xrootd url, ...]}, data only."""
    samples = {}
    for url in urls:
        if match := DATA_RE.search(url):
            era, dataset = match.groups()
            samples.setdefault(f"{dataset}_{era}", []).append(url)
    return samples


def select(points, masses=None, charges=None):
    return {(m, q): urls for (m, q), urls in points.items()
            if (masses is None or m in masses) and (charges is None or q in charges)}


def summary(points):
    masses = sorted({m for m, _ in points})
    charges = sorted({q for _, q in points})
    n_files = sum(len(u) for u in points.values())
    return (f"{len(points)} point(s), {n_files} file(s) | "
            f"M = {masses[0]}..{masses[-1]} ({len(masses)}) | "
            f"Q = {charges[0]}e..{charges[-1]}e ({len(charges)})")
