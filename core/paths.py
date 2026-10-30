import os
from pathlib import Path

FRAMEWORK = Path(__file__).resolve().parents[1]
ANALYSIS_MCP = FRAMEWORK.parent

CONFIG = FRAMEWORK / "config"
DATA = FRAMEWORK / "data"
RESULTS = FRAMEWORK / "results"
PRODUCTION = FRAMEWORK / "production"
SCRATCH = Path(os.environ.get("MCP_SCRATCH", "/scratch/cms/xmadre/MCP_analysis"))

COFFEA = ANALYSIS_MCP / "coffea"

# SLURM compute nodes only mount /home-pbs: the framework is synced there (run/slurm.py)
SLURM_BASE = Path(os.environ.get("MCP_SLURM_BASE", "/home-pbs/xmadre/MCP"))
SLURM_FRAMEWORK = SLURM_BASE / "analysis_MCP" / "framework"
SLURM_SCRATCH = SLURM_BASE / "scratch"
SLURM_LOGS = SLURM_BASE / "logs"
SLURM_PYTHON = Path(os.environ.get(
    "MCP_SLURM_PYTHON", SLURM_BASE / "coffea_workflow" / "condaEnv" / "bin" / "python3.12"))
SLURM_PROXY = Path(os.environ.get("MCP_SLURM_PROXY", "/home-pbs/xmadre/proxy/x509up"))
