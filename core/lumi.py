"""Recorded luminosity of a set of lumisections: brilcalc (web cache, BRIL normtag).
One result per set of lumisections, cached under SCRATCH/lumi/ with its JSON mask."""

import hashlib
import json
import subprocess

import numpy as np

from .paths import SCRATCH

NORMTAG = "/cvmfs/cms-bril.cern.ch/cms-lumi-pog/Normtags/normtag_BRIL.json"
CACHE = SCRATCH / "lumi"
LS_BITS = 20


def codes(runs, blocks):
    """(run, luminosityBlock) -> one int64 per lumisection."""
    return (np.asarray(runs, dtype=np.int64) << LS_BITS) | np.asarray(blocks, dtype=np.int64)


def compact(lumi_codes):
    """-> {run: [[first, last], ...]}, the format of the golden JSON."""
    out = {}
    for code in np.unique(lumi_codes).tolist():
        run, block = code >> LS_BITS, code & ((1 << LS_BITS) - 1)
        ranges = out.setdefault(str(run), [])
        if ranges and ranges[-1][1] == block - 1:
            ranges[-1][1] = block
        else:
            ranges.append([block, block])
    return out


def _brilcalc(mask):
    command = ["brilcalc", "lumi", "-c", "web", "-i", str(mask), "--normtag", NORMTAG,
               "-u", "/fb", "--output-style", "csv"]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit("[error] brilcalc not found: pip install --user brilws") from None
    if result.returncode:
        raise SystemExit(f"[error] {' '.join(command)}\n{result.stderr}")
    lines = result.stdout.splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("#nfill"))
    summary = dict(zip(lines[header].lstrip("#").split(","),
                       lines[header + 1].lstrip("#").split(",")))
    unknown = next((line.split(":", 1)[1].strip() for line in lines
                    if line.startswith("#(run,ls) in json but not in results")), "[]")
    return summary, unknown


def recorded(lumi_codes):
    """fb^-1 recorded in these lumisections."""
    lumi_codes = np.unique(np.asarray(lumi_codes, dtype=np.int64))
    key = hashlib.sha1(lumi_codes.tobytes()).hexdigest()[:16]
    cached = CACHE / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())["recorded"]

    CACHE.mkdir(parents=True, exist_ok=True)
    mask = CACHE / f"{key}_lumis.json"
    mask.write_text(json.dumps(compact(lumi_codes)))
    print(f"[info] brilcalc on {len(lumi_codes)} lumisections, {mask}", flush=True)
    summary, unknown = _brilcalc(mask)
    if unknown != "[]":
        print(f"[warn] lumisections unknown to brilcalc: {unknown[:200]}")
    value = float(summary["totrecorded(/fb)"])
    cached.write_text(json.dumps({"recorded": value, "n_lumisections": len(lumi_codes),
                                  "brilcalc": summary, "unknown": unknown}, indent=2))
    return value
