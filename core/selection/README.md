# MCP selections

The `core.selection` package: selection classes applied to the MiniAOD ntuples
(`HSCPMiniAODAnalyzer/Events`). Used by every stage of `stages/`:

```python
from core.selection import SELECTIONS, get_selection

selection = get_selection("muon")
mask = selection.event_mask(events)

from core.selection import ANALYSES, get_analysis

analysis = get_analysis("muon")
packed, best = analysis.packed_selection(events)
selected = packed.all(*analysis.cut_names())
```

| File | Role |
|---|---|
| `cuts.py` | Reads `config/selections.json`: `Cut`, `Channel`. |
| `candidates.py` | Branches → canonical fields (`Candidates`, `MiniaodCandidates`). |
| `selection.py` | `Selection`, `CombinedSelection`: masks, best candidate, cutflow. |
| `analysis.py` | `Analysis` (skeleton, PackedSelection, regions), `MuonAnalysis`, `TauAnalysis`. |
| `__init__.py` | Registry: `CHANNELS`, `COMBINED`, `SELECTIONS`, `ANALYSES`, `get_selection()`, `get_analysis()`. |

## Architecture

A **selection = one channel × one source**, two independent axes:

```
Candidates (ABC)                    Channel  <- config/selections.json
└── MiniaodCandidates                          (cuts.py)
        │                               │
        └───────── Selection ───────────┘
                get_selection("muon")
```

- `Candidates.build(events)` reads the ntuple and returns a candidate record with
  **canonical field names**. This is where, and the only place where, the branch
  translation lives. Adding a source (NanoAOD) = one `Candidates` class.
- `Channel` is read from `config/selections.json` by `cuts.py`: label, plot folder,
  triggers and ordered list of cuts. Adding or changing a channel is done
  **only in the JSON**, without touching the code.
- `Selection` provides `event_mask()`, `best_candidate()` and `cutflow()`.

The canonical field → branch table is in the docstring of `candidates.py`.

## Writing a cut

`config/selections.json`: the preselection, then a channel and its cuts, then the
next channel. A cut is a string `"observable operator value"`, the observable being
a canonical field; the order of the list is the order of the cutflow:

```json
"preselection": {
  "cuts": [
    "chi2 < 5",
    "pt > 50"
  ]
},

"muon": {
  "label": "muon channel",
  "plot_dir": "Muon",
  "triggers": ["HLT_Mu50", "HLT_IsoMu24", "HLT_IsoMu27"],
  "objects": {"pf_type": 13, "muon_id": "loose"},
  "cuts": [
    "Ih > 6",
    "inverse_beta > 1.25"
  ],
  "regions": {}
},
```

- `objects`: working points of the object selection, turned into cuts by the
  analysis class (`MuonAnalysis`: `pf_type`, `muon_id` loose/medium;
  `TauAnalysis`: `pf_type`, `tau_pt_min`). They come after the preselection,
  before `cuts`;
- `primary_datasets`: the data primary datasets fed by `triggers` (`Muon0`, `Muon1` for
  the muon channel, `Tau` for the tau one), compared to the backgrounds by the
  `control_plots` stage;
- `regions`: `{"SR": ["Ih > 10", ...], "CR": [...]}`, cuts ANDed together and applied
  to the most ionising candidate (largest `Ih`) left after the full selection and
  the trigger. Empty for now;

- `preselection` is applied **before** the cuts of each channel: the cutflow of a
  channel = preselection, then the channel's own cuts. It is the same list as `CUTS`
  in `coffea/test_framework/test_variable/scripts/tau_selection.py`
  (checked by `test_preselection`);
- operators: `>`, `>=`, `<`, `<=`, `==`, `!=` (spaces optional);
- value: a number, or `true`/`false` (booleans: `==` or `!=` only);
- the cuts are chained with AND;
- an entry with `combine` instead of `cuts` is a combination (see below).

`config/cut_labels.json` (optional) gives the text of the cutflow plots, per cut:
`"pt > 50": "$p_T > 50$"`. A missing cut is displayed as written. LaTeX
backslashes must be doubled there (`"$\\chi^2 < 5$"`), as JSON requires.

A badly written cut, an unknown key or an unknown observable makes the run fail
with an explicit message, never silently.

## The three channels

| Channel | Muon identification | Trigger | Plots in |
|---|---|---|---|
| `muon` | `LooseMuon` (`Muon_isLoose`) | yes | `Muon/` |
| `tau` | — | yes (3 tau paths) | `Tau/` |
| `comb` | muon OR tau, muon has priority | that of each channel | `Comb/` |

The muon channel uses the **loose** identification (`"muon_id": "loose"`). To go
back to the medium channel (`MediumMuon`), set `"muon_id": "medium"`.

## The combined channel

`CombinedSelection` ORs several channels, **the first one that fires wins**:

```json
"comb": {
  "label": "muon + tau combined",
  "plot_dir": "Comb",
  "combine": ["muon", "tau"]
},
```

The order in `combine` is the priority. Adding a combination is one more entry in
`selections.json`.

**For the map, the priority changes nothing**: an event counts once, whichever
channel selected it, so the combined efficiency is that of the OR. It decides two
things:

- which candidate `best_candidate()` returns when an event passes both.
  Muon and tau select **mutually exclusive** candidates (`pfType` 13 vs 211), so
  an event can only pass both through two different candidates — exactly the case
  the rule settles;
- the attribution in the summary (`muon kept` / `tau kept`).

The "cutflow" of the combined channel is not one: the two parts do not have the
same list of cuts, so a single cumulative sequence would make no sense.
`CombinedSelection.cutflow()` outputs instead an **overlap summary** —
`muon`, `tau`, `muon kept`, `tau kept`, `combined` — from which the gain of the
combination and the size of the overlap (`tau` − `tau kept`) can be read. The y axis
of the plot is labelled accordingly (`Selection.cutflow_ylabel`).

## Indexing of the MiniAOD collections

The main pitfall. Not all branches are parallel:

- `IsoTrack_*` and `DeDx_*` only have an entry for the HSCP candidates with a
  track (`HSCP_hasTrack`) — `nIsoTrack` entries, not `HSCP_n`;
- `Muon_*` only has an entry for those with an associated muon (`HSCP_hasMuon`).

`align_to_candidates()` spreads them back onto the HSCP candidate index, filling
the gaps with a value that fails the selection. Without it,
`Muon_time_inverseBeta[i]` does not correspond to the same candidate as
`IsoTrack_pt[i]` as soon as one candidate of the event has no muon.

Also beware of `Muon_*` (capitalised, the muon of the HSCP candidate) vs `muon_*`
(lower case, flat dump of `slimmedMuons`): two different collections.

## Candidate ↔ tau association

A `pat::Tau` is built from `packedPFCandidates`, and the HSCP candidate *is* one
of them. The link is therefore an **object identity**, and these ntuples store it:
`IsoTrack_pfIdx` and `tau_signalChargedHadrCands_pfIdx` index the same collection.

```python
linked = ak.any(prongs == idx, axis=3) & (idx >= 0)
```

No ΔR, no tolerance, no cut to tune. `pfIdx == -1` marks a candidate without a
packed candidate reference (~12%); it can never match, the prong indices being ≥ 0.

This is what the previous version rebuilt by hand from the kinematics
(`TAU_MATCH_MODE = "constituent"`, tolerance `1e-4` in a gap of a bimodal
distribution). The fraction of linked candidates at pT > 50 is the same
(0.814 here against ~0.80 measured then): the reconstruction was right, it is
simply no longer needed.

## Two differences from the original AOD selection

1. **`dz`/`dxy` in absolute value** (`MiniaodCandidates.USE_ABS_IMPACT = True`).
   In AOD the cut was on the signed value, so ~50% of the candidates
   (those with dz/dxy < 0, down to −86 cm) passed automatically. Set the attribute
   to `False` to get the AOD behaviour back.
2. **`dedx_hits = DeDx_IhNOM`**: the `cluster_*` branches are not written in
   MiniAOD (`AddStripClusterInfo = False` in `ntuplizer_cfg.py`).

On the other hand `IsoTrack_ptErrOverPt2` is now correct in this production
(checked: exactly `ptError / PseudoTrack_pt²`) and is used directly, where the
previous version had to recompute it because the branch was filled with NaN.

## Triggers

The `triggers` list of a channel gives the HLT paths to OR;
an empty or missing list = no trigger. The HLT branches of the ntuple have **no**
version suffix (`HLT_Mu50`, not `HLT_Mu50_v15`): adding one would miss the branch.

- **muon**: `HLT_Mu50 | HLT_IsoMu24 | HLT_IsoMu27`,
  the equivalent of the AOD `passMu`.
- **tau**: `HLT_DoubleMediumDeepTauPFTauHPS35_L2NN_eta2p1`,
  `HLT_DoublePNetTauhPFJet30_Medium_L2NN_eta2p3`,
  `HLT_DoubleMediumDeepTauPFTauHPS30_L2NN_eta2p1_OneProng`.

The `trigger` row shows up in the cutflows by itself as soon as `triggers` is
not empty.

## Analyses and PackedSelection

`get_analysis(name)` returns the analysis object of a channel (`ANALYSES` lists
them); `get_selection` returns the same object, so the old API still works.
`packed_selection(events)` returns a coffea `PackedSelection` and the most ionising
candidate of each event. Its bits are **cumulative at candidate level**: the bit of
a cut means "at least one candidate passes every cut so far" (an AND of independent
bits would accept an event where two different candidates each pass one cut). Only
`all()` and `cutflow()` in the order of `cut_names()` are therefore meaningful, not
the N-1 views.

`analysis.cutflows(packed)`: the full cutflow (`"selection"`) and one per region.
Standalone test, from `framework/`:

```bash
python3.12 -m tests.test_selection                       # dummy events
python3.12 -m tests.test_selection --file <ntuple> --max-events 20000
python3.12 -m run.launch <ntuple> --to regions --channel muon --max-files 1
```
