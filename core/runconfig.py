"""Run config: a YAML file giving the samples and the default options of run.launch.

    python3.12 -m run.launch config/runs/bkg_2024.yaml

`samples` is described in core/samples.py. Every other key is the name of a
launcher option (`--to` -> `to`, `--cutflow-mass` -> `cutflow_mass`) and gives its
default: an option on the command line always wins. An unknown key fails.
"""

from pathlib import Path

import yaml

from .paths import FRAMEWORK
from .samples import SampleError

SAMPLES = "samples"


def load(path, options):
    """-> dict; `path` relative to the current directory or to framework/, `options`
    the keys allowed besides `samples`."""
    path = Path(path)
    if not path.exists() and (FRAMEWORK / path).exists():
        path = FRAMEWORK / path
    if not path.exists():
        raise SampleError(f"no run config {path}")
    config = yaml.safe_load(path.read_text()) or {}
    unknown = set(config) - set(options) - {SAMPLES}
    if unknown:
        raise SampleError(f"{path}: unknown key(s) {sorted(unknown)}, "
                          f"expected {SAMPLES} or {sorted(options)}")
    return config


def apply(args, config, defaults):
    """Fill the options left unset on the command line (None): config, then default."""
    for name, default in defaults.items():
        if getattr(args, name) is None:
            setattr(args, name, config.get(name, default))
    return args
