import json
import operator
import re
from dataclasses import dataclass
from pathlib import Path

OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}
CUT_RE = re.compile(r"^\s*(\w+)\s*(>=|<=|==|!=|>|<)\s*(\S+)\s*$")
BOOLEANS = {"true": True, "false": False}
PRESELECTION = "preselection"
PRESELECTION_KEYS = {"cuts"}
CHANNEL_KEYS = {"label", "plot_dir", "triggers", "primary_datasets", "objects", "cuts",
                "regions"}
COMBINED_KEYS = {"label", "plot_dir", "combine"}


class CutError(ValueError):
    pass


@dataclass(frozen=True)
class Cut:
    """`observable op value`, applied to the fields of an awkward record."""

    observable: str
    op: str
    value: float | bool
    text: str
    label: str

    def __call__(self, record):
        if self.observable not in record.fields:
            raise CutError(f"'{self.text}': unknown observable '{self.observable}', "
                           f"expected one of {sorted(record.fields)}")
        return OPERATORS[self.op](record[self.observable], self.value)


@dataclass(frozen=True)
class Channel:
    name: str
    label: str
    plot_dir: str
    triggers: tuple
    selection: tuple
    preselection: tuple = ()
    objects: tuple = ()
    regions: tuple = ()
    primary_datasets: tuple = ()

    def cuts(self):
        """-> ordered [(label, cut), ...]: preselection, objects, then the channel cuts."""
        return [(cut.label, cut) for cut in self.preselection + self.objects + self.selection]


def _split(text):
    match = CUT_RE.match(str(text))
    if not match:
        raise CutError(f"'{text}': expected 'observable op value', op in {list(OPERATORS)}")
    return match.groups()


def parse_cut(text, labels=None):
    observable, op, raw = _split(text)
    if raw.lower() in BOOLEANS:
        value = BOOLEANS[raw.lower()]
        if op not in ("==", "!="):
            raise CutError(f"'{text}': a boolean only takes == or !=")
    else:
        try:
            value = float(raw)
        except ValueError:
            raise CutError(f"'{text}': value '{raw}' is neither a number nor true/false") from None
    normalized = f"{observable} {op} {raw}"
    return Cut(observable, op, value, normalized, (labels or {}).get(normalized, normalized))


def load_selections(path, labels_path=None, object_cuts=None):
    """-> (channels: name -> Channel, combined: name -> (channel names, label, plot dir)).

    `preselection` is applied before the cuts of every channel; an entry with
    `cuts` or `objects` is a channel, one with `combine` a combination of channels.
    `object_cuts` maps a channel name to the callable turning its `objects`
    working points into cut strings; `regions` maps a region name to its cuts."""
    path = Path(path)
    entries = json.loads(path.read_text())
    labels = {}
    if labels_path and Path(labels_path).exists():
        labels = {" ".join(_split(k)): v for k, v in json.loads(Path(labels_path).read_text()).items()}

    def parse_all(name, cuts):
        try:
            return tuple(parse_cut(c, labels) for c in cuts)
        except CutError as err:
            raise CutError(f"{path}: '{name}': {err}") from None

    presel_entry = entries.pop(PRESELECTION, {"cuts": []})
    unknown = set(presel_entry) - PRESELECTION_KEYS
    if unknown:
        raise CutError(f"{path}: '{PRESELECTION}' has unknown key(s) {sorted(unknown)}")
    preselection = parse_all(PRESELECTION, presel_entry.get("cuts", []))

    channels, combined = {}, {}
    for name, entry in entries.items():
        is_combined = "combine" in entry
        unknown = set(entry) - (COMBINED_KEYS if is_combined else CHANNEL_KEYS)
        if unknown:
            raise CutError(f"{path}: '{name}' has unknown key(s) {sorted(unknown)}")
        label, plot_dir = entry.get("label", name), entry.get("plot_dir", name)
        if is_combined:
            combined[name] = (tuple(entry["combine"]), label, plot_dir)
            continue
        if not entry.get("cuts") and not entry.get("objects"):
            raise CutError(f"{path}: channel '{name}' has no cuts")
        objects = ()
        if entry.get("objects"):
            if name not in (object_cuts or {}):
                raise CutError(f"{path}: channel '{name}' has objects but no object selection")
            try:
                texts = object_cuts[name](entry["objects"])
            except CutError as err:
                raise CutError(f"{path}: '{name}': {err}") from None
            objects = parse_all(name, texts)
        regions = tuple((region, parse_all(f"{name}/{region}", cuts))
                        for region, cuts in entry.get("regions", {}).items())
        channels[name] = Channel(name, label, plot_dir, tuple(entry.get("triggers", ())),
                                 parse_all(name, entry.get("cuts", [])), preselection,
                                 objects, regions, tuple(entry.get("primary_datasets", ())))

    for name, (parts, _, _) in combined.items():
        missing = [p for p in parts if p not in channels]
        if missing:
            raise CutError(f"{path}: '{name}' combines unknown channel(s) {missing}")
    return channels, combined
