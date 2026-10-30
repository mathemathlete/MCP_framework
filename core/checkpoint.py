"""Checkpoints: the events surviving a step, one ROOT file per sample.

    SCRATCH/preselection/<prod>/<version>/<sample>.root
    SCRATCH/selection/<channel>/<prod>/<version>/<sample>.root
        Events            TTree, run/luminosityBlock/event, [weights], [triggers],
                          cand_* = surviving candidates
        cutflow           TH1D: total, then one bin per cut
        cutflow_texts     the cuts that wrote it
        production        <prod>/<version> of the ntuples it comes from
        sumw              TH1D, one bin: sum of weightGenerator over every event read
        n_files           TH1D, one bin: number of ntuples read, checked on reading
        Lumis             data only, TTree run/luminosityBlock: every lumisection read

A sample is a signal grid point (M<m>_Q<q>), a background dataset or a primary dataset
and era of data (core/samples.py). Data has no weight branch: its weights are 1.

coffea workers cannot share a file: they write one file per chunk under
`<step dir>/.chunks/<point>/`, merged by `merge()` once the step is over.
"""

import shutil
from pathlib import Path

import awkward as ak
import numpy as np
import uproot

from .paths import SCRATCH

PRESELECTION = "preselection"
TREE = "Events"
CAND = "cand"
CUTFLOW = "cutflow"
CUTFLOW_TEXTS = "cutflow_texts"
PRODUCTION = "production"
EVENT_BRANCHES = ("run", "luminosityBlock", "event")
GENERATOR_WEIGHT = "weightGenerator"
WEIGHTS = (GENERATOR_WEIGHT, "weightPU")
SUMW = "sumw"
N_FILES = "n_files"
LUMIS = "Lumis"


class CheckpointError(RuntimeError):
    pass


def checkpoint_root(prod, version):
    """The production tag stored in, and checked against, every checkpoint."""
    return f"{prod}/{version}"


def step_dir(step):
    return SCRATCH / PRESELECTION if step == PRESELECTION else SCRATCH / "selection" / step


def point_key(mass, charge):
    return f"M{mass}_Q{charge}"


def sample_file(step, name, production):
    """`production`: <prod>/<version>, see checkpoint_root()."""
    return step_dir(step) / production / f"{name}.root"


def chunk_dir(step):
    return step_dir(step) / ".chunks"


def chunk_name(metadata):
    return f"{Path(metadata['filename']).stem}_{metadata['entrystart']}.root"


def _create_tree(f, data):
    """Always a TTree, even empty: uproot would default to RNTuple."""
    f.mktree(TREE, {k: v.type if isinstance(v, ak.Array) else v.dtype
                    for k, v in data.items()})
    f[TREE].extend(data)


def write_events(path, data):
    """`data`: name -> flat numpy array or jagged record (-> n<name>, <name>_<field>)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with uproot.recreate(path) as f:
        _create_tree(f, data)


def merge(chunks, path, n_total, rows, texts, production, n_files, sumw=None, template=None,
          lumis=None):
    """Chunk files -> the single checkpoint file of a sample, chunks removed.
    `template`: an empty checkpoint giving the branches when no chunk was written.
    `lumis`: data, the (run, luminosityBlock) read."""
    chunks = Path(chunks)
    parts = [read_events(file) for file in sorted(chunks.glob("*.root"))]
    if not parts and template is not None:
        parts = [read_events(template)]
    if not parts:
        raise CheckpointError(f"no chunk under {chunks}: nothing was read")
    events = ak.concatenate(parts) if len(parts) > 1 else parts[0]

    prefix = f"{CAND}_"
    data = {b: ak.to_numpy(events[b]) for b in events.fields
            if b != f"n{CAND}" and not b.startswith(prefix)}
    data[CAND] = ak.zip({b[len(prefix):]: events[b] for b in events.fields
                         if b.startswith(prefix)})
    counts = np.array([n_total, *rows], dtype=float)
    with uproot.recreate(path) as f:
        _create_tree(f, data)
        f[CUTFLOW] = (counts, np.arange(len(counts) + 1, dtype=float))
        f[CUTFLOW_TEXTS] = "\n".join(texts)
        f[PRODUCTION] = production
        f[N_FILES] = (np.array([n_files], dtype=float), np.array([0.0, 1.0]))
        if sumw is not None:
            f[SUMW] = (np.array([sumw], dtype=float), np.array([0.0, 1.0]))
        if lumis is not None:
            runs, blocks = np.array(sorted(lumis), dtype=np.int64).reshape(-1, 2).T
            f.mktree(LUMIS, {"run": np.int64, "luminosityBlock": np.int64})
            f[LUMIS].extend({"run": runs, "luminosityBlock": blocks})
    shutil.rmtree(chunks, ignore_errors=True)


def stored_cutflow(path):
    """-> (n_total, rows, cut texts) as written, whatever the current cuts."""
    with uproot.open(path) as f:
        counts = f[CUTFLOW].values()
        texts = str(f[CUTFLOW_TEXTS]).split("\n")
    return int(counts[0]), [int(n) for n in counts[1:]], texts


def stored_sumw(path):
    """Sum of the generator weights before any cut, None for a checkpoint without it."""
    with uproot.open(path) as f:
        return float(f[SUMW].values()[0]) if SUMW in f else None


def stored_lumis(path):
    """-> (runs, luminosityBlocks) read by a data checkpoint, None for MC."""
    with uproot.open(path) as f:
        if LUMIS not in f:
            return None
        lumis = f[LUMIS].arrays(library="np")
        return lumis["run"], lumis["luminosityBlock"]


def check_production(path, production, n_files=None):
    """Same production and, when both are known, same number of ntuples read: a
    checkpoint written from part of a sample, or before the production grew, fails."""
    if not Path(path).exists():
        raise CheckpointError(f"no checkpoint {path} -- rerun from an earlier step")
    with uproot.open(path) as f:
        stored = str(f[PRODUCTION])
        stored_files = int(f[N_FILES].values()[0]) if N_FILES in f else None
    if stored != production:
        raise CheckpointError(f"{path} comes from {stored}, not {production}")
    if None not in (n_files, stored_files) and stored_files != n_files:
        raise CheckpointError(f"{path} was written from {stored_files} file(s), the sample "
                              f"has {n_files} -- rerun from an earlier step")


def read_cutflow(path, texts, production, n_files=None):
    """-> (n_total, rows). Fails on a missing file, other cuts or another production."""
    check_production(path, production, n_files)
    n_total, rows, stored = stored_cutflow(path)
    if stored != list(texts):
        raise CheckpointError(f"{path} was written with other cuts:\n  {stored}\n"
                              f"now:\n  {list(texts)}")
    return n_total, rows


def read_events(path, filter_name=None):
    with uproot.open(path) as f:
        return f[TREE].arrays(filter_name=filter_name, library="ak")


def weight_branches(events):
    return [b for b in WEIGHTS if b in events.fields]


def event_weights(events):
    """weightGenerator x weightPU of each event, 1 for a branch the checkpoint lacks."""
    weights = np.ones(len(events))
    for branch in WEIGHTS:
        if branch in events.fields:
            weights = weights * ak.to_numpy(events[branch])
    return weights


def read_weighted_ids(path):
    """{(run, lumi, event): weight} of every event of a checkpoint."""
    events = read_events(path, filter_name=[*EVENT_BRANCHES, *WEIGHTS])
    ids = zip(*(ak.to_numpy(events[b]).tolist() for b in EVENT_BRANCHES))
    return dict(zip(ids, event_weights(events).tolist()))


def read_event_ids(path):
    """(run, lumi, event) of every event of a checkpoint, as a set."""
    with uproot.open(path) as f:
        arrays = f[TREE].arrays(EVENT_BRANCHES, library="np")
    return set(zip(*(arrays[b].tolist() for b in EVENT_BRANCHES)))


def reset(directory):
    shutil.rmtree(directory, ignore_errors=True)
    Path(directory).mkdir(parents=True)
