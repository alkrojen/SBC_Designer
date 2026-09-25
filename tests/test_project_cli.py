import os

import cadquery as cq

from sbc_designer import cli
from sbc_designer.demo_pcba import default_demo_path, write_demo
from sbc_designer.design import ALIGNMENT, BOTH, SCREWS, SBCParameters
from sbc_designer.project import Project
from sbc_designer.step_io import ModelPart, export_step, load_step


def test_project_load_generate_export(small_step, tmp_path):
    pr = Project()
    pr.load(small_step)
    assert pr.can_design and pr.name == "small_board.step"
    assert len(pr.display_parts) == len(pr.raw_parts)
    parts = pr.generate(ALIGNMENT, "top")
    assert parts and pr.generated[(ALIGNMENT, "top")] is parts
    pr.generate(SCREWS, "top")  # screws are always shared
    assert (SCREWS, BOTH) in pr.generated
    out = pr.export(None, str(tmp_path / "out.step"))
    names = [p.name for p in load_step(out)]
    assert any("alignment" in n for n in names) and any("screws" in n for n in names)
    files = pr.export_each(str(tmp_path / "each"))
    assert len(files) == 2 and all(os.path.isfile(f) for f in files)
    rep = pr.report()
    assert "Board: 60.0 x 40.0" in rep and "keyed pockets" in rep


def test_project_rejects_non_pcba_but_still_views(tmp_path):
    path = str(tmp_path / "cube.step")
    export_step([ModelPart("cube", cq.Solid.makeBox(10, 10, 10))], path)
    pr = Project()
    pr.load(path)
    assert not pr.can_design
    assert pr.display_parts and "No printed circuit board" in pr.report()


def test_project_params_change_clears_generated(small_step):
    pr = Project()
    pr.load(small_step)
    pr.generate(ALIGNMENT, "top")
    p = SBCParameters()
    p.alignment_thickness = 1.5
    pr.set_params(p)
    assert pr.generated == {}
    assert pr.designer.layout.z.align_top == 1.6 + 1.5


def test_cli_info_and_generate(small_step, tmp_path, capsys):
    assert cli.main(["info", small_step]) == 0
    assert "keyed pockets" in capsys.readouterr().out
    out = str(tmp_path / "a.step")
    assert cli.main(["generate", small_step, "--part", "cover", "--side", "both", "-o", out]) == 0
    names = [p.name for p in load_step(out)]
    assert sum("cover plate" in n for n in names) == 2
    assert cli.main(["generate", small_step]) == 2


def test_cli_screenshot(small_step, tmp_path):
    out = str(tmp_path / "v.png")
    assert cli.main(["screenshot", small_step, "-o", out, "--width", "320", "--height", "240"]) == 0
    assert os.path.getsize(out) > 1000


def test_demo_file_is_shipped_and_reproducible(tmp_path):
    shipped = default_demo_path()
    assert os.path.isfile(shipped)
    fresh = write_demo(str(tmp_path / "demo.step"))
    a, b = load_step(shipped), load_step(fresh)
    assert [p.name for p in a] == [p.name for p in b]
