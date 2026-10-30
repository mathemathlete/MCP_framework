"""The MCP analysis: every stage of stages/pipeline.py in order, on the samples of a
run config, on given ntuples, or on the whole signal grid."""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from core import runconfig
from core import samples as smp
from core.checkpoint import CheckpointError
from core.cross_sections import DEFAULT_LUMI, LUMINOSITIES, SPINS
from core.executor import DEFAULT_EXECUTOR, DEFAULT_WORKERS, EXECUTORS
from core.paths import FRAMEWORK, RESULTS, SCRATCH, SLURM_BASE
from core.selection import SELECTIONS
from stages.control_plots import plots
from stages.control_plots.plotting import NORMS
from stages.pipeline import STAGE_NAMES, STAGES, select_stages

from . import slurm

CONFIG_SUFFIXES = (".yaml", ".yml")
REMOTE_PREFIX = "root://"
# every option a run config may set, and its default
DEFAULTS = {
    "from": None, "to": None, "only": None, "skip": None,
    "channel": None, "workers": DEFAULT_WORKERS, "executor": DEFAULT_EXECUTOR,
    "skip_bad_files": False, "max_files": None,
    "cutflow_mass": 1200, "lumi": DEFAULT_LUMI,
    "step": None, "variable": None, "norm": "shape",
    "all_candidates": False, "plot": None,
    "spin": None, "scenario": None, "limit_lumi": None,
    "no_atlas": False, "no_xsec": False, "xsec_only": False,
}
STAGE_CHOICE = ("from", "to", "only")
LISTS = ("only", "skip", "channel", "step", "variable", "spin", "scenario")
CHOICES = {
    "from": STAGE_NAMES, "to": STAGE_NAMES, "only": STAGE_NAMES, "skip": STAGE_NAMES,
    "channel": SELECTIONS, "executor": EXECUTORS, "step": plots.step_names(),
    "norm": NORMS, "plot": plots.PARTS,
    "spin": tuple(SPINS), "scenario": tuple(LUMINOSITIES),
}
# options of the login node, dropped from the command run inside the SLURM job
SLURM_FLAGS = {"--slurm": 1, "--walltime": 1, "--wait": 0, "--executor": 1, "--workers": 1}
EXAMPLES = """examples (from analysis_MCP/framework):
  python3.12 -m run.launch                                  every stage, whole signal grid
  python3.12 -m run.launch config/runs/signal_vs_bkg.yaml   every stage on a run config
  python3.12 -m run.launch root://.../output_1.root         every stage on these signal ntuples
  python3.12 -m run.launch CONFIG --to selection            stop once the selection is written
  python3.12 -m run.launch CONFIG --from efficiency_map     restart from the selection checkpoints
  python3.12 -m run.launch CONFIG --only control_plots      a single stage
  python3.12 -m run.launch --only limits --channel comb
  python3.12 -m run.launch CONFIG --skip control_plots
  python3.12 -m run.launch CONFIG --dry-run                 the samples and stages, run nothing
  python3.12 -m run.launch --list-stages
  python3.12 -m run.launch CONFIG --slurm 50                in a SLURM job, 50 dask worker jobs
  python3.12 -m run.launch CONFIG --slurm 50 --wait         same, wait for it and fetch the results
  python3.12 -m run.launch --fetch                          results of the last SLURM job
"""


def build_parser():
    p = argparse.ArgumentParser(
        prog="python3.12 -m run.launch", description=__doc__, epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    p.add_argument("inputs", nargs="*", metavar="INPUT",
                   help="a run config (config/runs/*.yaml) or ntuples "
                        "(default: the whole signal grid)")

    stages = p.add_argument_group("stages, default: all in order")
    stages.add_argument("--from", choices=STAGE_NAMES, metavar="STAGE",
                        help=f"first stage: {', '.join(STAGE_NAMES)}")
    stages.add_argument("--to", choices=STAGE_NAMES, metavar="STAGE", help="last stage")
    stages.add_argument("--only", nargs="+", choices=STAGE_NAMES, metavar="STAGE",
                        help="these stages only")
    stages.add_argument("--skip", nargs="+", choices=STAGE_NAMES, metavar="STAGE",
                        help="stages to leave out")
    stages.add_argument("--list-stages", action="store_true", help="list the stages and exit")
    stages.add_argument("--dry-run", action="store_true",
                        help="list the samples and the stages, run nothing")

    samples = p.add_argument_group("samples")
    samples.add_argument("--prod", help=f"CRAB production of the signal grid "
                                        f"(default: {smp.DEFAULT_PRODUCTION})")
    samples.add_argument("--version", help="production version (default: the latest)")
    samples.add_argument("--mass", type=int, nargs="+", help="restrict the grid to these masses")
    samples.add_argument("--charge", type=int, nargs="+",
                         help="restrict the grid to these charges, in e")
    samples.add_argument("--max-files", type=int, help="ntuples per sample, for a quick test")
    samples.add_argument("--rescan", action="store_true", help="re-index the SE first")

    selection = p.add_argument_group("preselection, selection")
    selection.add_argument("--channel", nargs="+", choices=SELECTIONS,
                           help="channels (default: all), of every stage")
    selection.add_argument("--executor", choices=EXECUTORS,
                           help=f"default: {DEFAULT_EXECUTOR}; slurm: inside a SLURM job, "
                                "see --slurm")
    selection.add_argument("--workers", type=int,
                           help=f"local processes, or SLURM worker jobs with --executor slurm "
                                f"(default: {DEFAULT_WORKERS})")
    selection.add_argument("--skip-bad-files", action="store_true", default=None,
                           help="drop unreadable files instead of failing (biases N total)")

    maps = p.add_argument_group("efficiency_map")
    maps.add_argument("--cutflow-mass", type=int,
                      help="mass of the cutflows, 0 for none (default: 1200)")
    maps.add_argument("--lumi", type=float,
                      help=f"fb^-1 of the background yields and of --norm events "
                           f"(default: {DEFAULT_LUMI})")
    maps.add_argument("--from-cache", action="store_true",
                      help="maps and plots from efficiencies.json, no checkpoint read")

    control = p.add_argument_group("control_plots")
    control.add_argument("--step", nargs="+", choices=plots.step_names(),
                         help="steps to plot (default: all)")
    control.add_argument("--variable", nargs="+",
                         help="variables of config/variables.json (default: all)")
    control.add_argument("--norm", choices=NORMS, help="default: shape")
    control.add_argument("--all-candidates", action="store_true", default=None,
                         help="every surviving candidate instead of the most ionizing one")
    control.add_argument("--plot", choices=plots.PARTS, help="variables or cutflows only")

    limits = p.add_argument_group("limits")
    limits.add_argument("--spin", nargs="+", choices=tuple(SPINS),
                        help="cross-section sets (default: all)")
    limits.add_argument("--scenario", nargs="+", choices=tuple(LUMINOSITIES),
                        help="luminosity scenarios (default: all)")
    limits.add_argument("--limit-lumi", type=float,
                        help="any luminosity in fb^-1, instead of the scenarios")
    limits.add_argument("--maps-dir", type=Path,
                        help="maps to read (default: <results>/efficiency_map)")
    limits.add_argument("--no-atlas", action="store_true", default=None,
                        help="drop the ATLAS Run 2 reference curve")
    limits.add_argument("--no-xsec", action="store_true", default=None,
                        help="skip the cross-section plots")
    limits.add_argument("--xsec-only", action="store_true", default=None,
                        help="only the cross-section plots, no map needed")

    outputs = p.add_argument_group("outputs")
    outputs.add_argument("--results", type=Path, default=RESULTS,
                         help="where the stages write, one folder each (default: results/)")

    batch = p.add_argument_group(f"slurm, from the login node (synced under {SLURM_BASE})")
    batch.add_argument("--slurm", type=int, metavar="JOBS",
                       help="run in a SLURM job, the selection on JOBS dask worker jobs")
    batch.add_argument("--walltime", default=slurm.DEFAULT_WALLTIME,
                       help="HH:MM:SS, of the job and of each worker")
    batch.add_argument("--wait", action="store_true", help="wait for the job, then --fetch")
    batch.add_argument("--fetch", action="store_true",
                       help="bring results and scratch back from the SLURM area, run nothing")
    return p


def read_inputs(args):
    """-> (run config, sample groups) of the positional inputs."""
    if not args.inputs:
        return {}, smp.default_groups()
    configs = [i for i in args.inputs if i.endswith(CONFIG_SUFFIXES)]
    if not configs:
        return {}, smp.files_group(args.inputs)
    if len(args.inputs) > 1:
        raise smp.SampleError("give a single run config, or ntuples")
    config = runconfig.load(configs[0], DEFAULTS)
    return config, config.get(runconfig.SAMPLES) or smp.default_groups()


def parse_args(argv):
    p = build_parser()
    args = p.parse_args(argv)
    try:
        config, args.groups = read_inputs(args)
    except smp.SampleError as err:
        p.error(str(err))
    if any(getattr(args, k) for k in STAGE_CHOICE):
        # stages chosen on the command line replace those of the config
        config = {k: v for k, v in config.items() if k not in STAGE_CHOICE}
    runconfig.apply(args, config, DEFAULTS)
    for name in LISTS:
        if isinstance(getattr(args, name), (str, int)):
            setattr(args, name, [getattr(args, name)])
    for name, allowed in CHOICES.items():
        value = getattr(args, name)
        unknown = [v for v in (value if isinstance(value, list) else [value]) if
                   v is not None and v not in allowed]
        if unknown:
            p.error(f"{name}: {unknown} not in {list(allowed)}")
    if args.wait and not args.slurm:
        p.error("--wait needs --slurm")
    return p, args


def local_path(given):
    path = Path(given)
    if not path.exists() and (FRAMEWORK / path).exists():
        path = FRAMEWORK / path
    return path.resolve()


def job_argv(p, args, argv):
    """The same run inside the job: the selection on the dask workers, the local inputs
    relative to framework/, the only directory the job sees."""
    inputs = {}
    for given in args.inputs:
        if given.startswith(REMOTE_PREFIX):
            continue
        path = local_path(given)
        if not path.is_relative_to(FRAMEWORK):
            p.error(f"--slurm syncs framework/ only: put {given} under {FRAMEWORK}")
        inputs[given] = str(path.relative_to(FRAMEWORK))
    out, skip = [], 0
    for token in argv:
        if skip:
            skip -= 1
            continue
        flag, sep, _ = token.partition("=")
        if flag in SLURM_FLAGS:
            skip = 0 if sep else SLURM_FLAGS[flag]
            continue
        out.append(inputs.get(token, token))
    return [*out, "--executor", "slurm", "--workers", str(args.slurm)]


def print_stages(stages):
    for stage in stages:
        print(f"  {stage.name:<15}{'' if stage.implemented else '[todo]'}")


def load_samples(args):
    try:
        samples = smp.build(args.groups, args.mass, args.charge, args.prod, args.version,
                            args.rescan)
    except (smp.SampleError, FileNotFoundError) as err:
        sys.exit(f"[error] {err}")
    if not samples:
        sys.exit("[error] no sample matches the selection")
    if args.max_files:
        samples = {n: replace(s, files=s.files[:args.max_files]) for n, s in samples.items()}
    print(f"[info] samples\n{smp.summary(samples)}")
    print(f"[info] checkpoints under {SCRATCH}")
    return samples


def main():
    argv = sys.argv[1:]
    p, args = parse_args(argv)
    if args.list_stages:
        print_stages(STAGES)
        return
    if args.fetch:
        slurm.fetch()
        return
    try:
        stages = select_stages(getattr(args, "from"), args.to, args.only, args.skip)
    except ValueError as err:
        p.error(str(err))
    if not stages:
        p.error("no stage selected")
    if args.slurm:
        slurm.submit(job_argv(p, args, argv), args.walltime, args.wait)
        return

    needs_samples = any(s.implemented and s.samples for s in stages)
    samples = load_samples(args) if needs_samples else None
    print("[info] stages")
    print_stages(stages)
    if args.dry_run:
        return

    for stage in stages:
        if not stage.implemented:
            print(f"\n##### {stage.name}: [todo], skipped")
            continue
        print(f"\n##### {stage.name}", flush=True)
        stage_samples = samples
        if samples and not stage.data and any(s.is_data for s in samples.values()):
            stage_samples = {n: s for n, s in samples.items() if not s.is_data}
            print(f"[info] data left out of {stage.name} (blinded)")
            if not stage_samples and stage.samples:
                continue
        try:
            stage.run(stage_samples, args)
        except (CheckpointError, smp.SampleError, FileNotFoundError) as err:
            sys.exit(f"[error] {stage.name}: {err}")
    print(f"\nDone. Results in {args.results}")


if __name__ == "__main__":
    main()
