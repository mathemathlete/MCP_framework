"""SLURM submission, from the login node.

Compute nodes only mount /home-pbs: `submit` syncs the framework, its results
and the scratch under SLURM_BASE and runs run.launch there in a job, which
submits the dask workers as nested jobs. `fetch` brings results and scratch back.
"""

import os
import re
import shlex
import shutil
import subprocess

from core.executor import PARTITION
from core.paths import (COFFEA, FRAMEWORK, RESULTS, SCRATCH, SLURM_BASE, SLURM_FRAMEWORK,
                        SLURM_LOGS, SLURM_PROXY, SLURM_PYTHON, SLURM_SCRATCH)

DEFAULT_WALLTIME = "04:00:00"
WALLTIME_RE = re.compile(r"^\d+:\d\d:\d\d$")
JOB_MEMORY = "8G"
CODE_EXCLUDES = ("__pycache__/", "/results/", "/production/crab_projects/",
                 "/production/crab_configs/")

JOB = """#!/bin/bash
#SBATCH --job-name=mcp_analyses
#SBATCH --partition={partition}
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem={memory}
#SBATCH --time={walltime}
#SBATCH --chdir={framework}
#SBATCH --output={logs}/analyses_%j.out
#SBATCH --error={logs}/analyses_%j.err
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
export X509_USER_PROXY={proxy}
export MCP_SCRATCH={scratch}
export MCP_SLURM_WALLTIME={walltime}
export MPLCONFIGDIR={base}/.matplotlib
exec {python} -u -m run.launch {args}
"""


def rsync(src, dst, *options):
    dst.mkdir(parents=True, exist_ok=True)
    subprocess.run(["rsync", "-a", *options, f"{src}/", f"{dst}/"], check=True)


def copy_proxy(walltime):
    proxy = os.environ.get("X509_USER_PROXY", f"/tmp/x509up_u{os.getuid()}")
    valid = walltime.rsplit(":", 1)[0]
    status = subprocess.run(["voms-proxy-info", "--file", proxy, "--exists", "--valid", valid],
                            capture_output=True).returncode
    if status:
        raise SystemExit(f"[error] no proxy at {proxy} valid for {valid} more, "
                         "run: voms-proxy-init --voms cms --valid 192:00")
    SLURM_PROXY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(proxy, SLURM_PROXY)
    os.chmod(SLURM_PROXY, 0o600)


def push():
    print(f"[slurm] sync {FRAMEWORK} -> {SLURM_FRAMEWORK}", flush=True)
    rsync(FRAMEWORK, SLURM_FRAMEWORK, "--delete", *(f"--exclude={e}" for e in CODE_EXCLUDES))
    rsync(COFFEA, SLURM_FRAMEWORK.parent / COFFEA.name, "--include=plot_style.py", "--exclude=*")
    rsync(RESULTS, SLURM_FRAMEWORK / RESULTS.name, "--update")
    if SCRATCH.exists():
        rsync(SCRATCH, SLURM_SCRATCH, "--update", "--exclude=.chunks/")


def fetch():
    if not SLURM_FRAMEWORK.exists():
        raise SystemExit(f"[error] nothing at {SLURM_FRAMEWORK}, submit with --slurm first")
    print(f"[slurm] fetch {SLURM_FRAMEWORK / RESULTS.name} -> {RESULTS}", flush=True)
    rsync(SLURM_FRAMEWORK / RESULTS.name, RESULTS, "--update")
    if SLURM_SCRATCH.exists():
        print(f"[slurm] fetch {SLURM_SCRATCH} -> {SCRATCH}", flush=True)
        rsync(SLURM_SCRATCH, SCRATCH, "--update", "--exclude=.chunks/")


def submit(argv, walltime, wait):
    """Run `python -m run.launch <argv>` in a SLURM job."""
    if not WALLTIME_RE.match(walltime):
        raise SystemExit(f"[error] walltime '{walltime}' is not HH:MM:SS")
    if not SLURM_PYTHON.exists():
        raise SystemExit(f"[error] no python at {SLURM_PYTHON} (MCP_SLURM_PYTHON)")
    copy_proxy(walltime)
    push()
    SLURM_LOGS.mkdir(parents=True, exist_ok=True)
    script = JOB.format(partition=PARTITION, memory=JOB_MEMORY, walltime=walltime,
                        base=SLURM_BASE, framework=SLURM_FRAMEWORK, logs=SLURM_LOGS,
                        proxy=SLURM_PROXY, scratch=SLURM_SCRATCH, python=SLURM_PYTHON,
                        args=shlex.join(argv))
    print(f"[slurm] run.launch {shlex.join(argv)}", flush=True)

    sbatch = ["sbatch", "--parsable", *(["--wait"] if wait else [])]
    if wait:
        status = subprocess.run(sbatch, input=script, text=True).returncode
        fetch()
        if status:
            raise SystemExit(f"[error] the job failed (exit {status}), logs in {SLURM_LOGS}")
        return

    out = subprocess.run(sbatch, input=script, text=True, capture_output=True)
    if out.returncode:
        raise SystemExit(f"[error] sbatch failed: {out.stderr.strip()}")
    job = out.stdout.strip().split(";")[0]
    print(f"[slurm] job {job}, log {SLURM_LOGS}/analyses_{job}.out\n"
          "follow it:  squeue -u $USER\n"
          f"            tail -f {SLURM_LOGS}/analyses_{job}.out\n"
          "once done:  python3.12 -m run.launch --fetch")
