#!/bin/bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CMSSW_AREA_DEFAULT="/mnt/grid/home/xmadre/work/CMSSW_15_0_19"
CERN_USER="xmadre"
STORAGE_SITE="T2_FR_IPHC"
SE_HOST="sbgdcache.in2p3.fr"
SE_PREFIX="/cms/phedex"
NUM_CORES=1
MAX_MEMORY=3000
STATUS_JOBS=8

DATASETS_FILE=""
PROD_TAG=""
VERSION=""
DATA_TYPE="auto"
UNITS_PER_JOB=""
SPLITTING=""
MAX_EVENTS="-1"
FORCE_YEAR=""
FORCE_ERA=""
MODE="submit"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: ./submit_crab_production.sh -d datasets/my_list.txt -p NAME [options]

One CRAB task per dataset in the list (blank lines and '#' ignored). Each run
goes into a new version (v1, v2, ...), so relaunching later never overwrites a
previous production: same command -> next version.

  -d, --datasets FILE      DAS dataset list, one per line
  -p, --prod NAME          production name
  -v, --version VTAG       version (default: next free one; latest for --status/--catalog)
  -t, --type data|mc|auto  default auto, inferred from the dataset name
  -j, --units-per-job N    default 100 lumis (data) / 1 file (mc)
      --splitting S        LumiBased | FileBased | Automatic
  -n, --max-events N       maxEvents per job (default -1 = all)
      --year YEAR          force the year instead of inferring it
      --era ERA            force the era (required for 2022/2023 MC)
      --status             crab status of every task, as one table
      --catalog            scan the SE and index the ntuples produced
      --dry-run            write the crabConfigs without submitting
  -h, --help

Output goes to T2_FR_IPHC, grouped by charge and mass (signal) or process (bkg):
  /store/user/xmadre/HSCP/<prod>/<version>/MCP_spin<S>/Q-<n>e/M-<m>/...
  /store/user/xmadre/HSCP/<prod>/<version>/bkg/<process>/...

Examples
  ./submit_crab_production.sh -d datasets/mc_signal.txt -t mc -p MCP_spin0p5 -j 6
  ./submit_crab_production.sh -d datasets/mc_signal.txt -t mc -p MCP_spin0p5 -j 6  # -> v2
  ./submit_crab_production.sh -p MCP_spin0p5 --status
  ./submit_crab_production.sh -p MCP_spin0p5 --catalog
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -d|--datasets)      DATASETS_FILE="$2"; shift 2 ;;
    -p|--prod)          PROD_TAG="$2"; shift 2 ;;
    -v|--version)       VERSION="$2"; shift 2 ;;
    -t|--type)          DATA_TYPE="$2"; shift 2 ;;
    -j|--units-per-job) UNITS_PER_JOB="$2"; shift 2 ;;
    --splitting)        SPLITTING="$2"; shift 2 ;;
    -n|--max-events)    MAX_EVENTS="$2"; shift 2 ;;
    --year)             FORCE_YEAR="$2"; shift 2 ;;
    --era)              FORCE_ERA="$2"; shift 2 ;;
    --status)           MODE="status"; shift ;;
    --catalog)          MODE="catalog"; shift ;;
    --dry-run)          DRY_RUN=1; shift ;;
    -h|--help)          usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

die() { echo "[error] $*" >&2; exit 1; }

[ -n "$PROD_TAG" ] || { echo "[error] -p/--prod missing" >&2; usage >&2; exit 1; }

CMSSW_AREA="${CMSSW_BASE:-$CMSSW_AREA_DEFAULT}"
NTUPLIZER="$CMSSW_AREA/src/HSCPAnalysis/Ntuplizer"
PSET="$NTUPLIZER/test/ntuplizer_cfg.py"
PROD_ROOT="$SCRIPT_DIR/crab_projects/$PROD_TAG"

versions_of() { for d in "$PROD_ROOT"/*; do [ -d "$d" ] && basename "$d"; done 2>/dev/null | sort -V; }

if [ -z "$VERSION" ]; then
  last="$(versions_of | tail -1)"
  if [ "$MODE" = "catalog" ] || [ "$MODE" = "status" ]; then
    VERSION="$last"
    [ -n "$VERSION" ] || die "no version of '$PROD_TAG' under $PROD_ROOT"
    echo "[info] using the latest version: $VERSION"
  elif [[ "$last" =~ ^v([0-9]+)$ ]]; then
    VERSION="v$(( ${BASH_REMATCH[1]} + 1 ))"
  else
    VERSION="v1"
  fi
fi

WORK_AREA="$PROD_ROOT/$VERSION"
CONFIG_DIR="$SCRIPT_DIR/crab_configs/$PROD_TAG/$VERSION"
LOG_DIR="$SCRIPT_DIR/logs/$PROD_TAG/$VERSION"
OUT_LFN_BASE="/store/user/$CERN_USER/HSCP/$PROD_TAG/$VERSION"

# readable SE sub-tree; CRAB then appends
# <primaryDataset>/<outputDatasetTag>/<timestamp>/0000/
out_subdir() {
  local name="$1"
  if [[ "$name" =~ Par-S-([0-9p]+)-M-([0-9]+)-Q-([0-9]+) ]]; then
    echo "MCP_spin${BASH_REMATCH[1]}/Q-$(( ${BASH_REMATCH[3]} / 3 ))e/M-${BASH_REMATCH[2]}"
  elif [[ "$name" =~ mchamp_Q-([0-9]+)_M-([0-9]+) ]]; then
    echo "mchamp/Q-$(( ${BASH_REMATCH[1]} / 3 ))e/M-${BASH_REMATCH[2]}"
  elif [ -n "${2:-}" ]; then
    echo "data/Run${2}${3:-}"
  else
    echo "bkg/${name%%_*}"
  fi
}

# same grouping as xparser.normalizeEra
norm_era() {
  case "$1" in
    2022) case "$2" in B|C|D) echo BCD ;; E|F|G) echo EFG ;; *) echo "$2" ;; esac ;;
    2023) case "$2" in B|C) echo BC ;; *) echo "$2" ;; esac ;;
    *) echo "$2" ;;
  esac
}

lumi_json() {
  local d="$NTUPLIZER/data/lumi"
  case "$1" in
    2017) echo "$d/Cert_294927-306462_13TeV_UL2017_Collisions17_GoldenJSON.txt" ;;
    2018) echo "$d/Cert_314472-325175_13TeV_Legacy2018_Collisions18_JSON.txt" ;;
    2022) echo "$d/Cert_Collisions2022_355100_362760_Golden.txt" ;;
    2023) echo "$d/Cert_Collisions2023_366442_370790_Golden.txt" ;;
    2024) echo "$d/Cert_Collisions2024_378981_386951_Golden.txt" ;;
    2025) echo "$d/Cert_Collisions2025_391658_398903_Golden.txt" ;;
  esac
}

# files the PSet opens by relative path when doCrab=True
sandbox_files() {
  local is_data="$1" year="$2" files=() pu glob
  if [ "$is_data" = True ]; then
    files+=("$(lumi_json "$year")")
    case "$year" in
      2017|2018) files+=("$NTUPLIZER/data/template/template_Run2.root") ;;
      *)         files+=("$NTUPLIZER/data/template/template_Run3.root") ;;
    esac
    case "$year" in
      2022|2023|2024) files+=("$NTUPLIZER/data/template/SF_dEdx_Run3.txt") ;;
    esac
  else
    [ "$year" = 2017 ] || [ "$year" = 2018 ] && files+=("$NTUPLIZER/data/template/template_Run2_MC.root")
    case "$year" in
      2017|2018) glob="PileupHistogram-goldenJSON-13tev-${year}-*ub-*bins.root" ;;
      2022|2023) glob="pileupHistogram-Cert_Collisions${year}_*era$(norm_era "$year" "$era")_*.root" ;;
      2024|2025) glob="dataPileupHistogram-${year}*.root" ;;
      *)         glob="" ;;
    esac
    for pu in "$NTUPLIZER"/data/pileup/mix_${year}_*.root $([ -n "$glob" ] && echo "$NTUPLIZER/data/pileup/$glob"); do
      [ -f "$pu" ] && files+=("$pu")
    done
  fi
  printf '%s\n' "${files[@]}"
}

py_list() { local out="" f; for f in "$@"; do out="$out'$f', "; done; echo "[${out%, }]"; }

request_name() {
  local name
  name="$(printf '%s' "${PROD_TAG}_${VERSION}_${1}_${2}" | tr -c 'A-Za-z0-9_-' '_')"
  if [ ${#name} -gt 100 ]; then
    name="${name:0:93}_$(printf '%s' "$name" | md5sum | cut -c1-6)"
  fi
  echo "$name"
}

# year/era/isData/isAOD from /primary/campaign/TIER
parse_dataset() {
  primary="$(echo "$1" | cut -d/ -f2)"
  campaign="$(echo "$1" | cut -d/ -f3)"
  local tier; tier="$(echo "$1" | cut -d/ -f4)"

  case "$tier" in *SIM*|*GEN*) is_data=False ;; *) is_data=True ;; esac
  [ "$DATA_TYPE" = data ] && is_data=True
  [ "$DATA_TYPE" = mc ] && is_data=False
  case "$tier" in AOD*) is_aod=True ;; *) is_aod=False ;; esac

  year=""; era=""
  if [ "$is_data" = True ]; then
    year="$(echo "$campaign" | sed -n 's/^Run\([0-9]\{4\}\).*/\1/p')"
    era="$(echo "$campaign" | sed -n 's/^Run[0-9]\{4\}\([A-Z]\).*/\1/p')"
  else
    case "$campaign" in
      *UL17*|*2017*) year=2017 ;; *UL18*|*2018*) year=2018 ;;
      *2022*) year=2022 ;; *2023*) year=2023 ;; *2024*) year=2024 ;; *2025*) year=2025 ;;
    esac
  fi
  [ -n "$FORCE_YEAR" ] && year="$FORCE_YEAR"
  [ -n "$FORCE_ERA" ] && era="$FORCE_ERA"

  [ -n "$year" ] || { echo "[skip] $1 : year not recognized, use --year"; return 1; }
  if [ "$is_data" = True ] && [ -z "$era" ]; then
    echo "[skip] $1 : era not recognized (required for data), use --era"; return 1
  fi
  if [ "$is_data" = False ] && { [ "$year" = 2022 ] || [ "$year" = 2023 ]; } && [ -z "$era" ]; then
    echo "[skip] $1 : $year MC needs an era for pileup, use --era"; return 1
  fi
}

do_submit() {
  [ -n "$DATASETS_FILE" ] || { echo "[error] -d/--datasets missing" >&2; usage >&2; exit 1; }
  [ -f "$DATASETS_FILE" ] || die "dataset list not found: $DATASETS_FILE"
  [ -f "$PSET" ] || die "PSet not found: $PSET"
  command -v crab >/dev/null || die "crab not found: source /cvmfs/cms.cern.ch/common/crab-setup.sh"
  local left; left="$(voms-proxy-info -timeleft 2>/dev/null)"
  [ -n "$left" ] && [ "$left" -ge 3600 ] 2>/dev/null \
    || die "proxy missing or under 1h: voms-proxy-init -voms cms -rfc -valid 192:00"
  [ -n "${CMSSW_BASE:-}" ] || echo "[warn] CMSSW_BASE unset, using $CMSSW_AREA (run 'cmsenv')"

  mkdir -p "$WORK_AREA" "$CONFIG_DIR" "$LOG_DIR"
  cp "$DATASETS_FILE" "$LOG_DIR/datasets.txt"

  echo "production : $PROD_TAG / $VERSION"
  echo "PSet       : $PSET"
  echo "output     : $STORAGE_SITE:$OUT_LFN_BASE"
  echo

  local n_ok=0 n_fail=0 n_skip=0
  while IFS= read -r ds; do
    ds="$(echo "$ds" | sed 's/#.*//' | xargs)"
    [ -z "$ds" ] && continue
    parse_dataset "$ds" || { n_skip=$((n_skip+1)); continue; }

    local req splitting units lumi_mask out_lfn stage cfg params=()
    req="$(request_name "$primary" "$campaign")"
    if [ -d "$WORK_AREA/crab_$req" ]; then
      echo "[skip] $req (already submitted in $VERSION)"; n_skip=$((n_skip+1)); continue
    fi

    if [ "$is_data" = True ]; then
      splitting="${SPLITTING:-LumiBased}"; units="${UNITS_PER_JOB:-100}"
      lumi_mask="$(lumi_json "$year")"
    else
      splitting="${SPLITTING:-FileBased}"; units="${UNITS_PER_JOB:-1}"
      lumi_mask=""
    fi
    out_lfn="$OUT_LFN_BASE/$(out_subdir "$primary" "$([ "$is_data" = True ] && echo "$year")" "$era")"

    params=("doCrab=True" "isData=$is_data" "isAOD=$is_aod" "year=$year")
    [ -n "$era" ] && params+=("era=$era")
    [ "$MAX_EVENTS" != -1 ] && params+=("maxEvents=$MAX_EVENTS")

    mapfile -t sbx < <(sandbox_files "$is_data" "$year")

    cfg="$CONFIG_DIR/crabConfig_${req}.py"
    {
      echo "from CRABClient.UserUtilities import config"
      echo "config = config()"
      echo "config.General.requestName = '$req'"
      echo "config.General.workArea = '$WORK_AREA'"
      echo "config.General.transferOutputs = True"
      echo "config.General.transferLogs = False"
      echo "config.JobType.pluginName = 'Analysis'"
      echo "config.JobType.psetName = '$PSET'"
      echo "config.JobType.pyCfgParams = $(py_list "${params[@]}")"
      echo "config.JobType.inputFiles = $(py_list "${sbx[@]}")"
      echo "config.JobType.numCores = $NUM_CORES"
      echo "config.JobType.maxMemoryMB = $MAX_MEMORY"
      echo "config.JobType.allowUndistributedCMSSW = True"
      echo "config.Data.inputDataset = '$ds'"
      echo "config.Data.inputDBS = 'global'"
      echo "config.Data.splitting = '$splitting'"
      [ "$splitting" != Automatic ] && echo "config.Data.unitsPerJob = $units"
      echo "config.Data.outLFNDirBase = '$out_lfn'"
      echo "config.Data.publication = False"
      echo "config.Data.outputDatasetTag = '${PROD_TAG}_${VERSION}'"
      [ -n "$lumi_mask" ] && echo "config.Data.lumiMask = '$lumi_mask'"
      echo "config.Site.storageSite = '$STORAGE_SITE'"
    } > "$cfg"

    # CRAB evaluates the PSet in the cwd, and the PSet opens some of these by
    # relative path when doCrab=True: submit from a dir that holds them
    stage="$CONFIG_DIR/stage_$req"
    mkdir -p "$stage"
    for f in "${sbx[@]}"; do [ -f "$f" ] && ln -sf "$f" "$stage/$(basename "$f")"; done

    echo "=== $req"
    echo "    isData=$is_data isAOD=$is_aod year=$year era=${era:-none} $splitting/$units -> $out_lfn"
    if [ "$DRY_RUN" -eq 1 ]; then echo "    [dry-run] $cfg"; continue; fi

    if (cd "$stage" && crab submit -c "$cfg") 2>&1 | tee -a "$LOG_DIR/crab.log" | sed 's/^/    /'; then
      n_ok=$((n_ok+1))
    else
      n_fail=$((n_fail+1))
    fi
  done < "$DATASETS_FILE"

  echo
  echo "submitted: $n_ok | failed: $n_fail | skipped: $n_skip"
  [ "$n_fail" -gt 0 ] && echo "failures : $LOG_DIR/crab.log"
  echo "status   : ./submit_crab_production.sh -p $PROD_TAG -v $VERSION --status"
}

# one task -> "name state total finished running idle transferring failed other"
status_one() {
  local dir="$1" out="$2" name raw
  name="$(basename "$dir")"
  raw="$STATUS_DIR/$name.txt"

  crab status -d "$dir" > "$raw" 2>&1
  if ! grep -qE '^(Status on the|Jobs status)' "$raw"; then
    printf '%s\tERROR\t0\t0\t0\t0\t0\t0\t0\n' "$name" > "$out"
    printf '!' >&2
    return
  fi

  awk -v name="$name" '
    /^Status on the CRAB server:/ { sub(/^[^:]*:[ \t]*/, ""); gsub(/[ \t]+$/, ""); server = $0 }
    /^Status on the scheduler:/   { sub(/^[^:]*:[ \t]*/, ""); gsub(/[ \t]+$/, ""); sched = $0 }
    /^Publication/ { pub = 1 }
    !pub && /%[ \t]*\([ \t]*[0-9]+\/[0-9]+\)/ {
      line = $0; gsub(/[()\/]/, " ", line)
      n = split(line, f); st = ""
      for (i = 2; i <= n; i++) if (f[i] ~ /%$/) { st = f[i-1]; c = f[i+1] + 0; tot = f[i+2] + 0; break }
      if (st ~ /^(finished|failed|running|idle|transferring|transferred|unsubmitted|cooloff|held|toRetry|killed)$/) {
        cnt[st] += c
        if (tot > total) total = tot
      }
    }
    END {
      state = (sched != "" ? sched : (server != "" ? server : "UNKNOWN"))
      other = total - cnt["finished"] - cnt["running"] - cnt["idle"] - cnt["transferring"] - cnt["failed"]
      if (other < 0) other = 0
      printf "%s\t%s\t%d\t%d\t%d\t%d\t%d\t%d\t%d\n", name, state, total,
             cnt["finished"], cnt["running"], cnt["idle"], cnt["transferring"], cnt["failed"], other
    }
  ' "$raw" > "$out"
  printf '.' >&2
}

do_status() {
  command -v crab >/dev/null || die "crab not found: source /cvmfs/cms.cern.ch/common/crab-setup.sh"
  [ -d "$WORK_AREA" ] || die "no work area: $WORK_AREA"
  local left; left="$(voms-proxy-info -timeleft 2>/dev/null)"
  [ -n "$left" ] && [ "$left" -ge 60 ] 2>/dev/null \
    || die "proxy missing or expired: voms-proxy-init -voms cms -rfc -valid 192:00"

  local tasks=()
  mapfile -t tasks < <(find "$WORK_AREA" -mindepth 1 -maxdepth 1 -type d -name 'crab_*' | sort)
  [ "${#tasks[@]}" -gt 0 ] || die "no CRAB task under $WORK_AREA"

  STATUS_DIR="$LOG_DIR/status"
  mkdir -p "$STATUS_DIR"
  T_TOT=0; T_FIN=0; T_RUN=0; T_IDLE=0; T_TRANS=0; T_FAIL=0; T_OTHER=0
  declare -A S_CNT=()
  local tmp; tmp="$(mktemp -d)"

  echo "production : $PROD_TAG / $VERSION"
  echo "tasks      : ${#tasks[@]}, queried $STATUS_JOBS at a time (slow, one crab call each)"

  local i=0 t
  for t in "${tasks[@]}"; do
    while [ "$(jobs -rp | wc -l)" -ge "$STATUS_JOBS" ]; do wait -n 2>/dev/null || sleep 1; done
    status_one "$t" "$tmp/$(printf '%04d' "$i")" &
    i=$((i+1))
  done
  wait
  echo; echo

  local prefix="crab_${PROD_TAG}_${VERSION}_"
  printf '%-52s %-13s %6s %6s %5s %5s %6s %6s\n' TASK STATE JOBS FIN RUN IDLE TRANS FAIL
  local name state tot fin run idle trans fail other short failed_tasks=()
  while IFS=$'\t' read -r name state tot fin run idle trans fail other; do
    short="${name#"$prefix"}"; short="${short#crab_}"
    [ "${#short}" -gt 52 ] && short="${short:0:49}..."
    printf '%-52s %-13s %6s %6s %5s %5s %6s %6s\n' "$short" "$state" "$tot" "$fin" "$run" "$idle" "$trans" "$fail"
    [ "$fail" -gt 0 ] 2>/dev/null && failed_tasks+=("$name")
    T_TOT=$((T_TOT+tot)); T_FIN=$((T_FIN+fin)); T_RUN=$((T_RUN+run))
    T_IDLE=$((T_IDLE+idle)); T_TRANS=$((T_TRANS+trans)); T_FAIL=$((T_FAIL+fail)); T_OTHER=$((T_OTHER+other))
    S_CNT["$state"]=$(( ${S_CNT["$state"]:-0} + 1 ))
  done < <(cat "$tmp"/* 2>/dev/null)

  echo
  local pct="-"
  [ "$T_TOT" -gt 0 ] && pct="$(awk -v a="$T_FIN" -v b="$T_TOT" 'BEGIN{printf "%.1f", 100*a/b}')%"
  echo "jobs   : $T_TOT | finished $T_FIN ($pct) running $T_RUN idle $T_IDLE transferring $T_TRANS failed $T_FAIL other $T_OTHER"
  local s line=""
  for s in "${!S_CNT[@]}"; do line="$line $s=${S_CNT[$s]}"; done
  echo "tasks  : ${#tasks[@]} |$line"

  { echo "task,state,jobs,finished,running,idle,transferring,failed,other"
    cat "$tmp"/* 2>/dev/null | tr '\t' ','; } > "$LOG_DIR/status.csv"
  rm -rf "$tmp"

  echo "table  : $LOG_DIR/status.csv"
  echo "logs   : $STATUS_DIR/<task>.txt"

  if [ "${#failed_tasks[@]}" -gt 0 ]; then
    echo
    echo "${#failed_tasks[@]} task(s) with failed jobs:"
    for t in "${failed_tasks[@]}"; do echo "  crab resubmit -d $WORK_AREA/$t"; done
  fi
}

# index the ntuples on the SE, resolving CRAB's unpredictable <timestamp>
do_catalog() {
  command -v xrdfs >/dev/null || die "xrdfs not found"
  mkdir -p "$LOG_DIR"
  local base="$SE_PREFIX$OUT_LFN_BASE" url="root://$SE_HOST/" raw csv flist d ds q m spin n
  csv="$LOG_DIR/catalog.csv"; flist="$LOG_DIR/files.txt"; raw="$(mktemp)"

  echo "scanning $url$base"
  xrdfs "$SE_HOST" ls -R "$base" 2>/dev/null | grep '\.root$' > "$raw"
  [ -s "$raw" ] || { rm -f "$raw"; die "no .root under $base (submitted? finished?)"; }
  sed "s#^#$url#" "$raw" > "$flist"

  echo "spin,charge_e,mass_gev,dataset,n_files,dir" > "$csv"
  while IFS= read -r d; do
    n="$(grep -c "^$d/" "$raw")"
    ds="$(echo "$d" | sed "s#^$base/##" | awk -F/ -v tag="${PROD_TAG}_${VERSION}" '{for(i=2;i<=NF;i++) if ($i == tag) {print $(i-1); exit}}')"
    spin=""; q=""; m=""
    if [[ "$ds" =~ Par-S-([0-9p]+)-M-([0-9]+)-Q-([0-9]+) ]]; then
      spin="${BASH_REMATCH[1]}"; m="${BASH_REMATCH[2]}"; q=$(( ${BASH_REMATCH[3]} / 3 ))
    elif [[ "$ds" =~ mchamp_Q-([0-9]+)_M-([0-9]+) ]]; then
      q=$(( ${BASH_REMATCH[1]} / 3 )); m="${BASH_REMATCH[2]}"
    fi
    echo "$spin,$q,$m,$ds,$n,$url$d"
  done < <(sed 's#/[^/]*$##' "$raw" | sort -u) | sort -t, -k2,2n -k3,3n >> "$csv"
  rm -f "$raw"

  echo "datasets: $(( $(wc -l < "$csv") - 1 )) | files: $(wc -l < "$flist")"
  echo "index   : $csv"
  echo "files   : $flist"
}

case "$MODE" in
  submit)  do_submit ;;
  status)  do_status ;;
  catalog) do_catalog ;;
esac
