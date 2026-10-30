# MCP analysis framework

```
framework/
├── core/                    the library, shared by every stage
│   ├── selection/           selection classes (candidates, cuts, channels)
│   ├── datasets/            production catalogs (files.txt)
│   ├── samples.py           what a run reads: signal grid points, background datasets
│   ├── runconfig.py         run configs (config/runs/*.yaml)
│   ├── checkpoint.py        the events kept after each step, on the scratch
│   ├── cross_sections.py    signal and background cross sections, luminosities
│   ├── executor.py          coffea executors: iterative, futures, SLURM (dask)
│   ├── plotting.py          CMS style (coffea/plot_style.py) and saving
│   └── paths.py             every path of the framework
├── stages/                  the stages of the analysis, in the order of pipeline.py
│   ├── pipeline.py          the list of stages, --from/--to/--only/--skip
│   ├── preselection.py      raw ntuples over xrootd -> preselection checkpoint
│   ├── selection.py         -> selection checkpoint of each channel (muon, tau)
│   ├── efficiency_map/      mass × charge efficiency maps, cutflows, background yields
│   ├── regions.py           -> selected events as flat trees, one boolean per region
│   ├── control_plots/       1D distributions and cutflows of every step, signal vs backgrounds
│   └── limits/              expected exclusion contours
├── run/                     launch.py (the launcher), slurm.py (SLURM submission)
├── config/                  selections.json, cut_labels.json, variables.json,
│                            runs/*.yaml (run configs)
├── data/                    external inputs (cross sections)
├── results/<stage>/         every output, one tree per stage
└── production/              CRAB production of the ntuples
```

## Running

Everything runs **from `framework/`**, as a module, with `python3.12`. One launcher
runs the stages of `stages/pipeline.py` in order:

```
calibration [todo] -> weights [todo] -> preselection -> selection -> efficiency_map
    -> regions -> control_plots -> limits
```

Given only its input, it runs them all; `--to` stops after a stage, `--from` starts
at one, `--only` runs some of them, `--skip` leaves some out:

```bash
python3.12 -m run.launch                                  # every stage, whole signal grid
python3.12 -m run.launch config/runs/signal_vs_bkg.yaml   # every stage on a run config
python3.12 -m run.launch root://.../output_1.root         # every stage on these signal ntuples
python3.12 -m run.launch CONFIG --to selection            # stop once the selection is written
python3.12 -m run.launch CONFIG --from selection          # restart from the preselected events
python3.12 -m run.launch CONFIG --from efficiency_map     # restart from the selected events
python3.12 -m run.launch CONFIG --only control_plots      # a single stage
python3.12 -m run.launch --only limits --channel comb     # a stage and one of its options
python3.12 -m run.launch CONFIG --dry-run                 # the samples and stages, run nothing
python3.12 -m run.launch --list-stages
python3.12 -m run.launch --help                           # every option, grouped by stage
```

Each stage reads what the stages before it wrote and writes its own outputs, so a
run can start anywhere: `preselection` and `selection` write checkpoints on the
scratch (`core/checkpoint.py`), the others write to `results/<stage>/`
(`--results` elsewhere, e.g. for a test).

| stage | reads | writes |
|---|---|---|
| `preselection` | the ntuples, over xrootd | `<scratch>/preselection/` |
| `selection` | the preselection checkpoints | `<scratch>/selection/<channel>/` |
| `efficiency_map` | the selection checkpoints | `results/efficiency_map/<channel>/`: map (signal), yields (backgrounds) |
| `regions` | the selection checkpoints | `<scratch>/regions/<channel>/`, trees with `region_<name>` |
| `control_plots` | every checkpoint | `results/control_plots/<channel>/M<m>_Q<q>/` |
| `limits` | the maps | `results/limits/<channel>/<spin>/` |

`results/` only holds what is read by eye, the plots and the tables (`.pdf`,
`.txt`). The data files of these stages (`.root`, `.json`) go to the same place
under `/scratch/cms/xmadre/MCP_analysis/` (`core.paths.SCRATCH`, overridable with
`MCP_SCRATCH`), see `core/scratch.py`; with `--results` outside `results/` (a test),
everything stays there. `--only efficiency_map limits --from-cache` replays the maps
and the limits from the cache, without reading any checkpoint.

### Run configs: choosing the samples

Without an input, everything runs on the whole signal grid (`MCP_spin0p5_Q1to20`,
latest version). Signal ntuples given directly are read as grid points; backgrounds
need a run config, for their cross sections. A run config (`config/runs/*.yaml`)
says what to read, signal and backgrounds, and gives the default options; an option
on the command line wins, and stages chosen on the command line replace those of
the config:

```bash
python3.12 -m run.launch config/runs/signal_vs_bkg.yaml --to control_plots
python3.12 -m run.launch config/runs/bkg_2024.yaml --to preselection
```

```yaml
samples:
  signal:                      # a group: one legend entry, one line of the yield tables
    split: grid                # one sample per grid point M<m>_Q<q>
    production: [MCP_spin0p5_Q1to20, MCP_spin0p5_M1600_allQ]   # each at its latest version
    mass: [1200]               # optional
  DY:
    split: dataset             # one sample per primary dataset
    production: BKG_DY_2024
    match: DYto2Mu             # optional regex on the file URLs
    xsec: data/cross_sections/bkg_DY_2024.csv
    label: Drell-Yan
  data:
    split: data                # one sample per primary dataset and era, Muon0_Run2024C
    production: Run2024
  one_file:
    files: [root://.../output_1.root]   # given ntuples instead of a production
lumi: 376.81                   # fb^-1 of the yields and of --norm events
to: preselection               # any option of run.launch, by its name
```

Every production is taken at its latest version (`production/logs/<prod>/v<n>/`;
`version: v1` pins a single one). A point present in two productions is taken from
the first one listed, so listing `MCP_spin0p5_Q1to20` then `MCP_spin0p5_M1600_allQ`
adds 24e and 30e at 1600 GeV to the grid. `core/samples.py` documents every key;
`config/runs/` has examples (`signal`, `one_file`, `bkg_2024`, `signal_vs_bkg`,
`data_2024`, `data_vs_bkg`).

**Data is blinded**: it goes through the `preselection` and the `control_plots`
(data/MC after the preselection, see `stages/control_plots/README.md`) only; the
other stages leave it out. Its weights are 1, and its preselection checkpoints keep
the lumisections read, from which the luminosity is computed with `brilcalc`.

The checkpoints are stored per production,
`<scratch>/preselection/<prod>/<version>/<sample>.root`, so productions never
overwrite each other. Each one records how many ntuples it was written from:
reading it back for a sample with a different number of files (a single-file test,
a production that grew since) fails instead of giving a wrong result.

### On SLURM

```bash
voms-proxy-init --voms cms --valid 192:00
python3.12 -m run.launch --slurm 50                    # 50 dask workers, one SLURM job each
python3.12 -m run.launch --to efficiency_map --channel tau --slurm 50 --walltime 08:00:00
python3.12 -m run.launch --fetch                       # bring results/ and the scratch back
python3.12 -m run.launch --slurm 50 --wait             # wait for the job to end, then --fetch
python3.12 -m run.launch config/runs/bkg_2024.yaml --to efficiency_map --slurm 100
```

The compute nodes only mount `/home-pbs`: `--slurm` copies the grid proxy,
syncs the framework, `results/` and the scratch under `/home-pbs/xmadre/MCP/`
(`core.paths.SLURM_BASE`, overridable with `MCP_SLURM_BASE`), then submits a job
that runs the same `run.launch` command there with the `coffea_workflow/condaEnv`
environment (`MCP_SLURM_PYTHON`). This job hosts the dask scheduler and submits the
workers as SLURM jobs (`core/executor.py`): only `preselection` and `selection` are
distributed, everything else runs inside the job. A run config given to `--slurm`
must sit under `framework/`, the only directory synced. On SLURM the scratch is
`/home-pbs/xmadre/MCP/scratch`; `--fetch` copies it back under `core.paths.SCRATCH`.

The job is over once it no longer shows up in `squeue -u $USER`; it succeeded if its
log ends with `Done.`. Logs: `/home-pbs/xmadre/MCP/logs/` (`analyses_<job>.out/.err`,
`worker_<job>.out/.err`). Worker partition and memory: `MCP_SLURM_PARTITION`
(`vo.scigne.fr`), `MCP_SLURM_MEMORY` (`8GB`).

### Checkpoints

`preselection` and `selection` save the events they keep on the scratch (after the
preselection, after the muon selection, after the tau selection): `--from selection`
and `--from efficiency_map` restart from them, see
`stages/efficiency_map/README.md`. Every stage folder has its own README.

## Extending

- **Samples to run on**: a run config in `config/runs/`, no code change. A new
  background: its production (`production/`) and a cross-section CSV in
  `data/cross_sections/`.
- **A selection**: one entry in `config/selections.json`, no code change
  (see `core/selection/README.md`). A new ntuple source (NanoAOD):
  a `Candidates` subclass in `core/selection/candidates.py`.
- **A stage**: a module or a `stages/<stage>/` folder (empty `__init__.py`) with a
  `run(samples, args)` function, listed at its place in `STAGES` of
  `stages/pipeline.py`; its options go into `run/launch.py` (and `DEFAULTS`, to be
  settable from a run config). It imports what it needs from `core`
  (`from core.selection import get_selection`), uses relative imports between its own
  files, reads what the earlier stages wrote and writes to `args.results / <stage>`.
  The `[todo]` stages (`calibration`, `weights`) are placeholders of this kind.
- **Code shared by several stages**: in `core/`, not in a stage.
