"""Selection checkpoints -> the selected events as flat columns, one boolean per region
of `config/selections.json`: <scratch>/regions/<channel>/<prod>/<version>/<sample>.root."""

import awkward as ak
import numpy as np

from core import checkpoint
from core.scratch import data_path
from core.selection import CHANNELS, SELECTIONS
from core.selection.candidates import SkimCandidates
from core.selection.selection import most_ionizing

from .selection import base_channels

NAME = "regions"


def selected_columns(events, cand, regions):
    """`cand`: the selected candidates of each event -> event branches, weights,
    the most ionizing candidate and `region_<name>`."""
    best = ak.drop_none(most_ionizing(cand))
    columns = {b: ak.to_numpy(events[b])
               for b in (*checkpoint.EVENT_BRANCHES, *checkpoint.weight_branches(events))
               if b in events.fields}
    columns.update({f: ak.to_numpy(best[f]) for f in best.fields})
    for region, cuts in regions:
        passed = np.ones(len(best), dtype=bool)
        for cut in cuts:
            passed &= ak.to_numpy(cut(best))
        columns[f"region_{region}"] = passed
    return columns


def table(channel, counts):
    names = [region for region, _ in channel.regions]
    width = max([len(s) for s in counts] + [6])
    lines = [f"{'sample':<{width}} {'selected':>9}" + "".join(f" {n:>9}" for n in names)]
    for sample, (n, per_region) in counts.items():
        lines.append(f"{sample:<{width}} {n:>9d}" + "".join(f" {k:>9d}" for k in per_region))
    return "\n".join(lines)


def run(samples, args):
    outdir = data_path(args.results / NAME)
    for name in base_channels(args.channel or SELECTIONS):
        channel = CHANNELS[name]
        counts = {}
        for sample in samples.values():
            path = checkpoint.sample_file(name, sample.name, sample.production)
            checkpoint.check_production(path, sample.production, len(sample.files))
            events = checkpoint.read_events(path)
            columns = selected_columns(events, SkimCandidates().build(events), channel.regions)
            out = outdir / name / sample.production / f"{sample.name}.root"
            checkpoint.write_events(out, columns)
            counts[sample.name] = (len(events), [int(columns[f"region_{r}"].sum())
                                                 for r, _ in channel.regions])
        print(f"\n=== regions {name} -> {outdir / name} ===\n{table(channel, counts)}")
