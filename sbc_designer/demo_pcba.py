"""Builder for the demo PCBA: an indoor-unit air-conditioner controller.

The board is 160 x 100 x 1.6 mm FR-4 with a mains section (terminal block,
fuse, varistor, X2 capacitor, bridge, bulk capacitor, flyback transformer and
switcher), a relay section (compressor, fan and 4-way-valve relays, a fan
triac on a D-PAK), and a low-voltage section (MCU, stepper driver, op-amp,
sensor/stepper/display connectors, buzzer, regulator, passives).  The bottom
side carries a handful of SMD parts plus the protruding leads of every
through-hole part.

Run ``python -m sbc_designer.demo_pcba [out.step]`` to regenerate the file
shipped in ``demo/``.
"""

from __future__ import annotations

import math
import os
import sys
from typing import List, Optional, Sequence, Tuple

import cadquery as cq

from .step_io import ModelPart, export_step

BOARD_L = 160.0
BOARD_W = 100.0
BOARD_T = 1.6
LEAD_OUT = 1.5  # through-hole lead protrusion below the board
MOUNT_HOLES = [(4.0, 4.0), (156.0, 4.0), (4.0, 96.0), (156.0, 96.0), (64.0, 54.0)]
MOUNT_HOLE_D = 3.2

# colours
GREEN = (0.05, 0.36, 0.16)
BLACK = (0.08, 0.08, 0.09)
DARK = (0.18, 0.18, 0.2)
TAN = (0.72, 0.58, 0.38)
BLUE = (0.12, 0.3, 0.75)
NAVY = (0.08, 0.12, 0.35)
WHITE = (0.92, 0.9, 0.84)
YELLOW = (0.9, 0.78, 0.2)
TERM_GREEN = (0.15, 0.55, 0.3)
SILVER = (0.75, 0.75, 0.78)
RED = (0.85, 0.1, 0.1)


def _box(x, y, z0, lx, ly, h) -> cq.Workplane:
    return cq.Workplane("XY").box(lx, ly, h, centered=(True, True, False)).translate((x, y, z0))


def _cyl(x, y, z0, d, h) -> cq.Workplane:
    return cq.Workplane("XY").circle(d / 2).extrude(h).translate((x, y, z0))


def _pins(pts: Sequence[Tuple[float, float]], d=0.8) -> cq.Workplane:
    """Through-hole leads from the top surface down through the board."""
    wp = None
    for (x, y) in pts:
        c = _cyl(x, y, -LEAD_OUT, d, BOARD_T + LEAD_OUT + 0.5)
        wp = c if wp is None else wp.union(c)
    return wp


def _rot(wp: cq.Workplane, cx, cy, angle) -> cq.Workplane:
    if not angle:
        return wp
    return wp.rotate((cx, cy, 0), (cx, cy, 1), angle)


class _Builder:
    def __init__(self):
        self.parts: List[ModelPart] = []

    def add(self, name, wp: cq.Workplane, color, bottom=False):
        shape = wp.val() if len(wp.vals()) == 1 else cq.Compound.makeCompound(wp.vals())
        if bottom:
            shape = shape.mirror("XY", (0, 0, BOARD_T / 2))
        self.parts.append(ModelPart(name, shape, color))

    # --- generic SMD packages -------------------------------------------- #
    def chip(self, name, x, y, size="0603", angle=0, color=DARK, bottom=False):
        l, w, h = {"0402": (1.0, 0.5, 0.35), "0603": (1.6, 0.8, 0.45),
                   "0805": (2.0, 1.25, 0.5), "1206": (3.2, 1.6, 0.55)}[size]
        body = _box(x, y, BOARD_T, l, w, h)
        self.add(name, _rot(body, x, y, angle), color, bottom)

    def sot23(self, name, x, y, angle=0, bottom=False):
        body = _box(x, y, BOARD_T + 0.1, 2.9, 1.3, 1.0)
        leads = (_box(x - 0.95, y - 0.95, BOARD_T, 0.4, 0.6, 0.15)
                 .union(_box(x + 0.95, y - 0.95, BOARD_T, 0.4, 0.6, 0.15))
                 .union(_box(x, y + 0.95, BOARD_T, 0.4, 0.6, 0.15)))
        self.add(name, _rot(body.union(leads), x, y, angle), BLACK, bottom)

    def soic(self, name, x, y, pins=8, angle=0, bottom=False):
        n = pins // 2
        length = 1.27 * (n - 1) + 1.2
        body = _box(x, y, BOARD_T + 0.1, length, 3.9, 1.65)
        leads = None
        for i in range(n):
            px = x - 1.27 * (n - 1) / 2 + i * 1.27
            for sy in (-1, 1):
                ld = _box(px, y + sy * 2.5, BOARD_T, 0.42, 1.1, 0.2)
                leads = ld if leads is None else leads.union(ld)
        self.add(name, _rot(body.union(leads), x, y, angle), BLACK, bottom)

    def qfp(self, name, x, y, body=7.0, pins=48, bottom=False):
        n = pins // 4
        pitch = 0.5
        b = _box(x, y, BOARD_T + 0.1, body, body, 1.4)
        span = pitch * (n - 1)
        leads = None
        for i in range(n):
            o = -span / 2 + i * pitch
            for (dx, dy, lx, ly) in ((o, body / 2 + 0.5, 0.22, 1.0), (o, -body / 2 - 0.5, 0.22, 1.0),
                                     (body / 2 + 0.5, o, 1.0, 0.22), (-body / 2 - 0.5, o, 1.0, 0.22)):
                ld = _box(x + dx, y + dy, BOARD_T, lx, ly, 0.2)
                leads = ld if leads is None else leads.union(ld)
        self.add(name, b.union(leads), BLACK, bottom)

    def dpak(self, name, x, y, angle=0, bottom=False):
        body = _box(x, y + 0.8, BOARD_T, 6.6, 6.1, 2.3)
        tab = _box(x, y - 2.9, BOARD_T, 5.4, 1.4, 0.5)
        leads = (_box(x - 2.28, y + 4.9, BOARD_T, 0.8, 2.8, 0.5)
                 .union(_box(x + 2.28, y + 4.9, BOARD_T, 0.8, 2.8, 0.5)))
        self.add(name, _rot(body.union(tab).union(leads), x, y, angle), DARK, bottom)

    # --- through-hole parts ---------------------------------------------- #
    def tht_box(self, name, x, y, lx, ly, h, pins, color, angle=0, pin_d=0.8):
        wp = _box(x, y, BOARD_T, lx, ly, h).union(_pins([(x + px, y + py) for px, py in pins], pin_d))
        self.add(name, _rot(wp, x, y, angle), color)

    def tht_cyl(self, name, x, y, d, h, pitch, color, pin_d=0.6):
        wp = _cyl(x, y, BOARD_T + 0.3, d, h).union(
            _pins([(x - pitch / 2, y), (x + pitch / 2, y)], pin_d))
        self.add(name, wp, color)


def build_parts() -> List[ModelPart]:
    """Return the demo PCBA as a list of named, coloured parts."""
    b = _Builder()

    board = (cq.Workplane("XY").box(BOARD_L, BOARD_W, BOARD_T, centered=False)
             .edges("|Z").fillet(2.0))
    board = board.faces(">Z").workplane(origin=(0, 0, BOARD_T)).pushPoints(MOUNT_HOLES).hole(MOUNT_HOLE_D)
    b.parts.append(ModelPart("PCB AC controller 160x100 FR4", board.val(), GREEN))

    # ---------------- mains section (left) --------------------------------
    b.tht_box("J1 Terminal block 2P 7.5mm (L,N)", 11.0, 88.0, 16.0, 9.0, 12.5,
              [(-3.75, 0), (3.75, 0)], TERM_GREEN, pin_d=1.2)
    b.tht_box("F1 Fuse TR5 3.15A", 27.0, 90.0, 8.4, 4.0, 8.0, [(-2.54, 0), (2.54, 0)], BLACK)
    varistor = (cq.Workplane("XZ").circle(8.0).extrude(-5.0)
                .translate((40.0, 87.5, BOARD_T + 9.0))
                .union(_pins([(36.25, 90.0), (43.75, 90.0)], 0.8)))
    b.add("RV1 Varistor 14D471K", varistor, BLUE)
    b.tht_box("CX1 X2 capacitor 0.1uF 275VAC", 14.0, 70.0, 18.0, 8.5, 14.5,
              [(-7.5, 0), (7.5, 0)], YELLOW)
    b.tht_box("L1 Common mode choke UU9.8", 34.0, 70.0, 12.0, 13.0, 16.0,
              [(-5, -5), (5, -5), (-5, 5), (5, 5)], DARK)
    b.soic("BR1 Bridge rectifier MB6S", 48.0, 88.0, pins=4)
    b.tht_cyl("C1 Electrolytic 10uF 400V 10x16", 50.0, 70.0, 10.0, 16.0, 5.0, NAVY)
    b.tht_box("T1 Flyback transformer EE16", 20.0, 48.0, 17.0, 16.0, 14.0,
              [(-6.25, -5), (-6.25, 0), (-6.25, 5), (6.25, -5), (6.25, 0), (6.25, 5)], YELLOW)
    b.soic("U2 Offline switcher LNK304 SO-8", 40.0, 52.0, pins=8, angle=90)
    b.tht_cyl("C2 Electrolytic 470uF 25V 8x12", 48.0, 38.0, 8.0, 12.0, 3.5, NAVY)
    b.tht_cyl("C3 Electrolytic 220uF 16V 6.3x11", 36.0, 36.0, 6.3, 11.0, 2.5, NAVY)
    b.dpak("U5 Regulator 7805 D-PAK", 56.0, 52.0)
    b.chip("D1 Diode SMA ES1J", 30.0, 60.0, "1206", color=BLACK)
    b.chip("R1 1206 1M", 8.0, 58.0, "1206")
    b.chip("R2 1206 1M", 8.0, 54.0, "1206")
    b.chip("C4 0805 100nF", 44.0, 60.0, "0805", color=TAN)

    # ---------------- relay section (bottom middle / right) ---------------
    b.tht_box("K1 Relay 30A compressor", 86.0, 20.0, 30.0, 16.0, 23.0,
              [(-12.5, -5.5), (-12.5, 5.5), (10.5, -5.5), (10.5, 5.5)], BLUE, pin_d=1.2)
    b.tht_box("K2 Relay 10A fan high", 120.0, 14.0, 20.5, 10.0, 15.0,
              [(-8, -3.8), (-8, 3.8), (8, -3.8), (8, 3.8)], BLACK)
    b.tht_box("K3 Relay 10A four-way valve", 120.0, 30.0, 20.5, 10.0, 15.0,
              [(-8, -3.8), (-8, 3.8), (8, -3.8), (8, 3.8)], BLACK)
    b.tht_box("J2 Terminal block 4P 7.5mm (COMP,FAN,4WV,N)", 148.0, 22.0, 9.0, 31.0, 12.5,
              [(0, -11.25), (0, -3.75), (0, 3.75), (0, 11.25)], TERM_GREEN, pin_d=1.2)
    b.dpak("Q1 Fan triac BT137 D-PAK", 104.0, 44.0, angle=180)
    b.soic("U3 Relay/stepper driver ULN2003 SO-16", 88.0, 44.0, pins=16)
    for i, (x, y) in enumerate([(70.0, 12.0), (70.0, 28.0), (104.0, 8.0)]):
        b.chip(f"D{2 + i} Flyback diode SOD-123", x, y, "1206", angle=90, color=BLACK)
    b.chip("R3 0603 330R triac gate", 112.0, 50.0, "0603")
    b.chip("R4 0603 1k", 96.0, 50.0, "0603")
    b.sot23("Q2 NPN MMBT3904", 76.0, 52.0)

    # ---------------- low-voltage section (top right) ---------------------
    b.qfp("U1 MCU LQFP-48", 118.0, 72.0)
    b.chip("Y1 Crystal 8MHz 3225", 128.0, 64.0, "1206", color=SILVER)
    b.soic("U4 Op-amp LM358 SO-8", 96.0, 80.0, pins=8)
    b.tht_cyl("BZ1 Buzzer 12x9.5", 142.0, 58.0, 12.0, 9.5, 7.6, BLACK)
    b.tht_box("J3 JST XH 2P room sensor", 88.0, 94.0, 7.4, 5.75, 7.0, [(-1.25, 0), (1.25, 0)], WHITE)
    b.tht_box("J4 JST XH 2P pipe sensor", 100.0, 94.0, 7.4, 5.75, 7.0, [(-1.25, 0), (1.25, 0)], WHITE)
    b.tht_box("J5 JST XH 5P louver stepper", 116.0, 94.0, 14.9, 5.75, 7.0,
              [(-5.0 + 2.5 * i, 0) for i in range(5)], WHITE)
    b.tht_box("J6 Header 2x4 display board", 142.0, 92.0, 10.2, 5.1, 8.5,
              [(-3.81 + 2.54 * i, dy) for i in range(4) for dy in (-1.27, 1.27)], BLACK, pin_d=0.64)
    for i, (x, y) in enumerate([(132.0, 84.0), (136.0, 84.0), (140.0, 84.0)]):
        b.chip(f"LED{i + 1} 0805 status", x, y, "0805", color=(RED, (0.1, 0.8, 0.2), (0.95, 0.6, 0.1))[i])
    # passives around the MCU
    idx = 10
    for k in range(6):
        b.chip(f"C{idx} 0603 100nF decoupling", 110.0 + 3.0 * k, 81.0, "0603", color=TAN); idx += 1
    for k in range(4):
        b.chip(f"C{idx} 0603 100nF decoupling", 127.5, 68.0 + 3.0 * k, "0603", angle=90, color=TAN); idx += 1
    for k in range(6):
        b.chip(f"R{10 + k} 0603 10k", 108.0 + 3.0 * k, 62.0, "0603")
    for k in range(4):
        b.chip(f"R{20 + k} 0402 4k7", 106.0, 67.0 + 2.5 * k, "0402", angle=90)
    for k in range(4):
        b.chip(f"R{30 + k} 0805 thermistor divider", 88.0 + 3.5 * k, 88.0, "0805")
    b.chip("C30 0805 10uF", 100.0, 72.0, "0805", color=TAN)
    b.chip("C31 1206 22uF", 66.0, 44.0, "1206", color=TAN)

    # ---------------- bottom side -----------------------------------------
    b.soic("U6 EEPROM 24C02 SO-8", 120.0, 60.0, pins=8, bottom=True)
    b.sot23("Q3 NPN MMBT3904 buzzer", 138.0, 70.0, bottom=True)
    b.sot23("Q4 PNP MMBT3906 LED", 132.0, 76.0, angle=90, bottom=True)
    for k in range(6):
        b.chip(f"R{40 + k} 0603 bottom", 100.0 + 3.0 * k, 66.0, "0603", bottom=True)
    for k in range(4):
        b.chip(f"C{40 + k} 0603 bottom", 80.0 + 3.0 * k, 60.0, "0603", color=TAN, bottom=True)
    b.chip("R50 1206 snubber", 106.0, 36.0, "1206", bottom=True)
    b.chip("C50 1206 snubber 10nF", 110.0, 36.0, "1206", color=TAN, bottom=True)

    return b.parts


def write_demo(path: str) -> str:
    """Build the demo board and write it to ``path`` as a STEP assembly."""
    return export_step(build_parts(), path, name="AC_controller_PCBA")


def default_demo_path() -> str:
    """Location of the demo STEP file shipped with the application."""
    candidates = []
    if getattr(sys, "_MEIPASS", None):  # PyInstaller bundle
        candidates.append(os.path.join(sys._MEIPASS, "demo", "ac_controller_pcba.step"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), "demo", "ac_controller_pcba.step"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return candidates[-1]


if __name__ == "__main__":  # pragma: no cover
    out = sys.argv[1] if len(sys.argv) > 1 else default_demo_path()
    print("wrote", write_demo(out))
