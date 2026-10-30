"""Raw ntuples over xrootd -> preselection checkpoint, the slow step."""

import shutil

import awkward as ak
import coffea.processor as processor
import numpy as np

from core import checkpoint, executor
from core.selection import ALL_TRIGGERS, PRESELECTION, MiniaodCandidates


class _PreselectionProcessor(processor.ProcessorABC):
    """Raw ntuple -> preselected candidates, one chunk file per coffea chunk. `data`: the
    data samples, written without weights and with the lumisections read."""

    def __init__(self, candidates, cuts, triggers, outdir, data=()):
        self.candidates = candidates
        self.cuts = cuts
        self.triggers = triggers
        self.outdir = outdir
        self.data = set(data)

    def process(self, events):
        name = events.metadata["dataset"]
        cand = self.candidates.build(events)
        mask = ak.ones_like(cand.pt, dtype=bool)
        rows = []
        for cut in self.cuts:
            mask = mask & cut(cand)
            rows.append(int(ak.sum(ak.any(mask, axis=1))))

        is_data = name in self.data
        weights = () if is_data else checkpoint.weight_branches(events)
        kept = ak.to_numpy(ak.any(mask, axis=1))
        data = {b: ak.to_numpy(events[b])[kept]
                for b in (*checkpoint.EVENT_BRANCHES, *weights, *self.triggers)}
        data["cand"] = cand[mask][kept]
        checkpoint.write_events(self.outdir / name / checkpoint.chunk_name(events.metadata), data)
        sumw = (float(ak.sum(events[checkpoint.GENERATOR_WEIGHT]))
                if checkpoint.GENERATOR_WEIGHT in events.fields else float(len(events)))
        out = {"n_total": len(events), "rows": np.array(rows, dtype=np.int64), "sumw": sumw}
        if is_data:
            out["lumis"] = set(zip(ak.to_numpy(events["run"]).tolist(),
                                   ak.to_numpy(events["luminosityBlock"]).tolist()))
        return {name: out}

    def postprocess(self, accumulator):
        return accumulator


def preselection_texts():
    return [cut.text for cut in PRESELECTION] + [f"triggers: {' '.join(ALL_TRIGGERS)}"]


def preselect(samples, workers=executor.DEFAULT_WORKERS, executor_name=executor.DEFAULT_EXECUTOR,
              skip_bad_files=False):
    """`samples`: {name: core.samples.Sample}."""
    step = checkpoint.PRESELECTION
    chunks = checkpoint.chunk_dir(step)
    checkpoint.reset(chunks)
    candidates = MiniaodCandidates()
    print(f"\n=== preselection -> {checkpoint.step_dir(step)} ===")
    results = executor.run({name: list(s.files) for name, s in samples.items()},
                           candidates.tree_name,
                           _PreselectionProcessor(candidates, PRESELECTION, ALL_TRIGGERS, chunks,
                                                  [n for n, s in samples.items() if s.is_data]),
                           workers, executor_name, skip_bad_files)
    for name, sample in samples.items():
        res = results[name]
        checkpoint.merge(chunks / name, checkpoint.sample_file(step, name, sample.production),
                         res["n_total"], res["rows"], preselection_texts(), sample.production,
                         len(sample.files), None if sample.is_data else res["sumw"],
                         lumis=res.get("lumis"))
    shutil.rmtree(chunks)


def run(samples, args):
    preselect(samples, args.workers, args.executor, args.skip_bad_files)
