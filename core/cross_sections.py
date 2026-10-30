"""Cross sections, in pb: HECO signal per (mass, charge), backgrounds per dataset.

`data/cross_sections/`, see its README.
"""

import numpy as np
import pandas as pd

from .paths import DATA as DATA_DIR
from .paths import FRAMEWORK

DATA = DATA_DIR / "cross_sections"

# fb^-1; run23 is the value of limit_test/scripts/extrap.py
LUMINOSITIES = {"run3": 376.81, "run23": 476.81}
DEFAULT_LUMI = LUMINOSITIES["run3"]


class CrossSections:
    def __init__(self, key, label, filename, sqrt_s):
        self.key = key
        self.label = label
        self.path = DATA / filename
        self.sqrt_s = sqrt_s
        self._df = None

    @property
    def df(self):
        if self._df is None:
            df = pd.read_csv(self.path, skipinitialspace=True)
            df.columns = df.columns.str.strip()
            df["charge_e"] = df["charge"] / 3.0
            self._df = df
        return self._df

    @property
    def masses(self):
        return sorted(self.df["mass"].unique())

    @property
    def charges(self):
        return sorted(self.df["charge_e"].unique())

    def table(self):
        return {(int(row.mass), float(row.charge_e)): float(row.xsec_pb)
                for row in self.df.itertuples()}

    def at_charge(self, charge_e):
        rows = self.df[np.isclose(self.df["charge_e"], charge_e)].sort_values("mass")
        return (rows["mass"].values, rows["xsec_pb"].values, rows["unc_pb"].values)

    def on_grid(self, masses, charges):
        table = self.table()
        out = np.full((len(masses), len(charges)), np.nan)
        for i, mass in enumerate(masses):
            for j, charge in enumerate(charges):
                value = table.get((int(round(mass)), float(charge)))
                if value is not None:
                    out[i, j] = value
        return out


SPINS = {
    "spin0p5": CrossSections("spin0p5", "spin 1/2", "heco_cross_sections_run3.csv", 13.6),
    "spin0": CrossSections("spin0", "spin 0", "heco_cross_sections_spin0_run2.csv", 13.0),
}



def read_background(path):
    """-> {primary dataset: xsec in pb}; `path` relative to framework/ or absolute."""
    path = FRAMEWORK / path
    df = pd.read_csv(path, skipinitialspace=True)
    df.columns = df.columns.str.strip()
    return {str(row.dataset).strip(): float(row.xsec_pb) for row in df.itertuples()}
