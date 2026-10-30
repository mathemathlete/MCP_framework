"""coffea executors: one process, local processes, or dask workers as SLURM jobs.

`slurm` needs to run inside a SLURM job, the workers cannot reach the login
node: `python3.12 -m run.launch --slurm N` submits it (run/slurm.py).
"""

import atexit
import os
import sys

from coffea import processor
from coffea.nanoevents import BaseSchema

from .paths import FRAMEWORK, SCRATCH, SLURM_BASE, SLURM_LOGS, SLURM_PROXY

EXECUTORS = ("iterative", "futures", "slurm")
DEFAULT_EXECUTOR = "futures"
DEFAULT_WORKERS = 32
XROOTD_TIMEOUT = 300
PARTITION = os.environ.get("MCP_SLURM_PARTITION", "vo.scigne.fr")
WORKER_MEMORY = os.environ.get("MCP_SLURM_MEMORY", "8GB")
WORKER_WALLTIME = os.environ.get("MCP_SLURM_WALLTIME", "04:00:00")

# one cluster per process, shared by every step that runs coffea
_client = None


def make_executor(name, workers):
    if name == "iterative":
        return processor.IterativeExecutor()
    if name == "futures":
        return processor.FuturesExecutor(workers=workers)
    if name == "slurm":
        return processor.DaskExecutor(client=slurm_client(workers))
    raise ValueError(f"unknown executor '{name}' (expected {', '.join(EXECUTORS)})")


def run(fileset, tree_name, processor_instance, workers=DEFAULT_WORKERS,
        executor=DEFAULT_EXECUTOR, skip_bad_files=False):
    """`fileset`: {sample name: [file, ...]}, one coffea dataset per sample."""
    runner = processor.Runner(
        executor=make_executor(executor, workers),
        schema=BaseSchema,
        xrootdtimeout=XROOTD_TIMEOUT,
        skipbadfiles=skip_bad_files,
    )
    return runner({name: files for name, files in fileset.items() if files},
                  treename=tree_name, processor_instance=processor_instance)


def slurm_client(jobs):
    global _client
    if _client is not None:
        return _client
    if "SLURM_JOB_ID" not in os.environ:
        raise SystemExit("[error] the slurm executor runs inside a SLURM job, "
                         "submit with: python3.12 -m run.launch --slurm N")

    from dask.distributed import Client
    from dask_jobqueue import SLURMCluster

    SLURM_LOGS.mkdir(parents=True, exist_ok=True)
    cluster = SLURMCluster(
        queue=PARTITION,
        cores=1,
        memory=WORKER_MEMORY,
        walltime=WORKER_WALLTIME,
        python=sys.executable,
        local_directory=str(SLURM_BASE / "dask-scratch-space"),
        job_script_prologue=[
            "unset PYTHONHOME; export PYTHONNOUSERSITE=1",
            f"export PYTHONPATH={FRAMEWORK}",
            f"export X509_USER_PROXY={SLURM_PROXY}",
            f"export MCP_SCRATCH={SCRATCH}",
            f"export MPLCONFIGDIR={SLURM_BASE}/.matplotlib",
        ],
        job_extra_directives=[
            f"--output={SLURM_LOGS}/worker_%j.out",
            f"--error={SLURM_LOGS}/worker_%j.err",
            f"--chdir={FRAMEWORK}",
        ],
    )
    cluster.scale(jobs=jobs)
    _client = Client(cluster)
    atexit.register(cluster.close)
    atexit.register(_client.close)
    print(f"[slurm] {jobs} worker job(s) on {PARTITION}, logs in {SLURM_LOGS}", flush=True)
    return _client
