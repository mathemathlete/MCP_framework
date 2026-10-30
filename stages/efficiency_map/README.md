# MCP efficiency maps and background yields

The `efficiency_map` stage: selection efficiencies (mass × charge) for the **muon**
and **tau** channels, read off the checkpoints of the `selection` stage, itself fed
by the MiniAOD grid produced with CRAB and **read directly from T2_FR_IPHC over
xrootd** by `preselection` — no file is downloaded. Background samples of a run
config go through the same selection and give expected yields instead of maps.

Clean version of `coffea/MiniAOD_verif/Analyse`, whose AOD vs MiniAOD comparison
was only a one-off validation. What it established is carried over here as code,
not as a check to redo.

## Running it

```bash
python3.12 -m run.launch --to efficiency_map
```

Run it from `framework/`. It does everything up to the maps: `preselection` and
`selection`, then the three channels over the 263 grid points of
`MCP_spin0p5_Q1to20` (the default signal production), the ROOT maps on the scratch
and their plot in `results/efficiency_map/`. The cutflows are computed and kept in the cache; their
plots, together with the 1D distributions, are made by the `control_plots` stage.
Without `--to`, the run goes on to `regions`, `control_plots` and `limits`.

```bash
python3.12 -m run.launch --to efficiency_map --channel tau     # a single channel (see the table below)
python3.12 -m run.launch --to efficiency_map --mass 1200 1600  # a subset of the grid
python3.12 -m run.launch --to efficiency_map --charge 4 5 6    # charges in e
python3.12 -m run.launch --to efficiency_map --cutflow-mass 0  # no cutflow
python3.12 -m run.launch --only efficiency_map --from-cache    # replay the plots from the cache
python3.12 -m run.launch --from selection --to efficiency_map  # redo the muon/tau selections
python3.12 -m run.launch --only efficiency_map                 # redo the maps only
python3.12 -m run.launch --to preselection                     # stop once the preselection is written
python3.12 -m run.launch --to selection                        # stop before the maps
python3.12 -m run.launch --to efficiency_map --rescan          # re-index the SE first
python3.12 -m run.launch --to efficiency_map --workers 16      # local processes (default 32)
python3.12 -m run.launch --help                                # the rest
```

A run config, `config/runs/<run>.yaml` as first argument, gives the samples (signal
productions, backgrounds, single files) and the default options, see the top-level
README and `core/samples.py`; `--mass`, `--charge`, `--prod` and every other option
given on the command line override it.

`--executor slurm` runs `preselection` and `selection` on dask workers submitted as
SLURM jobs (`--workers` of them); it only works inside a SLURM job, so go through
`python3.12 -m run.launch --to efficiency_map --slurm N`, see the top-level README.

Rerunning one channel or a few points **merges point by point** into the existing
cache: the points not recomputed are kept, and a cutflow at a new mass is added to
the previous ones instead of replacing them.

## Checkpoints

The `preselection` and `selection` stages write the events they keep on the
scratch, which this stage reads:

```
ntuples (xrootd) ─► preselection ─► muon selection ─┬─► maps + cutflows
                                  └► tau selection ─┘   (comb = muon OR tau)

/scratch/cms/xmadre/MCP_analysis/
├── preselection/<prod>/<version>/<sample>.root     candidates passing the preselection
└── selection/
    ├── muon/<prod>/<version>/<sample>.root         candidates passing the muon channel
    │                                               (trigger included)
    └── tau/<prod>/<version>/<sample>.root
```

A sample is a grid point (`M<m>_Q<q>`) or a background dataset (its primary
dataset name). One file per sample and per step, containing:

| Object | Content |
|---|---|
| `Events` | TTree: `run`, `luminosityBlock`, `event`, `weightGenerator`, `weightPU`, [triggers], `cand_*` (one per canonical field) |
| `cutflow` | TH1D: N total, then one bin per cut |
| `cutflow_texts` | the text of the cuts that produced it |
| `production` | `<prod>/<version>` of the source ntuples |
| `n_files` | number of ntuples read |
| `sumw` | sum of `weightGenerator` over every event read, before any cut |

During a step, the coffea workers write one file per chunk into
`<step>/.chunks/`, then merged into a single file per point and deleted.

| After changing… | Run |
|---|---|
| the preselection, the triggers, the production | with no option (rereads the ntuples, the only slow step) |
| the muon/tau cuts, the `objects` | `--from selection` |
| nothing, only the maps/cutflows to redo | `--from efficiency_map` |

Restarting from a checkpoint written with other cuts, another production or
another number of ntuples fails with an explicit message, instead of silently giving
a wrong result. The combined
channel has no checkpoint of its own: it is the OR of the muon and tau events, on
`(run, luminosityBlock, event)`.

On M = 1200, Q = 1e and 4e (41 files): 28 s from the ntuples, 8 s from the
preselection, 4 s from the selection; identical maps and cutflows. The preselection
weighs ~10 MB per point.

## Prerequisites

```bash
voms-proxy-init --voms cms
```

That's all: no `cmsenv` (uproot reads xrootd), no CRAB, no transfer. A few minutes
with `--workers 32` for the 2718 files of the previous production `MCP_spin0p5`
(~70 s of reading per channel over its grid); `MCP_spin0p5_Q1to20` has 4947.

## The files

| File | Role |
|---|---|
| `core/datasets/catalog.py` | Grid point → xrootd URLs, from the production index. |
| `core/selection/` | Branches → canonical fields, cuts, combined channel (see its README). |
| `config/selections.json` | **The selections.** Channels, cuts, triggers, combinations. |
| `config/cut_labels.json` | Text of the cuts on the cutflow plots. |
| `core/samples.py`, `config/runs/` | The samples of a run, from a run config. |
| `stages/preselection.py`, `stages/selection.py` | The coffea steps writing the checkpoints. |
| `efficiency.py` | Efficiencies, cutflows and yields read off the checkpoints, result objects, TH2D, JSON caches. |
| `plotting.py` | 2D map. |
| `map.py` | The stage, `run(samples, args)`, called by `run.launch`. |

## Where the files come from

The ntuples stay on the IPHC SE (`sbgdcache.in2p3.fr`), stored by
`production/submit_crab_production.sh`:

```
/store/user/xmadre/HSCP/<prod>/<version>/MCP_spin0p5/Q-<charge>e/M-<mass>/
    <primaryDataset>/<prod>_<version>/<timestamp>/0000/output_*.root
```

The `<timestamp>` is imposed by CRAB and unpredictable, so the index is produced
once by `--catalog`:

```bash
production/submit_crab_production.sh -p MCP_spin0p5_Q1to20 --catalog
```

which writes `logs/<prod>/<version>/files.txt` (one xrootd URL per line).
`core/datasets/catalog.py` reads it back and groups by `(mass, charge)` on the
`/Q-<n>e/M-<m>/` pattern of the path; `--rescan` reruns the scan by itself when the
production has changed. Without an explicit version, the latest one is used.

**Available grid** (`MCP_spin0p5_Q1to20`, v1): 263 points, 4947 files.
Masses 100 → 2400 GeV (16 values, of which 300/500/700/900/1000/1400/1800 are absent
from the old AOD grid), charges 1e → 16e and 20e (`Q-3` to `Q-60` in the dataset
names, where `Q-n` is in units of e/3). Missing points: 20e at 600, 700, 800, 900,
1000, 1200 and 1400 GeV, 16e at 900 GeV, 10e at 2400 GeV.

Earlier productions: `MCP_spin0p5` (144 points, charges 1e → 9e, 2718 files),
`MCP_spin0p5_M1600_allQ` (1600 GeV, charges 1e → 16e, 20e, 24e, 30e).

## What a map contains

```
efficacity_Comb[m][q] = N(events with >= 1 selected candidate
                          [+ trigger if the channel applies one]) / N(entries)
initial[m][q]         = N(ntuple entries)
```

Same definition and same TH2D names as `limit_test/data/map_muon_trg.root`, so the
files produced can be used as they are by `limit_test/scripts/extrap.py` and
`limit_1.py`.

The **binning covers the whole produced grid**: 16 mass bins, 9 charge bins,
extended to the masses and charges of the points of the map (e.g. up to 20e with
`MCP_spin0p5_Q1to20`).
The reference map stopped at 9 × 8 and left `Q-27` (9e) in the overflow.
`extrap.py` reads the edges from the histogram, so the wider binning breaks nothing
downstream. The edges are the masses themselves (upper edge 2800) and `1 … 10` in
charge: `MASSES` / `CHARGES` of `core/datasets/catalog.py`, plus the extra points.

## Outputs

```
results/efficiency_map/<channel folder>/
├── map.pdf                2D map
└── yields.txt             expected events per dataset and per process

/scratch/cms/xmadre/MCP_analysis/efficiency_map/
├── efficiencies.json      cache of every number
├── yields.json            background yields, raw numbers, every channel
└── <channel folder>/map.root   TH2D efficacity_Comb + initial
```

One folder per channel (`Muon/`, `Tau/`, `Comb/`, see `plot_dir` in
`config/selections.json`). The JSON cache is unique and at the root of `efficiency_map/` on the scratch:
it is the source of truth, the plots are derived from it again in 5 s with
`--only efficiency_map --from-cache`.

Conventions: the points with a measured efficiency of zero are drawn as a 68% CL
upper limit (arrow), otherwise they would vanish from the log scale; on the maps,
a white cell = no sample, a hatched cell = sample present but 0 events selected.

The ROOT maps keep the variable binning of the reference; the **drawn** maps use a
categorical mass axis (cells of equal width), without which the cells at 100 GeV
are four times narrower than those at 2400 and the numbers no longer fit in them.

## Background yields

For each background sample and channel (`split: dataset` groups of the run config):

```
expected = xsec x lumi x sum(w over the selected events) / sum(weightGenerator over every event)
w        = weightGenerator x weightPU
```

`xsec` comes from the CSV of the group (`data/cross_sections/`), `lumi` (fb⁻¹) from
`--lumi` or the run config, default 376.81 (Run 3 scenario of `stages/limits`).
The generator weights matter: W+jets amc@NLO has 16% negative weights. The table
gives each dataset then the sum of its process; `yields.json` keeps the raw numbers
and merges sample by sample, like the maps. The combined channel is the OR of the
muon and tau events, each event counted once.

## Notes

- The signal efficiencies are **unweighted** (`weightGenerator` / `weightPU` are not
  applied), as in the reference map — otherwise the two would no longer be
  comparable.
- An unreadable file makes the grid point fail, on purpose: `--skip-bad-files`
  lets it through but then biases the `N total` of the denominator.
- `python3.12`, not `python3`: `coffea`, `hist` and `mplhep` are only installed
  under 3.12.
