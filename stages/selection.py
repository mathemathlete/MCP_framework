"""Preselection checkpoint -> selection checkpoint of each channel, trigger included."""

import shutil

import awkward as ak
import coffea.processor as processor
import numpy as np

from core import checkpoint, executor
from core.selection import COMBINED, PRESELECTION, SELECTIONS, get_selection

from .preselection import preselection_texts


class _SelectionProcessor(processor.ProcessorABC):
    """Preselection checkpoint -> candidates passing one channel, trigger included."""

    def __init__(self, selection, outdir):
        self.selection = selection
        self.outdir = outdir

    def process(self, events):
        name = events.metadata["dataset"]
        cand = self.selection.candidates.build(events)
        mask = self.selection.candidate_mask(cand, events)
        _, rows = self.selection.cutflow(events)

        kept = ak.to_numpy(ak.any(mask, axis=1))
        data = {b: ak.to_numpy(events[b])[kept]
                for b in (*checkpoint.EVENT_BRANCHES, *checkpoint.weight_branches(events))}
        data["cand"] = cand[mask][kept]
        checkpoint.write_events(self.outdir / name / checkpoint.chunk_name(events.metadata), data)
        return {name: np.array([n for _, n in rows], dtype=np.int64)}

    def postprocess(self, accumulator):
        return accumulator


def selection_texts(selection):
    texts = [cut.text for _, cut in selection.channel.cuts()]
    if selection.channel.triggers:
        texts.append(f"trigger: {' | '.join(selection.channel.triggers)}")
    return texts


def base_channels(channels):
    """The channels to select, combinations replaced by their parts."""
    names = []
    for channel in channels:
        for part in COMBINED[channel][0] if channel in COMBINED else (channel,):
            if part not in names:
                names.append(part)
    return names


def select(selection, samples, workers=executor.DEFAULT_WORKERS,
           executor_name=executor.DEFAULT_EXECUTOR):
    step, presel_step = selection.channel.name, checkpoint.PRESELECTION
    presel_files = {name: checkpoint.sample_file(presel_step, name, s.production)
                    for name, s in samples.items()}
    presel = {name: checkpoint.read_cutflow(presel_files[name], preselection_texts(),
                                            s.production, len(s.files))
              for name, s in samples.items()}
    chunks = checkpoint.chunk_dir(step)
    checkpoint.reset(chunks)
    print(f"\n=== {step} selection -> {checkpoint.step_dir(step)} ===")
    fileset = {name: [str(path)] for name, path in presel_files.items()}
    results = executor.run(fileset, checkpoint.TREE, _SelectionProcessor(selection, chunks),
                           workers, executor_name)

    n_presel = len(PRESELECTION)
    for name, sample in samples.items():
        n_total, presel_rows = presel[name]
        # no chunk when nothing survived the preselection
        rows = results.get(name, np.zeros(len(selection.cut_labels()), dtype=np.int64))
        # the input holds preselected candidates only: its own preselection rows are flat
        checkpoint.merge(chunks / name, checkpoint.sample_file(step, name, sample.production),
                         n_total,
                         [*presel_rows, *rows[n_presel:]], selection_texts(selection),
                         sample.production, len(sample.files),
                         checkpoint.stored_sumw(presel_files[name]), template=presel_files[name])
    shutil.rmtree(chunks)


def run(samples, args):
    for name in base_channels(args.channel or SELECTIONS):
        select(get_selection(name, "skim"), samples, args.workers, args.executor)
