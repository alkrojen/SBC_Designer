import dataclasses

import pytest

from scb_designer.design.params import SCBParameters


def test_defaults_are_valid_and_follow_the_project_description():
    p = SCBParameters()
    p.validate()
    assert 0.75 <= p.alignment_thickness <= 2.7
    assert p.screw_pitch == 30.0 and p.screw_diameter == 2.5
    assert (p.cover_skin, p.rib_height, p.rib_pitch) == (1.2, 5.0, 10.0)
    assert "D-PAK" in p.power_keyword_list


def test_every_field_has_a_label_and_group():
    for f in dataclasses.fields(SCBParameters):
        assert f.metadata.get("label")
        assert f.metadata.get("group")


@pytest.mark.parametrize("changes", [
    dict(alignment_thickness=0.5),
    dict(alignment_thickness=3.0),
    dict(channel_depth=2.5, alignment_thickness=2.0),
    dict(interior_screws="everywhere"),
    dict(gasket_offset=13.9),
    dict(screw_edge_offset=6.0),
])
def test_invalid_values_rejected(changes):
    with pytest.raises(ValueError):
        dataclasses.replace(SCBParameters(), **changes).validate()


def test_json_roundtrip(tmp_path):
    p = dataclasses.replace(SCBParameters(), alignment_thickness=1.5, interior_screws="grid",
                            power_keywords="TO-220")
    path = str(tmp_path / "p.json")
    p.save(path)
    q = SCBParameters.load(path)
    assert q == p
    assert q.power_keyword_list == ("TO-220",)


def test_from_dict_ignores_unknown_keys_and_coerces_types():
    p = SCBParameters.from_dict({"alignment_thickness": "1.2", "bogus": 3})
    assert p.alignment_thickness == 1.2
