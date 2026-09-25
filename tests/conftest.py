import os
import sys

import cadquery as cq
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scb_designer import demo_pcba  # noqa: E402
from scb_designer.demo_pcba import GREEN, NAVY, TERM_GREEN, _Builder  # noqa: E402
from scb_designer.pcba import analyze  # noqa: E402
from scb_designer.step_io import ModelPart, export_step, load_step  # noqa: E402

DEMO_STEP = os.path.join(ROOT, "demo", "ac_controller_pcba.step")


def build_small_board():
    """A 60 x 40 mm board with a few parts on both sides (fast to design)."""
    b = _Builder()
    board = (cq.Workplane("XY").box(60, 40, demo_pcba.BOARD_T, centered=False)
             .faces(">Z").workplane(origin=(0, 0, demo_pcba.BOARD_T))
             .pushPoints([(30.0, 20.0)]).hole(3.2))
    b.parts.append(ModelPart("PCB small test board", board.val(), GREEN))
    b.chip("R1 0603", 10.0, 10.0, "0603")
    b.chip("C1 0805", 10.0, 30.0, "0805", angle=30)
    b.soic("U1 SO-8", 45.0, 30.0, pins=8)
    b.dpak("Q1 D-PAK power", 45.0, 10.0)
    b.tht_cyl("C2 Electrolytic 8x12", 20.0, 20.0, 8.0, 12.0, 3.5, NAVY)
    b.sot23("Q2 SOT-23 bottom", 40.0, 20.0, bottom=True)
    b.chip("R2 0603 bottom", 50.0, 20.0, "0603", bottom=True)
    return b.parts


@pytest.fixture(scope="session")
def small_parts():
    return build_small_board()


@pytest.fixture(scope="session")
def small_step(tmp_path_factory, small_parts):
    path = str(tmp_path_factory.mktemp("small") / "small_board.step")
    export_step(small_parts, path, name="small")
    return path


@pytest.fixture(scope="session")
def small_pcba(small_step):
    return analyze(load_step(small_step))


@pytest.fixture(scope="session")
def demo_parts():
    assert os.path.isfile(DEMO_STEP), "demo STEP file is missing"
    return load_step(DEMO_STEP)


@pytest.fixture(scope="session")
def demo_pcba_model(demo_parts):
    return analyze(demo_parts)


@pytest.fixture(scope="session")
def small_designer(small_pcba):
    from scb_designer.design import SCBDesigner
    return SCBDesigner(small_pcba)


@pytest.fixture(scope="session")
def small_generated(small_designer):
    return small_designer.generate_all()
