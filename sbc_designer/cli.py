"""Command line interface (batch generation without the GUI).

Examples::

    sbc-designer-cli info board.step
    sbc-designer-cli generate board.step --part alignment --side top -o top_alignment.step
    sbc-designer-cli generate board.step --all --out-dir parts/
    sbc-designer-cli screenshot board.step -o view.png --with-parts
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .design import PART_TYPES, SCREWS, SBCParameters
from .pcba import SIDES
from .project import Project


def _project(args) -> Project:
    params = SBCParameters.load(args.params) if getattr(args, "params", None) else SBCParameters()
    pr = Project(params)
    pr.load(args.step)
    return pr


def cmd_info(args) -> int:
    pr = _project(args)
    print(f"{pr.name}: {len(pr.raw_parts)} parts")
    if not pr.can_design:
        print(f"Not a PCBA: {pr.pcba_error}")
        return 1
    print(pr.report())
    return 0


def cmd_generate(args) -> int:
    pr = _project(args)
    if not pr.can_design:
        print(f"Not a PCBA: {pr.pcba_error}", file=sys.stderr)
        return 1
    if args.all:
        pr.generate_all()
        folder = args.out_dir or "."
        for f in pr.export_each(folder):
            print("wrote", f)
        if args.output:
            print("wrote", pr.export(None, args.output))
        return 0
    if not args.part:
        print("--part or --all is required", file=sys.stderr)
        return 2
    sides = ["both"] if args.part == SCREWS else (list(SIDES) if args.side == "both" else [args.side])
    for s in sides:
        pr.generate(args.part, s)
    out = args.output or f"{os.path.splitext(pr.name)[0]}_{args.side}_{args.part}.step"
    print("wrote", pr.export(None, out))
    return 0


def cmd_screenshot(args) -> int:
    from .viewer import Scene, explode_direction

    pr = _project(args)
    scene = Scene(offscreen=True)
    scene.render_window.SetSize(args.width, args.height)
    for i, p in enumerate(pr.display_parts):
        scene.add_part(f"m{i}", p)
    if args.with_parts and pr.can_design:
        pr.generate_all()
        for i, p in enumerate(pr.all_generated()):
            scene.add_part(f"g{i}", p, "generated", explode_dir=explode_direction(p))
        scene.set_explode(args.explode)
    scene.set_view(args.view)
    scene.screenshot(args.output)
    print("wrote", args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="sbc-designer-cli", description="SBC Designer command line")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="analyse a PCBA STEP file")
    p.add_argument("step")
    p.add_argument("--params", help="parameter JSON file")
    p.set_defaults(fn=cmd_info)

    p = sub.add_parser("generate", help="generate SBC parts as STEP")
    p.add_argument("step")
    p.add_argument("--part", choices=PART_TYPES)
    p.add_argument("--side", choices=["top", "bottom", "both"], default="top")
    p.add_argument("--all", action="store_true", help="every part for both sides")
    p.add_argument("-o", "--output", help="output STEP file (all selected parts in one assembly)")
    p.add_argument("--out-dir", help="with --all: one STEP file per part and side")
    p.add_argument("--params", help="parameter JSON file")
    p.set_defaults(fn=cmd_generate)

    p = sub.add_parser("screenshot", help="render a PNG off-screen")
    p.add_argument("step")
    p.add_argument("-o", "--output", default="view.png")
    p.add_argument("--view", default="iso", choices=["iso", "top", "bottom", "front", "back", "left", "right"])
    p.add_argument("--with-parts", action="store_true", help="generate and show all SBC parts")
    p.add_argument("--explode", type=float, default=2.0)
    p.add_argument("--width", type=int, default=1600)
    p.add_argument("--height", type=int, default=1100)
    p.add_argument("--params", help="parameter JSON file")
    p.set_defaults(fn=cmd_screenshot)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
