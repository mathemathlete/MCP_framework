# CRAB production — HSCP ntuplizer

`submit_crab_production.sh` submits one CRAB task per dataset of a list, deriving
`isData` / `isAOD` / `year` / `era` from the dataset name.

Every launch goes into a **new version** (v1, v2, …): running the same command
again later never overwrites the previous production.

## Prerequisites

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
cd /mnt/grid/home/xmadre/work/CMSSW_15_0_19/src && cmsenv && cd -
source /cvmfs/cms.cern.ch/common/crab-setup.sh
voms-proxy-init -voms cms -rfc -valid 192:00
```

## Running

```bash
cd /mnt/grid/home/xmadre/work/analysis_MCP/framework/production

# MCP spin 1/2 signal MC: 144 datasets (charges 1-9e x 16 masses)
./submit_crab_production.sh -d datasets/mc_signal.txt -t mc -p MCP_spin0p5 -j 6

# data
./submit_crab_production.sh -d datasets/data_2025.txt -t data -p Run2025C
```

### Run 3 2024 backgrounds

```bash
# Drell-Yan powheg, MLL bins 200 -> 6000+: 21 datasets, ~1100 files, ~31M events
./submit_crab_production.sh -d datasets/mc_bkg_DY_2024.txt -t mc -p BKG_DY_2024

# inclusive W+jets (equivalent of the Run 2 WJetsToLNu, split by flavour in 2024):
# 3 datasets, ~38400 files, ~1.59G events
./submit_crab_production.sh -d datasets/mc_bkg_WJets_2024.txt -t mc -p BKG_WJets_2024 -j 6
```

`mc_bkg_WJets_PTLNu_2024.txt` (1J/2J x pT(lnu) bins, ~59900 files) is an
alternative to the inclusive sample for the high-pT tails: do not combine the two.
The background ntuples are stored under `bkg/<process>/` (e.g. `bkg/DYto2Mu/`).
The cross sections are in `framework/data/cross_sections/bkg_*_2024.csv` (see the
README of that folder).

`-j 6` groups 6 files per job: ~3400 input files, hence ~560 jobs instead of
~3400 with the default `-j 1`. `--splitting Automatic` is an alternative.

Always do a `--dry-run` first: the crabConfigs are written without submitting
anything, and can be reviewed in `crab_configs/<prod>/<version>/`.

`./submit_crab_production.sh -h` lists every option.

## Running again later

The same command goes into the next version:

```bash
./submit_crab_production.sh -d datasets/mc_signal.txt -t mc -p MCP_spin0p5 -j 6   # -> v1
./submit_crab_production.sh -d datasets/mc_signal.txt -t mc -p MCP_spin0p5 -j 6   # -> v2
```

The dataset list used is copied to `logs/<prod>/<version>/datasets.txt`, so what a
version processed is always known.

To complete an existing version instead of creating a new one (for instance if
part of the submissions failed), give the version: the tasks already submitted
are skipped.

```bash
./submit_crab_production.sh -d datasets/mc_signal.txt -t mc -p MCP_spin0p5 -v v1 -j 6
```

## Monitoring

`--status` queries every task of a version (8 in parallel) and prints a table,
one line per task:

```bash
./submit_crab_production.sh -p MCP_spin0p5 --status          # latest version
./submit_crab_production.sh -p MCP_spin0p5 -v v1 --status
```

```
TASK                                 STATE        JOBS   FIN  RUN IDLE  TRANS  FAIL
HSCP_Par-S-0p5-M-1800-Q-27_...        SUBMITTED     200   100   50   50      0     0
HSCP_Par-S-0p5-M-1800-Q-24_...        COMPLETED      24    24    0    0      0     0

jobs   : 274 | finished 164 (59.9%) running 50 idle 50 transferring 5 failed 5 other 0
tasks  : 144 | SUBMITTED=140 COMPLETED=3 FAILED=1
```

- `logs/<prod>/<version>/status.csv`: the same table as CSV
- `logs/<prod>/<version>/status/<task>.txt`: the raw `crab status` output, to read
  when a task is `FAILED` or `ERROR`
- the tasks with `failed` jobs are listed at the end of the output with the
  matching `crab resubmit` command, ready to copy-paste

One task at a time, directly with crab:

```bash
crab status -d crab_projects/MCP_spin0p5/v1/crab_<task>
crab resubmit -d crab_projects/MCP_spin0p5/v1/crab_<task>
```

## Storage on T2_FR_IPHC

The ntuples stay on the SE (`sbgdcache.in2p3.fr`, PFN `/cms/phedex/store/...`),
ordered by charge and mass:

```
/store/user/xmadre/HSCP/<prod>/<version>/MCP_spin0p5/Q-<1..9>e/M-<mass>/
    <primaryDataset>/<prod>_<version>/<timestamp>/0000/*.root
```

The last four levels are imposed by CRAB.

Since the `<timestamp>` is unpredictable, `--catalog` scans the SE and writes the
index to give to the analysis code:

```bash
./submit_crab_production.sh -p MCP_spin0p5 --catalog          # latest version
./submit_crab_production.sh -p MCP_spin0p5 -v v1 --catalog
```

- `logs/<prod>/<version>/catalog.csv`: `spin,charge_e,mass_gev,dataset,n_files,dir`
  sorted by charge then mass, `dir` being a full xrootd URL
- `logs/<prod>/<version>/files.txt`: every xrootd URL of the ntuples, one per line

There is no POSIX mount of the dCache on the UIs: the files are read over xrootd
(`root://sbgdcache.in2p3.fr//cms/phedex/store/...`), which ROOT does natively.

## Layout

```
datasets/                       dataset lists
                                mc_signal.txt = MCP spin 1/2, charges 1-9e, 16 masses
crab_configs/<prod>/<version>/  generated crabConfigs + stage_<task>/ (inputFiles links)
crab_projects/<prod>/<version>/ CRAB work area
logs/<prod>/<version>/          datasets.txt, crab.log, status.csv, status/,
                                catalog.csv, files.txt
```

The fixed settings (CMSSW area, CERN account, storage site, memory, cores) are
constants at the top of the script, to edit if needed.

## Notes

- Under `doCrab=True`, the PSet opens the golden JSON, the dE/dx template and the
  pileup histograms by relative path: the script puts them in
  `JobType.inputFiles` **and** submits from `stage_<task>/`, because CRAB evaluates
  the PSet in the current directory.
- 2022/2023 MC requires `--era` (the pileup is indexed by grouped era there).
- Data: `LumiBased`/100 lumis + the year's golden JSON as `lumiMask`, so that CRAB
  does not create jobs on lumis outside the golden JSON. MC: `FileBased`/1 file.
- The MCP datasets have disk replicas on many T1/T2s: neither a Rucio rule nor
  remote reading is needed.
- `Q-<n>` in the dataset names is in units of e/3: `Q-27` = 9e.
