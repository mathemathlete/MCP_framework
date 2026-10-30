# Cross sections

All read by `core/cross_sections.py`.

## HECO signal (`analyses/limits`, `--norm events` of the control plots)

| File | Content | √s |
|---|---|---|
| `heco_cross_sections_run3.csv` | HECO spin 1/2 | 13.6 TeV |
| `heco_cross_sections_spin0_run2.csv` | HECO spin 0 | 13 TeV |

Charge in units of e/3, cross section in pb. Copied from `limit_test/data/`.

## 2024 backgrounds (RunIII2024Summer24MiniAODv6)

One line per DAS dataset (`dataset` = primary name), cross section in pb. A
`split: dataset` group of a run config names its CSV with `xsec:`; every dataset of
the production must have a line.

| File | Datasets | CRAB production |
|---|---|---|
| `bkg_DY_2024.csv` | DYto2{Mu,Tau,E} powheg, 7 MLL bins from 200 to 6000+ | `BKG_DY_2024` (`mc_bkg_DY_2024.txt`) |
| `bkg_WJets_2024.csv` | Wto{E,Mu,Tau}Nu-2Jets amcatnloFXFX, inclusive | `BKG_WJets_2024` (`mc_bkg_WJets_2024.txt`) |
| `bkg_WJets_binned_2024.csv` | WtoLNu-2Jets 1J/2J × PTLNu, and WtoLNu-4Jets × MLNu (madgraph, not produced) | `mc_bkg_WJets_PTLNu_2024.txt` |

Columns: `xsec_pb`, `xsec_err_pb`, `neg_weight_frac` (fraction of negative
generator weights), plus, for the inclusive W, `genxsec_raw_pb` and `note`: there
the GenXSecAnalyzer gives the sum of the 3 flavours, divided by 3.

These are **generator** cross sections (GenXSecAnalyzer on the per-lumi products
of the MiniAOD), not NNLO reference values. Computed by
`analysis_MCP/coffea/background_estimation/genxsec/run_genxsec.py`, copied from
`analysis_MCP/coffea/background_estimation/*_RunIII2024Summer24_MiniAOD_xsec_pb.csv`.
The inclusive and binned W+jets samples overlap: never combine the two.
