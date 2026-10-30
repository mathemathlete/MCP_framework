"""Standard control plots: 1D distributions of the candidate variables and the
cutflow of every step, read from the checkpoints on the scratch.

Steps: the preselection, each channel and each combination of
`config/selections.json`. Variables: `config/variables.json`. One folder per
signal point, `<plot_dir>/M<mass>_Q<charge>/`; the background samples are stacked
per process under the signal curve.

Data/MC, after the preselection only (the data is left out of the later steps): one
comparison per channel with `primary_datasets`, `Preselection/DataMC_<plot_dir>/`.
Its triggers on data and MC; the data of its primary datasets restricted to the
lumisections read in all of them, the MC normalised to their recorded luminosity.
"""

import numpy as np

from core import lumi as lumis
from core.selection import CHANNELS

from . import plotting
from . import samples as smp

NAME = "control_plots"
PARTS = ("variables", "cutflows")


def step_names():
    return [s.name for s in smp.steps()]


def points(signal):
    """-> [(folder, title, [signal point])], sorted by mass then charge."""
    return [(d.sample.name, f"M = {d.mass} GeV, Q = {d.charge}e", [d])
            for d in sorted(signal, key=lambda d: (d.mass, d.charge))]


def select_variables(names):
    variables = smp.load_variables()
    if not names:
        return variables
    unknown = set(names) - {v.name for v in variables}
    if unknown:
        raise SystemExit(f"[error] unknown variable(s) {sorted(unknown)}, see {smp.VARIABLES_CONFIG}")
    return [v for v in variables if v.name in names]


def plot_step(step, signal, background, variables, args):
    tag = "allcand" if args.all_candidates else "best"
    what = "all candidates" if args.all_candidates else "most ionizing candidate"
    fields = set((signal or background)[0].candidates.fields) | {smp.N_CANDIDATES}

    # without signal, one plot of the backgrounds alone
    for folder, title, members in points(signal) or [("bkg", "backgrounds", [])]:
        outdir = args.results / NAME / step.plot_dir / folder
        outdir.mkdir(parents=True, exist_ok=True)
        if args.plot != "variables":
            plotting.plot_cutflow(members, f"{title}, {step.label}", outdir / "cutflow.pdf",
                                  relative=not step.combined, backgrounds=background)
            table = plotting.cutflow_table(members, background)
            print(f"\n-- cutflow {step.name}, {title} --\n{table}")
            (outdir / "cutflow.txt").write_text(table + "\n")
        if args.plot == "cutflows":
            continue
        for variable in variables:
            if variable.name not in fields:
                print(f"[warn] {variable.name} not in the checkpoint, skipped")
                continue
            plotting.plot_variable(members, variable, f"{title}, {step.label}, {what}",
                                   outdir / tag / f"{variable.name}.pdf", args.norm,
                                   args.all_candidates, background, args.lumi)


def common_lumis(members, datasets):
    """The lumisections read in every primary dataset of `datasets`."""
    common = None
    for dataset in datasets:
        read = np.unique(np.concatenate([d.lumis for d in members
                                         if d.sample.primary_dataset == dataset]))
        print(f"[info] {dataset}: {len(read)} lumisections")
        common = read if common is None else np.intersect1d(common, read)
    return common


def plot_data_mc(step, data, background, variables, args):
    tag = "allcand" if args.all_candidates else "best"
    fields = set(background[0].candidates.fields) | {smp.N_CANDIDATES}
    for name, channel in sorted(CHANNELS.items()):
        if not channel.primary_datasets:
            continue
        members = [d for d in data if d.sample.primary_dataset in channel.primary_datasets]
        missing = sorted(set(channel.primary_datasets) - {d.sample.primary_dataset
                                                          for d in members})
        if missing:
            print(f"[warn] data/MC {name}: no {missing} in the run config, skipped")
            continue
        print(f"\n=== data/MC {step.name}, {name} triggers: "
              f"{', '.join(channel.primary_datasets)} ===")
        common = common_lumis(members, channel.primary_datasets)
        luminosity = lumis.recorded(common)
        observed = smp.merge_data([d.passing(channel.triggers, common) for d in members])
        mc = [d.passing(channel.triggers) for d in background]

        outdir = args.results / NAME / step.plot_dir / f"DataMC_{channel.plot_dir}"
        outdir.mkdir(parents=True, exist_ok=True)
        table = plotting.data_mc_table(observed, mc, luminosity, len(common))
        print(table)
        (outdir / "yields.txt").write_text(table + "\n")
        title = f"{step.label}, {channel.label} triggers"
        for variable in variables:
            if variable.name in fields:
                plotting.plot_data_mc(observed, mc, variable, title,
                                      outdir / tag / f"{variable.name}.pdf",
                                      args.all_candidates, luminosity)


def run(samples, args):
    plotting.apply_cms_style()
    variables = select_variables(args.variable)
    samples = list(samples.values())

    chosen = [s for s in smp.steps() if not args.step or s.name in args.step]
    for step in chosen:
        found = smp.available(step, samples)
        if not found:
            print(f"[warn] {step.name}: no checkpoint, run the selection first")
            continue
        loaded = [smp.load(step, s) for s in found]
        signal = [d for d in loaded if d.sample.is_signal]
        background = [d for d in loaded if d.sample.is_background]
        data = [d for d in loaded if d.sample.is_data]
        missing = [d.sample.name for d in background if d.sumw is None]
        if missing:
            raise SystemExit(f"[error] no sum of weights in the checkpoints of {missing}, "
                             "rerun their preselection")
        print(f"\n=== {step.name}: {len(signal)} signal point(s), "
              f"{len(background)} background sample(s), {len(data)} data sample(s) ===")
        # with data, the backgrounds alone are drawn by the data/MC plots
        if signal or (background and not data):
            plot_step(step, signal, background, variables, args)
        if data and step.name == smp.PRESELECTION:
            if not background:
                print("[warn] data without background sample: no data/MC")
                continue
            plot_data_mc(step, data, background, variables, args)

    print(f"[info] control plots in {args.results / NAME}")
