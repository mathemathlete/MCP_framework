# MCP expected limits

Expected exclusion contours (mass × charge) from the efficiency maps of
the `efficiency_map` stage and the HECO cross sections, the last stage of the pipeline. A rewrite of `limit_test/scripts`
(`extrap.py`, `limit_1.py`, `diff.py`), where every figure required editing
constants at the top of a script: here the three channels, the two spins and the
two luminosity scenarios come out of a single command.

## Running it

```bash
python3.12 -m run.launch --only limits
```

Run it from `framework/` (a full `run.launch` ends with it). It does everything: 3 channels (`muon`, `tau`, `comb`) ×
2 spins × 2 luminosity scenarios, i.e. 12 exclusion contours, the 12 matching
`N_pred` / `r` ROOT files and the cross-section plots, in `results/limits/`.

```bash
python3.12 -m run.launch --only limits --channel comb             # a single channel
python3.12 -m run.launch --only limits --spin spin0p5             # a single set of cross sections
python3.12 -m run.launch --only limits --scenario run23           # a single scenario
python3.12 -m run.launch --only limits --limit-lumi 300           # any luminosity, in fb^-1
python3.12 -m run.launch --only limits --maps-dir ../limit_test/data   # the AOD reference maps
python3.12 -m run.launch --only limits --no-atlas                 # without the ATLAS Run 2 curve
python3.12 -m run.launch --only limits --xsec-only                # only the cross-section plots
python3.12 -m run.launch --help                                   # the rest
```

## Prerequisites

`python3.12` (as everywhere else: `hist`, `mplhep`, `uproot` and `scipy` are only
installed there). No proxy, no xrootd: everything is read locally, from
`<scratch>/efficiency_map/<channel folder>/map.root` and `data/cross_sections/`. The maps must therefore
exist — otherwise run `python3.12 -m run.launch --to efficiency_map` first. Run
with samples where none is signal (backgrounds only), the stage skips itself.

## The files

| File | Role |
|---|---|
| `limits.py` | **The computation.** `N_pred`, `r`, mass reach, ROOT output. |
| `plotting.py` | Exclusion contour, cross-section plots. |
| `limit.py` | The stage, `run(samples, args)`, called by `run.launch`. |

## What is computed

For each grid point (mass, charge):

```
N_pred = eff(m, q) x sigma(m, q) x L x 1000        sigma in pb, L in fb^-1
r      = 2.3 / N_pred
```

`r < 1` = point excluded at 95% CL. The 2.3 is the 95% Poisson upper limit for
**zero observed events and zero expected background**: no background, no
systematics, no weighting. It is a sensitivity projection, not a limit.

The `r = 1` contour is drawn by linear interpolation of `log10(r)` over the
(mass, charge) plane — `LinearNDInterpolator`, so nothing is extrapolated outside
the convex hull of the measured points: hence the white area above Q = 7 for the
muon channel, where no event is selected any more.

The table printed for each configuration gives the **mass reach** per charge: the
largest `m` with `r < 1`, interpolated in log between the two points around the
crossing. `--` = never excluded, `> 2400` = excluded up to the end of the grid.

## Inputs

**Efficiency maps**: `<scratch>/efficiency_map/<channel folder>/map.root`, TH2D
`efficacity_Comb` and `initial`. The AOD reference maps
(`limit_test/data/map_{muon,comb}_trg.root`) are accepted as they are via
`--maps-dir`: the binning is read from the histogram, the file names are tried in
the order `<channel folder>/map.root`, `map_<key>.root`, `map_<channel>.root`,
`map_<channel>_trg.root`.

**Cross sections** (`data/cross_sections/`, copied from `limit_test/data/`, read by
`core/cross_sections.py`):

| File | Content | √s |
|---|---|---|
| `heco_cross_sections_run3.csv` | HECO spin 1/2 (`--spin spin0p5`) | 13.6 TeV |
| `heco_cross_sections_spin0_run2.csv` | HECO spin 0 (`--spin spin0`) | 13 TeV |

The charge there is in units of e/3 (`charge = 3` ⇒ Q = 1e), converted on loading.
The CSVs cover 17 masses (100 → 2800) and Q = 1e → 30e, hence the whole produced
grid.

**Luminosity scenarios**: `run3` = 376.81 fb⁻¹, `run23` = 476.81 fb⁻¹ (Run 2+3,
the value of `extrap.py`). `--limit-lumi` takes any other value.

## Outputs

```
results/limits/
├── <channel folder>/<spin>/excl_<scenario>.pdf
└── xsec/
    ├── xsec_vs_mass_<spin>.pdf      every charge, in fb
    └── xsec_by_charge_<spin>.pdf    one panel per charge, with uncertainties

/scratch/cms/xmadre/MCP_analysis/limits/
└── <channel folder>/<spin>/npred_<scenario>.root   TH2D N_pred and r
```

The channel folders are those of `stages/efficiency_map` (`Muon/`, `Tau/`, `Comb/`):
`limits.py` imports `core.selection` so as not to duplicate the names and labels.
The TH2Ds keep the binning of the input map, so `N_pred` and `r` stay overlayable
on the map they come from.

## What changes with respect to `limit_test/scripts`

1. **The points are placed at their true coordinates**, not at the bin centre.
   `extrap.py` drew `r` at the bin centres (`x_centers`), so the 100 GeV point
   showed up at 150 GeV and charge 1e at 1.5e — the whole contour was shifted by
   half a bin upwards. On the same reference map, the `r = 1` contour now crosses
   1530 GeV at Q = 1e against ~1730 before: that is exactly this shift, the
   underlying `r` field is identical.
2. **The whole grid**, 16 masses × 9 charges instead of 9 × 8, and the 3 channels
   instead of the 2 AOD maps.
3. **The zero-efficiency points are shown** (red crosses) instead of being silently
   removed from the interpolation: `r` is infinite there, the sample exists, the
   absence of contour in that area is a result.
4. **CMS style** (`coffea/plot_style.py`) and PDF, like the rest of the framework.
5. A single command instead of a set of constants to uncomment at the top of
   `extrap.py`.

## Caveats

- The spin 0 cross sections are at **13 TeV** while the maps are **13.6 TeV**
  samples: the spin 0 contour mixes the two, as `extrap.py` already did. To redo
  as soon as a Run 3 spin 0 set exists.
- The map efficiencies are unweighted (see `stages/efficiency_map/README.md`).
- The ATLAS Run 2 curve drawn in red is the spin 1/2 limit of `extrap.py`
  (6 points hard-coded in `plotting.ATLAS_RUN2`); it is overlaid on both spins,
  as before.

## Current results

Combined channels, spin 1/2, 476.81 fb⁻¹ — largest excluded mass:

| Q [e] | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|
| `comb` (loose muon + tau) | 1467 | 1834 | 1790 | 1944 | 2165 | 2320 | > 2400 | > 2400 | > 2400 |

The dip at Q = 3e comes from the efficiencies: the muon efficiency peaks at 2e then
drops (0.29 → 0.08 → 0.02 from 2e to 4e at 1200 GeV), and the tau channel only
takes over from 4e (0.010 → 0.084 on the same points). At 3e neither carries,
see the maps of `stages/efficiency_map`.
