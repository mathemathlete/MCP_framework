"""Efficiency_map checkpoints -> per step and sample: surviving candidates and cutflow.

A step is the preselection, a channel (`selection/<channel>`) or a combination
of channels, rebuilt here as in `efficiency.py`: the first part to fire keeps
the event, with its own candidates.
"""

import json
from dataclasses import dataclass, field, replace

import awkward as ak
import numpy as np

from core import checkpoint, lumi
from core.paths import CONFIG
from core.samples import Sample
from core.selection import ALL_TRIGGERS, CHANNELS, COMBINED, CombinedSelection, Selection
from core.selection.candidates import NO_VALUE, SkimCandidates
from core.selection.selection import TRIGGER_LABEL, most_ionizing

VARIABLES_CONFIG = CONFIG / "variables.json"
PRESELECTION = "preselection"
N_CANDIDATES = "n_candidates"
CUT_LABELS = {cut.text: cut.label for c in CHANNELS.values() for _, cut in c.cuts()}


@dataclass(frozen=True)
class Step:
    name: str
    label: str
    plot_dir: str
    parts: tuple = ()

    @property
    def combined(self):
        return bool(self.parts)

    @property
    def checkpoints(self):
        return self.parts or (self.name,)


@dataclass(frozen=True)
class Variable:
    name: str
    label: str
    bins: int
    range: tuple
    logy: bool = False
    data_mc: "Variable | None" = None


@dataclass
class StepData:
    """One sample after one step. `weights`: generator x pileup per event (1 for data),
    `sumw`: sum of the generator weights before any cut (None for data, or in a
    checkpoint written without them). `triggers`: path -> fired, per event; `lumis`:
    data, the lumisections read (core.lumi.codes)."""

    sample: Sample
    n_total: int
    rows: list
    ylabel: str
    candidates: ak.Array
    ids: np.ndarray
    weights: np.ndarray
    sumw: float | None
    triggers: dict = field(default_factory=dict)
    lumis: np.ndarray | None = None

    @property
    def mass(self):
        return self.sample.mass

    @property
    def charge(self):
        return self.sample.charge

    @property
    def best(self):
        return ak.drop_none(most_ionizing(self.candidates))

    def passing(self, triggers, lumis=None):
        """The events firing any of `triggers`, and in `lumis` if given."""
        keep = np.zeros(len(self.ids), dtype=bool)
        for path in triggers:
            keep |= self.triggers[path]
        if lumis is not None:
            keep &= np.isin(lumi.codes(self.ids[:, 0], self.ids[:, 1]), lumis)
        return self.subset(keep)

    def subset(self, keep):
        return replace(self, candidates=self.candidates[keep], ids=self.ids[keep],
                       weights=self.weights[keep],
                       triggers={p: fired[keep] for p, fired in self.triggers.items()})

    def values(self, variable, all_candidates=False):
        """(values, event weights) to histogram, NO_VALUE (no muon, no tau...) dropped."""
        if variable == N_CANDIDATES:
            return ak.to_numpy(ak.num(self.candidates, axis=1)).astype(float), self.weights
        if all_candidates:
            cand = ak.flatten(self.candidates)
            weights = ak.to_numpy(ak.flatten(
                ak.broadcast_arrays(self.weights, self.candidates[variable])[0]))
        else:
            has_best = ak.to_numpy(ak.num(self.candidates, axis=1) > 0)
            cand, weights = self.best, self.weights[has_best]
        values = ak.to_numpy(cand[variable]).astype(float)
        keep = values != NO_VALUE
        return values[keep], weights[keep]


def steps():
    out = [Step(PRESELECTION, "preselection", "Preselection")]
    out += [Step(n, c.label, c.plot_dir) for n, c in sorted(CHANNELS.items())]
    out += [Step(n, label, plot_dir, parts) for n, (parts, label, plot_dir) in sorted(COMBINED.items())]
    return out


def _variable(name, e, data_mc=None):
    return Variable(name, e.get("label", name), int(e["bins"]), tuple(e["range"]),
                    bool(e.get("logy", False)), data_mc)


def load_variables(path=VARIABLES_CONFIG):
    entries = json.loads(path.read_text())
    return [_variable(name, e, _variable(name, {**e, **e["data_mc"]}) if "data_mc" in e else None)
            for name, e in entries.items()]


def available(step, samples):
    """The samples with a checkpoint for the step (for every part of a combination)."""
    return [s for s in samples
            if all(checkpoint.sample_file(name, s.name, s.production).exists()
                   for name in step.checkpoints)]


def _label(text):
    return TRIGGER_LABEL if text.startswith("trigger:") else CUT_LABELS.get(text, text)


def _read_events(path):
    events = checkpoint.read_events(
        path, filter_name=[*checkpoint.EVENT_BRANCHES, *checkpoint.WEIGHTS, *ALL_TRIGGERS,
                           "cand_*"])
    ids = np.stack([ak.to_numpy(events[b]) for b in checkpoint.EVENT_BRANCHES], axis=1)
    triggers = {p: ak.to_numpy(events[p]).astype(bool) for p in ALL_TRIGGERS
                if p in events.fields}
    return SkimCandidates().build(events), ids, checkpoint.event_weights(events), triggers


def _load_single(name, sample):
    path = checkpoint.sample_file(name, sample.name, sample.production)
    checkpoint.check_production(path, sample.production, len(sample.files))
    n_total, counts, texts = checkpoint.stored_cutflow(path)
    rows = [(_label(t), n) for t, n in zip(texts, counts)]
    candidates, ids, weights, triggers = _read_events(path)
    lumis = checkpoint.stored_lumis(path)
    return StepData(sample, n_total, rows, Selection.cutflow_ylabel, candidates, ids, weights,
                    checkpoint.stored_sumw(path), triggers,
                    None if lumis is None else lumi.codes(*lumis))


def _load_combined(step, sample):
    parts = [(name, _load_single(name, sample)) for name in step.parts]
    rows = [(name, len(d.ids)) for name, d in parts]
    taken, kept = set(), []
    for name, d in parts:
        keep = np.array([i not in taken for i in map(tuple, d.ids.tolist())], dtype=bool)
        rows.append((f"{name} kept", int(keep.sum())))
        taken.update(map(tuple, d.ids[keep].tolist()))
        kept.append((d.candidates[keep], d.ids[keep], d.weights[keep]))
    rows.append(("combined", len(taken)))
    first = parts[0][1]
    return StepData(sample, first.n_total, rows, CombinedSelection.cutflow_ylabel,
                    ak.concatenate([c for c, _, _ in kept]),
                    np.concatenate([i for _, i, _ in kept]),
                    np.concatenate([w for _, _, w in kept]), first.sumw)


def merge_data(members):
    """Data of several primary datasets -> one StepData, each event once."""
    first = members[0]
    ids = np.concatenate([d.ids for d in members])
    _, unique = np.unique(ids, axis=0, return_index=True)
    keep = np.sort(unique)
    merged = replace(first, ids=ids,
                     candidates=ak.concatenate([d.candidates for d in members]),
                     weights=np.concatenate([d.weights for d in members]),
                     triggers={p: np.concatenate([d.triggers[p] for d in members])
                               for p in first.triggers},
                     n_total=sum(d.n_total for d in members))
    return merged.subset(keep)


def load(step, sample):
    if step.combined:
        return _load_combined(step, sample)
    return _load_single(step.name, sample)
