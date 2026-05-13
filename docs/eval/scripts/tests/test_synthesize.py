# docs/eval/scripts/tests/test_synthesize.py
from __future__ import annotations

from docs.eval.scripts.synthesize_questions import (
    Place,
    template_geographic,
    template_multi_place,
    template_per_neighborhood,
    template_single_place,
    write_candidate_tsv,
)


def _place(**o):
    base = {"name": "Cathedral of Saint John the Divine", "neighborhood": "Morningside Heights", "source_type": "wikipedia"}
    base.update(o)
    return Place(**base)


def test_single_place_templates_produce_at_least_three_variants():
    place = _place()
    qs = template_single_place(place)
    assert len(qs) >= 3
    assert any(place.name in q for q in qs)


def test_multi_place_template_uses_two_places():
    p1 = _place(name="Flatiron Building", neighborhood="Flatiron District")
    p2 = _place(name="Empire State Building", neighborhood="Midtown")
    qs = template_multi_place([p1, p2])
    assert len(qs) >= 1
    assert any("Flatiron" in q and "Empire State" in q for q in qs)


def test_geographic_template_includes_neighborhood():
    qs = template_geographic("SoHo")
    assert any("SoHo" in q for q in qs)
    assert all("Manhattan" in q or "SoHo" in q for q in qs)


def test_per_neighborhood_template_emits_known_neighborhoods():
    qs = template_per_neighborhood(["Harlem", "FiDi"])
    assert any("Harlem" in q for q in qs)
    assert any("FiDi" in q or "Financial District" in q for q in qs)


def test_write_candidate_tsv_emits_curation_columns(tmp_path):
    out = tmp_path / "candidates.tsv"
    rows = [
        {"question": "Q1?", "category": "single_place", "region": "MH", "expected_source_types": "wikipedia,osm"},
        {"question": "Q2?", "category": "multi_place", "region": "Midtown", "expected_source_types": "wikipedia"},
    ]
    write_candidate_tsv(out, rows)
    text = out.read_text()
    assert "question\tcategory\tregion\texpected_source_types\taccept\tedited_question\tnotes" in text
    assert "Q1?" in text
    assert "Q2?" in text
