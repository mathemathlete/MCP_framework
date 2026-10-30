"""Standalone test of the selection: fake events by default, or a real ntuple with --file.

    python3.12 -m tests.test_selection
    python3.12 -m tests.test_selection --file root://.../output_1.root --analysis muon tau
"""

import argparse
from dataclasses import replace

import awkward as ak
import numpy as np
import uproot

from core.selection import ANALYSES, CHANNELS, get_analysis, make_analysis
from core.selection.cuts import parse_cut
from stages.regions import selected_columns

MUON_CANDIDATE = {
    "IsoTrack_pt": 100.0, "IsoTrack_eta": 0.0, "IsoTrack_phi": 0.0,
    "IsoTrack_PseudoTrack_p": 100.0, "IsoTrack_PseudoTrack_pt": 100.0,
    "IsoTrack_normChi2": 1.0, "DeDx_IhNOM": 12, "IsoTrack_numberOfValidHits": 15,
    "IsoTrack_dz": 0.0, "IsoTrack_dxy": 0.0, "IsoTrack_isHighPurityTrack": True,
    "IsoTrack_ptErrOverPt2": 0.001, "IsoTrack_pfMiniRelIsoAll": 0.0,
    "IsoTrack_IsoSumPt_dr03": 1.0, "DeDx_Ih": 8.0, "IsoTrack_pfType": 13,
    "IsoTrack_pfIdx": -1, "IsoTrack_pfEcalEnergy": 0.0, "IsoTrack_pfHcalEnergy": 0.0,
    "Muon_time_inverseBeta": 1.5, "Muon_isMedium": True, "Muon_isLoose": True,
}
TAU_CANDIDATE = {**MUON_CANDIDATE, "IsoTrack_pfType": 211, "IsoTrack_pfIdx": 5, "DeDx_Ih": 20.0}
MUON_TRIGGER = "HLT_Mu50"
TAU_TRIGGER = "HLT_DoubleMediumDeepTauPFTauHPS35_L2NN_eta2p1"
LINKED_TAU = {"pt": 60.0, "prongs": [5]}

FAKE_EVENTS = [
    ([MUON_CANDIDATE], [MUON_TRIGGER]),
    ([{**MUON_CANDIDATE, "DeDx_Ih": 4.0}, {**MUON_CANDIDATE, "IsoTrack_pt": 20.0}], [MUON_TRIGGER]),
    ([MUON_CANDIDATE], []),
    ([{**MUON_CANDIDATE, "IsoTrack_normChi2": 10.0}], [MUON_TRIGGER]),
    ([MUON_CANDIDATE, {**MUON_CANDIDATE, "DeDx_Ih": 12.0}], [MUON_TRIGGER]),
    ([TAU_CANDIDATE], [TAU_TRIGGER]),
]
EXPECTED = {"muon": [True, False, False, False, True, False],
            "tau": [False, False, False, False, False, True]}
TEST_REGIONS = {"SR": ["Ih > 10"], "CR": ["Ih <= 10"]}
EXPECTED_REGIONS = {"SR": [False, False, False, False, True, False],
                    "CR": [True, False, False, False, False, False]}


def fake_events():
    triggers = sorted({t for _, fired in FAKE_EVENTS for t in fired}
                      | {"HLT_IsoMu24", "HLT_IsoMu27",
                         "HLT_DoublePNetTauhPFJet30_Medium_L2NN_eta2p3",
                         "HLT_DoubleMediumDeepTauPFTauHPS30_L2NN_eta2p1_OneProng"})
    columns = {branch: ak.Array([[c[branch] for c in cands] for cands, _ in FAKE_EVENTS])
               for branch in MUON_CANDIDATE}
    columns["HSCP_hasTrack"] = ak.Array([[True] * len(c) for c, _ in FAKE_EVENTS])
    columns["HSCP_hasMuon"] = ak.Array([[c["IsoTrack_pfType"] == 13 for c in cands]
                                        for cands, _ in FAKE_EVENTS])
    for branch in [b for b in MUON_CANDIDATE if b.startswith("Muon_")]:
        columns[branch] = ak.Array([[c[branch] for c in cands if c["IsoTrack_pfType"] == 13]
                                    for cands, _ in FAKE_EVENTS])
    columns["tau_pt"] = ak.Array([[LINKED_TAU["pt"]]] * len(FAKE_EVENTS))
    columns["tau_signalChargedHadrCands_pfIdx"] = ak.Array([[LINKED_TAU["prongs"]]] * len(FAKE_EVENTS))
    for trigger in triggers:
        columns[trigger] = ak.Array([trigger in fired for _, fired in FAKE_EVENTS])
    return ak.zip(columns, depth_limit=1)


def print_cutflows(name, analysis, packed):
    for flow, cutflow in analysis.cutflows(packed).items():
        result = cutflow.result()
        print(f"\n[{name}] {flow}")
        for label, n in zip(result.labels, result.nevcutflow):
            print(f"  {label:<30} {n}")


def check_fake():
    events = fake_events()
    for name in ANALYSES:
        analysis = get_analysis(name)
        packed, _ = analysis.packed_selection(events)
        print_cutflows(name, analysis, packed)

        selected = packed.all(*analysis.cut_names())
        assert selected.tolist() == EXPECTED[name], (name, selected.tolist())
        assert selected.tolist() == ak.to_list(analysis.event_mask(events)), name

        _, rows = analysis.cutflow(events)
        nev = analysis.cutflows(packed)["selection"].result().nevcutflow[1:]
        assert [n for _, n in rows] == [int(n) for n in nev], name

    regions = tuple((r, tuple(parse_cut(c) for c in cuts)) for r, cuts in TEST_REGIONS.items())
    analysis = make_analysis(replace(CHANNELS["muon"], regions=regions))
    packed, best = analysis.packed_selection(events)
    print_cutflows("muon + test regions", analysis, packed)
    for region, mask in analysis.region_masks(packed).items():
        assert mask.tolist() == EXPECTED_REGIONS[region], (region, mask.tolist())
    assert ak.to_list(best.Ih)[4] == 12.0
    cand = analysis.candidates.build(events)
    selected = analysis.event_mask(events)
    columns = selected_columns(events[selected],
                               cand[analysis.candidate_mask(cand, events)][selected],
                               analysis.channel.regions)
    assert columns["Ih"].tolist() == [8.0, 12.0], columns["Ih"]
    assert columns["region_SR"].tolist() == [False, True]
    assert columns["region_CR"].tolist() == [True, False]
    print("\nfake events: OK")


def run_file(path, names, max_events):
    analyses = [get_analysis(n) for n in names]
    tree = uproot.open({path: analyses[0].tree_name})
    branches = [k for k in tree.keys() if not k.startswith(("GenPart", "puppijet", "electron", "muon_"))]
    events = tree.arrays(branches, entry_stop=max_events)
    for name, analysis in zip(names, analyses):
        packed, _ = analysis.packed_selection(events)
        print_cutflows(name, analysis, packed)


def main():
    p = argparse.ArgumentParser(description="selection test")
    p.add_argument("--file", help="ntuple (local path or xrootd URL); fake events if absent")
    p.add_argument("--analysis", nargs="+", choices=ANALYSES, default=list(ANALYSES))
    p.add_argument("--max-events", type=int)
    args = p.parse_args()
    if args.file:
        run_file(args.file, args.analysis, args.max_events)
    else:
        check_fake()


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
