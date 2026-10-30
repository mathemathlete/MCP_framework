"""Selection = a channel (config/selections.json) applied to a source of candidates."""

import awkward as ak

TRIGGER_LABEL = "trigger"


def most_ionizing(selected):
    """Highest-Ih candidate per event, None for events with no candidate."""
    return ak.firsts(selected[ak.argmax(selected.Ih, axis=1, keepdims=True)])


class Selection:
    """A channel applied to a source: what `efficiency.py` drives."""

    cutflow_ylabel = "Cumulative efficiency"

    def __init__(self, channel, candidates):
        self.channel = channel
        self.candidates = candidates

    @property
    def key(self):
        return f"{self.channel.name}_{self.candidates.source}"

    @property
    def tree_name(self):
        return self.candidates.tree_name

    @property
    def label(self):
        return self.candidates.label

    def trigger(self, events):
        """Per-event trigger mask, or None if the channel applies none."""
        if not self.channel.triggers:
            return None
        passed = events[self.channel.triggers[0]]
        for path in self.channel.triggers[1:]:
            passed = passed | events[path]
        return passed

    def candidate_mask(self, cand, events):
        """Candidate-level mask, the event trigger folded in."""
        mask = None
        for _, cut in self.channel.cuts():
            mask = cut(cand) if mask is None else (mask & cut(cand))
        trigger = self.trigger(events)
        return mask if trigger is None else (mask & trigger)

    def event_mask(self, events):
        """Events with >= 1 fully selected candidate, and the trigger if any."""
        cand = self.candidates.build(events)
        return ak.any(self.candidate_mask(cand, events), axis=1)

    def best_candidate(self, events):
        """Highest-Ih selected candidate of the kept events, and the event mask."""
        cand = self.candidates.build(events)
        selected = cand[self.candidate_mask(cand, events)]
        keep = ak.num(selected, axis=1) > 0
        return most_ionizing(selected)[keep], keep

    def cutflow(self, events):
        """-> (n_events, [(label, n events with >= 1 surviving candidate), ...])."""
        cand = self.candidates.build(events)

        rows = []
        mask = None
        for label, cut in self.channel.cuts():
            mask = cut(cand) if mask is None else (mask & cut(cand))
            rows.append((label, int(ak.sum(ak.num(cand[mask], axis=1) > 0))))

        trigger = self.trigger(events)
        if trigger is not None:
            surviving = (ak.num(cand[mask], axis=1) > 0) & trigger
            rows.append((TRIGGER_LABEL, int(ak.sum(surviving))))

        return len(events), rows

    def cut_labels(self):
        labels = [label for label, _ in self.channel.cuts()]
        return labels + [TRIGGER_LABEL] if self.channel.triggers else labels


class CombinedChannel:
    """Placeholder channel: `CombinedSelection` owns the logic, not a cut list."""

    triggers = ()

    def __init__(self, name, label, plot_dir):
        self.name = name
        self.label = label
        self.plot_dir = plot_dir

    def cuts(self):
        raise NotImplementedError("a combined selection has no single cut list")


class CombinedSelection(Selection):
    """Several channels OR-ed, the first one to fire taking precedence.

    For the map the precedence changes nothing: an event counts once, whichever
    channel selected it. It decides which candidate `best_candidate()` returns
    when an event passes both -- and muon and tau select mutually exclusive
    candidates (`pfType` 13 vs 211), so an event passes both only through two
    different candidates.
    """

    cutflow_ylabel = "Fraction of events"

    def __init__(self, channel, selections):
        super().__init__(channel, selections[0].candidates)
        self.selections = selections

    @property
    def label(self):
        return self.candidates.label

    def candidate_mask(self, cand, events):
        combined = taken = None
        for selection in self.selections:
            mask = selection.candidate_mask(cand, events)
            if combined is None:
                combined = mask
            else:
                # keep the higher-priority candidates where that channel fired
                combined = (combined & taken) | (mask & ~taken)
            fired = ak.any(mask, axis=1)
            taken = fired if taken is None else (taken | fired)
        return combined

    def cutflow(self, events):
        """Overlap breakdown: the parts have different cut lists, so a single
        cumulative sequence would be meaningless."""
        cand = self.candidates.build(events)
        masks = [(s.channel.name, ak.any(s.candidate_mask(cand, events), axis=1))
                 for s in self.selections]

        rows = [(name, int(ak.sum(mask))) for name, mask in masks]

        taken = None
        for name, mask in masks:
            own = mask if taken is None else (mask & ~taken)
            rows.append((f"{name} kept", int(ak.sum(own))))
            taken = mask if taken is None else (taken | mask)

        rows.append(("combined", int(ak.sum(taken))))
        return len(events), rows

    def cut_labels(self):
        names = [s.channel.name for s in self.selections]
        return names + [f"{n} kept" for n in names] + ["combined"]

