"""Selection checkpoints -> signal efficiency maps and cutflows, background yields.

One folder per channel, `<plot_dir>/`. Signal: TH2D map and its plot, merged into
the cache `efficiencies.json`. Background: yields per dataset and per process. The
plots and tables go to `<results>/efficiency_map/`, the ROOT maps and the JSON to
the same place on the scratch (`core.scratch.data_path`).
"""

from core.scratch import data_path
from core.selection import SELECTIONS, get_selection

from . import efficiency as eff
from . import plotting

NAME = "efficiency_map"


def merge_cutflows(old, new):
    """Same point-level merge as the maps, across masses and charges."""
    by_point = {(c.mass, c.charge): c for c in old}
    by_point.update({(c.mass, c.charge): c for c in new})
    return [by_point[k] for k in sorted(by_point)]


def compute_maps(channels, signal, cutflow_mass):
    if cutflow_mass and not any(s.mass == cutflow_mass for s in signal):
        print(f"[warn] M={cutflow_mass} is not in the selected grid, no cutflow")
    maps, cutflows = {}, {}
    for channel in channels:
        selection = get_selection(channel)
        print(f"\n=== {selection.key} ({selection.label}, "
              f"{selection.channel.label}) ===")
        emap, cfs = eff.read_selection(selection, signal, cutflow_mass)
        maps[selection.key] = emap
        print(emap.table())
        if cfs:
            cutflows[selection.key] = cfs
        for cf in cfs:
            print(f"\n-- cutflow M={cf.mass}, Q={cf.charge}e, "
                  f"{cf.n_total} events --")
            print(cf.table())
    return maps, cutflows


def compute_yields(channels, background):
    return {get_selection(c).key: eff.read_yields(get_selection(c), background)
            for c in channels}


def plot_dirs():
    """Map key -> the folder of the channel (`plot_dir` of config/selections.json)."""
    selections = [get_selection(c) for c in SELECTIONS]
    return {s.key: s.channel.plot_dir or s.key for s in selections}


def write_outputs(maps, outdir):
    folders = plot_dirs()
    for key, emap in maps.items():
        if not emap:
            continue
        folder = outdir / folders.get(key, key)
        emap.write(data_path(folder / "map.root"))
        plotting.plot_map(emap, folder / "map.pdf")


def write_yields(yields, outdir, lumi):
    stored = eff.save_yields(data_path(outdir / "yields.json"), yields)
    folders = plot_dirs()
    for key in yields:
        table = eff.yields_table(stored[key], lumi)
        print(f"\n=== yields {key} ===\n{table}")
        path = outdir / folders.get(key, key) / "yields.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(table + "\n")
        print(f"[ok] {path}")


def compute(samples, channels, args, outdir, cache):
    """-> (maps, cutflows) of the cache, the new points merged in; None without signal."""
    signal = [s for s in samples.values() if s.is_signal]
    background = [s for s in samples.values() if s.is_background]
    new_maps, new_cutflows = compute_maps(channels, signal, args.cutflow_mass) \
        if signal else ({}, {})
    yields = compute_yields(channels, background) if background else {}

    if yields:
        write_yields(yields, outdir, args.lumi)
    if not signal:
        return None

    # merge into the existing cache: rerunning one channel or a few points
    # must not throw the rest away
    maps, cutflows = ({}, {})
    if cache.exists():
        print(f"[info] merging into {cache}")
        maps, cutflows = eff.load_cache(cache)
    for key, emap in new_maps.items():
        old = maps.get(key)
        maps[key] = emap.merged_with(old) if old else emap
    for key, cfs in new_cutflows.items():
        cutflows[key] = merge_cutflows(cutflows.get(key, []), cfs)
    eff.save_cache(cache, maps, cutflows)
    return maps, cutflows


def run(samples, args):
    plotting.apply_cms_style()
    outdir = args.results / NAME
    cache = data_path(outdir / "efficiencies.json")

    if args.from_cache:
        if not cache.exists():
            raise SystemExit(f"[error] no cache at {cache} -- run without --from-cache")
        print(f"[info] reading {cache}")
        maps, _ = eff.load_cache(cache)
    else:
        computed = compute(samples, args.channel or SELECTIONS, args, outdir, cache)
        if computed is None:
            print(f"[info] no signal sample: yields only, in {outdir}")
            return
        maps, _ = computed

    write_outputs(maps, outdir)
    print(f"[info] efficiency maps in {outdir}")
