"""Efficiency maps -> expected exclusion contours, per channel, spin and luminosity."""

from core import cross_sections as xsec_module
from core.datasets.catalog import CHARGES
from core.scratch import data_path

from . import limits, plotting

NAME = "limits"


def scenarios(args):
    if args.limit_lumi is not None:
        return [(f"L{args.limit_lumi:g}", args.limit_lumi)]
    return [(key, limits.LUMINOSITIES[key])
            for key in (args.scenario or limits.LUMINOSITIES)]


def maps_dir(args):
    return args.maps_dir or data_path(args.results / "efficiency_map")


def run_scan(channel, spin, lumi_key, lumi, args, maps, outdir):
    scan = limits.scan(channel, spin, lumi_key, maps, lumi=lumi)
    print(f"\n=== {scan.key} ({scan.label}, {scan.lumi:g} fb^-1) ===")
    print(f"[info] map {scan.source}")
    print(scan.table())

    folder = outdir / scan.plot_dir / scan.cross_sections.key
    scan.write(data_path(folder / f"npred_{scan.lumi_key}.root"))
    plotting.plot_exclusion(scan, folder / f"excl_{scan.lumi_key}.pdf",
                            atlas=not args.no_atlas)
    return scan


def cross_section_plots(outdir):
    plots = outdir / "xsec"
    for spin, cross_sections in xsec_module.SPINS.items():
        plotting.plot_xsec_vs_mass(cross_sections, CHARGES,
                                   plots / f"xsec_vs_mass_{spin}.pdf")
        plotting.plot_xsec_by_charge(cross_sections, CHARGES,
                                     plots / f"xsec_by_charge_{spin}.pdf")


def run(samples, args):
    """`samples`: None when no stage of the run reads any."""
    if samples is not None and not any(s.is_signal for s in samples.values()):
        print("[info] no signal sample in this run, no limit")
        return
    plotting.apply_cms_style()
    outdir = args.results / NAME
    if not args.xsec_only:
        maps = maps_dir(args)
        for channel in args.channel or limits.SELECTIONS:
            for spin in args.spin or xsec_module.SPINS:
                for lumi_key, lumi in scenarios(args):
                    run_scan(channel, spin, lumi_key, lumi, args, maps, outdir)

    if args.xsec_only or not args.no_xsec:
        cross_section_plots(outdir)
    print(f"[info] limits in {outdir}")
