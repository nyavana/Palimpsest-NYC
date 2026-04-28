"""Citation contract verifier tests — directly translates the locked
contract scenarios from `agent-tools/spec.md` into pytest assertions.
"""

from __future__ import annotations

import pytest

from app.agent.citations import (
    CitationError,
    RetrievalLedger,
    parse_narration_response,
    verify_citations,
)


def _hit(
    doc_id: str = "wikipedia:Cathedral_of_Saint_John_the_Divine",
    source_type: str = "wikipedia",
    source_url: str = "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine",
) -> dict[str, object]:
    return {"doc_id": doc_id, "source_type": source_type, "source_url": source_url}


def test_parse_response_extracts_narration_and_citations():
    payload = (
        '{"narration": "Hello.", "citations": [{"doc_id": "wikipedia:X", '
        '"source_url": "https://en.wikipedia.org/wiki/X", "source_type": "wikipedia", '
        '"span": "intro", "retrieval_turn": 1}]}'
    )
    parsed = parse_narration_response(payload)
    assert parsed.narration == "Hello."
    assert len(parsed.citations) == 1


def test_parse_response_handles_extra_text_around_json():
    """LLMs sometimes wrap JSON in prose. The parser pulls the JSON object out."""
    payload = (
        'Here is my answer:\n```json\n'
        '{"narration": "x", "citations": [{"doc_id": "wikipedia:A", '
        '"source_url": "https://en.wikipedia.org/wiki/A", "source_type": "wikipedia", '
        '"span": "", "retrieval_turn": 1}]}\n```\n'
    )
    parsed = parse_narration_response(payload)
    assert parsed.narration == "x"


def test_parse_response_invalid_json_raises():
    with pytest.raises(CitationError):
        parse_narration_response("not json at all")


def test_parse_response_missing_narration_raises():
    payload = '{"citations": []}'
    with pytest.raises(CitationError):
        parse_narration_response(payload)


def test_parse_response_missing_citations_array_raises():
    payload = '{"narration": "x"}'
    with pytest.raises(CitationError):
        parse_narration_response(payload)


# ── Verifier scenarios from the locked spec ─────────────────────────


def test_citation_for_retrieved_doc_passes():
    ledger = RetrievalLedger()
    ledger.add(turn=1, hits=[_hit()])
    parsed = parse_narration_response(
        '{"narration": "n", "citations": [{"doc_id": '
        '"wikipedia:Cathedral_of_Saint_John_the_Divine", '
        '"source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine", '
        '"source_type": "wikipedia", "span": "intro", "retrieval_turn": 1}]}'
    )
    verify_citations(parsed, ledger=ledger, current_turn=2)  # raises on failure


def test_citation_for_unretrieved_doc_rejected():
    ledger = RetrievalLedger()
    parsed = parse_narration_response(
        '{"narration": "n", "citations": [{"doc_id": "wikipedia:Made_Up_Page", '
        '"source_url": "https://en.wikipedia.org/wiki/Made_Up_Page", '
        '"source_type": "wikipedia", "span": "", "retrieval_turn": 1}]}'
    )
    with pytest.raises(CitationError) as ei:
        verify_citations(parsed, ledger=ledger, current_turn=2)
    assert "not retrieved" in str(ei.value).lower() or "unknown" in str(ei.value).lower()


def test_citation_with_future_retrieval_turn_rejected():
    ledger = RetrievalLedger()
    ledger.add(turn=1, hits=[_hit()])
    parsed = parse_narration_response(
        '{"narration": "n", "citations": [{"doc_id": '
        '"wikipedia:Cathedral_of_Saint_John_the_Divine", '
        '"source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine", '
        '"source_type": "wikipedia", "span": "", "retrieval_turn": 4}]}'
    )
    with pytest.raises(CitationError) as ei:
        verify_citations(parsed, ledger=ledger, current_turn=2)
    assert "future" in str(ei.value).lower() or "retrieval_turn" in str(ei.value).lower()


def test_citation_source_type_mismatch_rejected():
    ledger = RetrievalLedger()
    ledger.add(turn=1, hits=[_hit(source_type="osm")])
    parsed = parse_narration_response(
        '{"narration": "n", "citations": [{"doc_id": '
        '"wikipedia:Cathedral_of_Saint_John_the_Divine", '
        '"source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine", '
        '"source_type": "wikipedia", "span": "", "retrieval_turn": 1}]}'
    )
    with pytest.raises(CitationError) as ei:
        verify_citations(parsed, ledger=ledger, current_turn=2)
    assert "source_type" in str(ei.value).lower() or "mismatch" in str(ei.value).lower()


def test_span_is_opaque_to_verifier():
    """span MAY be any string, including empty. The verifier must not parse it."""
    import json as _json

    ledger = RetrievalLedger()
    ledger.add(turn=1, hits=[_hit()])
    for span_value in ("", "intro", "anything-here", "lol §3.4", "🎉"):
        parsed = parse_narration_response(
            '{"narration": "n", "citations": [{"doc_id": '
            '"wikipedia:Cathedral_of_Saint_John_the_Divine", '
            '"source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine", '
            '"source_type": "wikipedia", "span": ' + _json.dumps(span_value) + ', '
            '"retrieval_turn": 1}]}'
        )
        verify_citations(parsed, ledger=ledger, current_turn=1)


def test_empty_citations_array_rejected():
    ledger = RetrievalLedger()
    parsed = parse_narration_response('{"narration": "n", "citations": []}')
    with pytest.raises(CitationError) as ei:
        verify_citations(parsed, ledger=ledger, current_turn=1)
    assert "empty" in str(ei.value).lower() or "uncited" in str(ei.value).lower()


def test_empty_narration_rejected():
    ledger = RetrievalLedger()
    ledger.add(turn=1, hits=[_hit()])
    parsed = parse_narration_response(
        '{"narration": "", "citations": [{"doc_id": '
        '"wikipedia:Cathedral_of_Saint_John_the_Divine", '
        '"source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine", '
        '"source_type": "wikipedia", "span": "", "retrieval_turn": 1}]}'
    )
    with pytest.raises(CitationError):
        verify_citations(parsed, ledger=ledger, current_turn=1)


def test_source_type_outside_v1_enum_rejected():
    """Spec: source_type SHALL equal the V1 enum (wikipedia | wikidata | osm)."""
    ledger = RetrievalLedger()
    ledger.add(turn=1, hits=[_hit(source_type="wikipedia")])
    parsed = parse_narration_response(
        '{"narration": "n", "citations": [{"doc_id": '
        '"wikipedia:Cathedral_of_Saint_John_the_Divine", '
        '"source_url": "https://en.wikipedia.org/wiki/Cathedral_of_Saint_John_the_Divine", '
        '"source_type": "chronicling-america", "span": "", "retrieval_turn": 1}]}'
    )
    with pytest.raises(CitationError):
        verify_citations(parsed, ledger=ledger, current_turn=1)


def test_source_url_must_be_https():
    ledger = RetrievalLedger()
    ledger.add(turn=1, hits=[_hit(source_url="http://example.test/x")])
    parsed = parse_narration_response(
        '{"narration": "n", "citations": [{"doc_id": '
        '"wikipedia:Cathedral_of_Saint_John_the_Divine", '
        '"source_url": "http://example.test/x", "source_type": "wikipedia", '
        '"span": "", "retrieval_turn": 1}]}'
    )
    with pytest.raises(CitationError):
        verify_citations(parsed, ledger=ledger, current_turn=1)
