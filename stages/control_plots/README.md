# Control plots

1D distributions of the candidate variables and the cutflow of every selection
step, over the signal grid, with the backgrounds of a run config stacked under it.
Nothing is read over xrootd: everything comes from the checkpoints written on the
scratch by the `preselection` and `selection` stages (run them first, with the same
run config; a full `run.launch` does).

```bash
python3.12 -m run.launch --only control_plots
python3.12 -m run.launch config/runs/signal_vs_bkg.yaml --only control_plots --norm events
```

From `framework/`. Outputs in `results/control_plots/<folder>/<point>/`, one
`<point>` folder per signal point (`M1200_Q4`), the signal point alone against the
backgrounds:

| File | Content |
|---|---|
| `cutflow.pdf` | cumulative efficiency cut by cut, and below it the efficiency relative to the previous cut |
| `cutflow.txt` | the same as a table (N and cumulative efficiency) |
| `best/<variable>.pdf` | distribution of the most ionising candidate (largest `Ih`) of each event |
| `allcand/<variable>.pdf` | every surviving candidate (`--all-candidates`) |

## Steps

- `preselection` → `Preselection/`: the candidates after the preselection;
- a channel of `config/selections.json` (`muon`, `tau`) → its `plot_dir`: the
  candidates after the full selection of the channel, trigger included;
- a combination (`comb`): rebuilt as in the `efficiency_map` stage, the first channel that
  fires keeps the event and its candidates. Its "cutflow" is the overlap summary
  (`muon`, `tau`, `muon kept`, `tau kept`, `combined`), without a relative panel.

The cut labels come from `config/cut_labels.json`. The cutflow is the one written
in the checkpoint, even if the cuts have changed since: rerun `efficiency_map` to
update it.

## Backgrounds

The `split: dataset` groups of the run config are drawn per process (one group =
one process): stacked and filled under the signal curves, as one dashed curve in the
cutflows. In the cutflows, the datasets of a process are weighted by their cross
sections. Without signal in the run config, one plot per step shows the backgrounds
alone, in `<folder>/bkg/`.

## Data/MC

With `split: data` samples (`config/runs/data_vs_bkg.yaml`), after the preselection
only, one comparison per channel having `primary_datasets` in
`config/selections.json`:

| channel | triggers, on data and MC | data |
|---|---|---|
| `muon` | `HLT_Mu50`, `HLT_IsoMu24`, `HLT_IsoMu27` | `Muon0` + `Muon1` |
| `tau` | the 3 double-tau paths | `Tau` |

- the data of a channel is kept in the lumisections read in **each** of its primary
  datasets (a lumisection whose job failed in one of them is dropped), each event
  once (`(run, luminosityBlock, event)`);
- the luminosity of these lumisections is computed with `brilcalc` (web cache, BRIL
  normtag), cached with its JSON mask under `<scratch>/lumi/`; the backgrounds are
  normalised to it, whatever `--norm` and `--lumi`;
- outputs in `Preselection/DataMC_<folder>/`: `best/<variable>.pdf` (stack, data with
  its 68% Poisson interval, data/MC) and `yields.txt`
  (expected events per process, data, data/MC).

```bash
python3.12 -m run.launch config/runs/data_2024.yaml --slurm 100        # the data preselection
python3.12 -m run.launch config/runs/data_vs_bkg.yaml --only control_plots --step preselection
```

The data production is indexed as it is when `files.txt` was written (`--rescan`
once it has grown); a data checkpoint written from fewer files is refused.

## Variables

One entry per variable in `config/variables.json`, the key being a canonical
candidate field (see `core/selection/candidates.py`):

```json
"Ih": {"label": "$I_h$ [MeV/cm]", "bins": 80, "range": [0, 80], "logy": true}
```

- values outside `range` go into the first/last bin;
- `"data_mc": {"bins": 40, "range": [0, 20]}`: binning of the Data/MC plots only;
- candidates without a value (no muon for `inverse_beta`, no tau for
  `pt_tau`, `NO_VALUE = -999`) are not counted;
- `n_candidates` is special: the number of surviving candidates per event.

## Options

```bash
python3.12 -m run.launch --only control_plots --step muon tau          # some steps
python3.12 -m run.launch --only control_plots --variable pt Ih eta     # some variables
python3.12 -m run.launch --only control_plots --mass 1200 --charge 1 4 # part of the grid
python3.12 -m run.launch --only control_plots --norm efficiency        # area = selection efficiency
python3.12 -m run.launch --only control_plots --norm events --lumi 109 # expected events for 109 fb^-1
python3.12 -m run.launch config/runs/signal_vs_bkg.yaml --only control_plots
python3.12 -m run.launch --only control_plots --all-candidates         # every candidate
python3.12 -m run.launch --only control_plots --plot cutflows          # without the distributions
```

`--norm`: `shape` (unit area, the default; the background stack as a whole),
`efficiency` (area = fraction of the generated events passing the step, hence
comparable from one step to the next; one dashed line per background process) or
`events` (expected events for `--lumi` fb⁻¹: xsec × lumi / N generated for the
signal, unweighted as in the maps, with the HECO cross sections; xsec × lumi × w /
Σ weightGenerator for the backgrounds, w = generator × pileup weight).

The samples drawn are those of the run config (the signal grid by default) that
have a checkpoint for the step: a sample missing from a step is simply skipped.
