"""Analyses: a channel of config/selections.json applied as a coffea PackedSelection."""

import awkward as ak
from coffea.analysis_tools import PackedSelection

from .cuts import CutError
from .selection import TRIGGER_LABEL, Selection, most_ionizing

MUON_IDS = {"loose": "loose_muon", "medium": "medium_muon"}


def _check_keys(objects, expected):
    missing = sorted(set(expected) - set(objects))
    unknown = sorted(set(objects) - set(expected))
    if missing or unknown:
        raise CutError(f"objects: missing {missing}, unknown {unknown}, expected {sorted(expected)}")


class Analysis(Selection):
    """Common skeleton: preselection, object selection, channel cuts,
    trigger, then regions on the most ionising candidate.

    Each bit of the PackedSelection is cumulative at candidate level: the bit
    of a cut means "at least one candidate passes every cut so far".
    Only `all()` and `cutflow()` in the order of `cut_names()` are therefore meaningful.
    """

    name = ""

    @staticmethod
    def object_cuts(objects):
        """Working points of `objects` -> cut strings."""
        if objects:
            raise CutError("this analysis has no object selection")
        return []

    def cut_names(self):
        names = [cut.text for _, cut in self.channel.cuts()]
        return names + [TRIGGER_LABEL] if self.channel.triggers else names

    def region_names(self):
        return [region for region, _ in self.channel.regions]

    def packed_selection(self, events):
        """-> (PackedSelection, most ionising candidate of the selected events, None otherwise)."""
        cand = self.candidates.build(events)
        packed = PackedSelection(dtype="uint64")

        mask = None
        for _, cut in self.channel.cuts():
            mask = cut(cand) if mask is None else (mask & cut(cand))
            packed.add(cut.text, ak.to_numpy(ak.any(mask, axis=1)))

        trigger = self.trigger(events)
        if trigger is not None:
            mask = mask & trigger
            packed.add(TRIGGER_LABEL, ak.to_numpy(trigger))

        best = most_ionizing(cand[mask])
        for region, cuts in self.channel.regions:
            passed = ak.ones_like(best.Ih, dtype=bool)
            for cut in cuts:
                passed = passed & cut(best)
            packed.add(region, ak.to_numpy(ak.fill_none(passed, False)))
        return packed, best

    def region_masks(self, packed):
        names = self.cut_names()
        return {region: packed.all(*names, region) for region in self.region_names()}

    def cutflows(self, packed):
        """-> {"selection": full cutflow, region: cutflow ending with the region}."""
        names = self.cut_names()
        flows = {"selection": packed.cutflow(*names)}
        flows.update({region: packed.cutflow(*names, region) for region in self.region_names()})
        return flows


class MuonAnalysis(Analysis):
    name = "muon"

    @staticmethod
    def object_cuts(objects):
        _check_keys(objects, ("pf_type", "muon_id"))
        if objects["muon_id"] not in MUON_IDS:
            raise CutError(f"muon_id '{objects['muon_id']}' not in {sorted(MUON_IDS)}")
        return [f"pf_type == {objects['pf_type']:g}",
                f"{MUON_IDS[objects['muon_id']]} == true"]


class TauAnalysis(Analysis):
    name = "tau"

    @staticmethod
    def object_cuts(objects):
        _check_keys(objects, ("pf_type", "tau_pt_min"))
        return [f"pf_type == {objects['pf_type']:g}",
                f"pt_tau > {objects['tau_pt_min']:g}"]


ANALYSIS_CLASSES = {cls.name: cls for cls in (MuonAnalysis, TauAnalysis)}
