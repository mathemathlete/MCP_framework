r"""HSCP/MCP selections on the MiniAOD ntuples (`HSCPMiniAODAnalyzer/Events`).

A selection = a channel x a source. Channels are written against canonical
candidate fields, so adding a source (NanoAOD) is a new `Candidates` subclass
and nothing else.

Canonical fields and their branches
-----------------------------------
| field               | MiniAOD branch                                |
|---------------------|-----------------------------------------------|
| `pt` `eta` `phi`    | `IsoTrack_pt` `IsoTrack_eta` `IsoTrack_phi`   |
| `p_track`           | `IsoTrack_PseudoTrack_p`                      |
| `pt_track`          | `IsoTrack_PseudoTrack_pt`                     |
| `chi2`              | `IsoTrack_normChi2`                           |
| `dedx_hits`         | `DeDx_IhNOM`                                  |
| `tracker_hits`      | `IsoTrack_numberOfValidHits`                  |
| `dz` `dxy`          | `IsoTrack_dz` `IsoTrack_dxy`, absolute value  |
| `high_purity`       | `IsoTrack_isHighPurityTrack`                  |
| `sigma_pt_over_pt2` | `IsoTrack_ptErrOverPt2`                       |
| `mini_rel_iso`      | `IsoTrack_pfMiniRelIsoAll`                    |
| `track_iso`         | `IsoTrack_IsoSumPt_dr03`                      |
| `Ih`                | `DeDx_Ih`                                     |
| `inverse_beta`      | `Muon_time_inverseBeta`                       |
| `medium_muon`       | `Muon_isMedium`                               |
| `loose_muon`        | `Muon_isLoose`                                |
| `pf_type`           | `IsoTrack_pfType` (PDG)                       |
| `pt_tau`            | tau linked through `IsoTrack_pfIdx`           |
| `ecal` `hcal`       | `IsoTrack_pfEcalEnergy` `IsoTrack_pfHcalEnergy` |

Collection indexing is the one trap: `IsoTrack_*`/`DeDx_*` have one entry per
HSCP candidate with a track (`HSCP_hasTrack`), `Muon_*` one per candidate with a
muon (`HSCP_hasMuon`). `align_to_candidates()` re-spreads them onto the HSCP
candidate index. Beware `Muon_*` (the candidate's muon) vs `muon_*` (a flat dump
of `slimmedMuons`).
"""

from abc import ABC, abstractmethod

import awkward as ak
import numpy as np

# fill value for candidates with no track / no muon / no tau: fails every cut
NO_VALUE = -999.0

PF_MUON = 13
PF_HADRON = 211


def align_to_candidates(compact, present, fill=NO_VALUE):
    """Re-spread a compact collection onto the HSCP candidate index.

    `compact` has one entry per candidate where `present` is true, in the same
    order; the result has one per HSCP candidate, `fill` elsewhere.
    """
    counts = ak.num(present, axis=1)
    flat_present = ak.to_numpy(ak.flatten(present, axis=1))
    flat_compact = ak.to_numpy(ak.flatten(compact, axis=1))

    if flat_present.sum() != len(flat_compact):
        raise ValueError(f"misaligned collection: {flat_present.sum()} candidates "
                         f"expected, {len(flat_compact)} values found")

    dtype = np.result_type(flat_compact.dtype, np.asarray(fill).dtype)
    out = np.full(flat_present.shape, fill, dtype=dtype)
    out[flat_present] = flat_compact
    return ak.unflatten(out, counts)


def _safe_div(num, den, guard):
    return ak.where(guard, num / ak.where(guard, den, 1.0), 0.0)


class Candidates(ABC):
    """Builds the canonical candidate record from a ntuple."""

    source = ""
    label = ""
    tree_name = ""

    @abstractmethod
    def build(self, events):
        """-> ak.Array of records, one per candidate."""

    def _derived(self, fields):
        e_calo = fields["hcal"] + fields["ecal"]
        fields["e_calo"] = e_calo
        fields["hcal_prop"] = _safe_div(fields["hcal"], e_calo, e_calo != 0)
        fields["e_over_p"] = _safe_div(e_calo, fields["p_track"], fields["p_track"] > 0)
        return fields


class MiniaodCandidates(Candidates):
    source = "miniaod"
    label = "MiniAOD 2024"
    tree_name = "HSCPMiniAODAnalyzer/Events"

    # dz/dxy on their absolute value. The AOD selection cut on the signed value,
    # which let ~50% of candidates through unconditionally.
    USE_ABS_IMPACT = True

    def build(self, events):
        has_track = events.HSCP_hasTrack
        has_muon = events.HSCP_hasMuon

        def track(branch, fill=NO_VALUE):
            return align_to_candidates(events[branch], has_track, fill)

        def muon(branch, fill=NO_VALUE):
            return align_to_candidates(events[branch], has_muon, fill)

        dz, dxy = track("IsoTrack_dz"), track("IsoTrack_dxy")
        if self.USE_ABS_IMPACT:
            dz, dxy = abs(dz), abs(dxy)

        fields = {
            "pt": track("IsoTrack_pt"),
            "eta": track("IsoTrack_eta"),
            "phi": track("IsoTrack_phi"),
            "p_track": track("IsoTrack_PseudoTrack_p"),
            "pt_track": track("IsoTrack_PseudoTrack_pt"),
            "chi2": track("IsoTrack_normChi2"),
            "dedx_hits": track("DeDx_IhNOM", fill=0),
            "tracker_hits": track("IsoTrack_numberOfValidHits", fill=0),
            "dz": dz,
            "dxy": dxy,
            "high_purity": track("IsoTrack_isHighPurityTrack", fill=False),
            "sigma_pt_over_pt2": track("IsoTrack_ptErrOverPt2"),
            "mini_rel_iso": track("IsoTrack_pfMiniRelIsoAll"),
            "track_iso": track("IsoTrack_IsoSumPt_dr03"),
            "Ih": track("DeDx_Ih"),
            "inverse_beta": muon("Muon_time_inverseBeta"),
            "medium_muon": muon("Muon_isMedium", fill=False),
            "loose_muon": muon("Muon_isLoose", fill=False),
            "pf_type": track("IsoTrack_pfType", fill=0),
            "pt_tau": self.match_tau(track("IsoTrack_pfIdx", fill=-1), events),
            "ecal": track("IsoTrack_pfEcalEnergy", fill=0.0),
            "hcal": track("IsoTrack_pfHcalEnergy", fill=0.0),
        }
        return ak.zip(self._derived(fields))

    def match_tau(self, pf_idx, events):
        """pt of the tau the candidate is a signal charged hadron of, else NO_VALUE.

        A `pat::Tau` is built out of `packedPFCandidates` and the HSCP candidate
        is one of them, so the link is an object identity: same `pfIdx`. No dR,
        no tolerance. `pfIdx == -1` marks a candidate with no packed-candidate
        reference, which can never match (prong indices are >= 0).
        """
        idx, prongs = ak.unzip(ak.cartesian(
            [pf_idx, events.tau_signalChargedHadrCands_pfIdx], axis=1, nested=True))
        linked = ak.any(prongs == idx, axis=3) & (idx >= 0)

        _, tau_pt = ak.unzip(ak.cartesian([pf_idx, events.tau_pt], axis=1, nested=True))
        best = ak.argmax(linked, axis=2, keepdims=True)
        matched = ak.fill_none(ak.firsts(tau_pt[best], axis=2), NO_VALUE)
        return ak.where(ak.any(linked, axis=2), matched, NO_VALUE)


class SkimCandidates(Candidates):
    """Candidates already built and written to a checkpoint (`cand_<field>`).
    Same source as what was skimmed, so the selection keys do not change."""

    source = MiniaodCandidates.source
    label = MiniaodCandidates.label
    tree_name = "Events"
    PREFIX = "cand_"

    def build(self, events):
        return ak.zip({f[len(self.PREFIX):]: events[f] for f in events.fields
                       if f.startswith(self.PREFIX)})


SOURCES = {"miniaod": MiniaodCandidates, "skim": SkimCandidates}
