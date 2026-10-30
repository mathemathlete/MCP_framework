from ..paths import CONFIG
from .analysis import ANALYSIS_CLASSES, Analysis, MuonAnalysis, TauAnalysis
from .candidates import SOURCES, Candidates, MiniaodCandidates, SkimCandidates
from .cuts import Channel, Cut, CutError, load_selections
from .selection import CombinedChannel, CombinedSelection, Selection

SELECTIONS_CONFIG = CONFIG / "selections.json"
CUT_LABELS = CONFIG / "cut_labels.json"
OBJECT_CUTS = {name: cls.object_cuts for name, cls in ANALYSIS_CLASSES.items()}

CHANNELS, COMBINED = load_selections(SELECTIONS_CONFIG, CUT_LABELS, OBJECT_CUTS)
SELECTIONS = sorted(CHANNELS) + sorted(COMBINED)
ANALYSES = tuple(sorted(CHANNELS))
PRESELECTION = next(iter(CHANNELS.values())).preselection
ALL_TRIGGERS = tuple(sorted({t for c in CHANNELS.values() for t in c.triggers}))


def make_analysis(channel, source="miniaod"):
    if source not in SOURCES:
        raise KeyError(f"unknown source: {source} (expected {sorted(SOURCES)})")
    return ANALYSIS_CLASSES.get(channel.name, Analysis)(channel, SOURCES[source]())


def get_analysis(name, source="miniaod"):
    if name not in CHANNELS:
        raise KeyError(f"unknown analysis: {name} (expected {list(ANALYSES)})")
    return make_analysis(CHANNELS[name], source)


def get_selection(channel, source="miniaod"):
    if channel in COMBINED:
        parts, label, plot_dir = COMBINED[channel]
        return CombinedSelection(CombinedChannel(channel, label, plot_dir),
                                 [get_selection(c, source) for c in parts])
    if channel not in CHANNELS:
        raise KeyError(f"unknown channel: {channel} (expected {SELECTIONS})")
    return get_analysis(channel, source)
