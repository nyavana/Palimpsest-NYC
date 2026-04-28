"""Raw-cache tests — file-backed JSON cache used by ingestors."""

from __future__ import annotations

import json

import pytest

from app.ingest.raw_cache import RawCache


def test_get_returns_none_for_unseen_key(tmp_path):
    cache = RawCache(tmp_path)
    assert cache.get("https://example.test/a") is None


def test_put_then_get_round_trips(tmp_path):
    cache = RawCache(tmp_path)
    payload = {"hello": "world", "n": 7}
    cache.put("https://example.test/a", payload)
    assert cache.get("https://example.test/a") == payload


def test_put_isolates_payloads_per_url(tmp_path):
    cache = RawCache(tmp_path)
    cache.put("u1", {"k": 1})
    cache.put("u2", {"k": 2})
    assert cache.get("u1") == {"k": 1}
    assert cache.get("u2") == {"k": 2}


def test_files_land_under_provided_root(tmp_path):
    cache = RawCache(tmp_path)
    cache.put("https://example.test/a/b?c=1", {"x": 1})
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1


def test_corrupt_cache_file_returns_none(tmp_path):
    """A half-written cache file from a crashed run shouldn't crash callers —
    they should treat it as a miss and re-fetch."""
    cache = RawCache(tmp_path)
    cache.put("u", {"a": 1})
    # Corrupt the cache file
    fp = next(tmp_path.rglob("*.json"))
    fp.write_text("{not valid json")
    assert cache.get("u") is None


def test_put_is_atomic_via_tmp_file(tmp_path):
    """Writing the cache via a tmp file + rename means a partial write
    should not leave a half-file at the canonical path."""
    cache = RawCache(tmp_path)
    cache.put("u", {"a": 1})
    fp = next(tmp_path.rglob("*.json"))
    parsed = json.loads(fp.read_text())
    assert parsed == {"a": 1}


@pytest.mark.parametrize(
    "url1,url2",
    [
        ("https://a.test/x", "https://A.TEST/x"),  # case-sensitive on purpose
        ("https://a.test/x?b=1", "https://a.test/x?b=2"),  # query differs
    ],
)
def test_distinct_urls_get_distinct_files(tmp_path, url1, url2):
    cache = RawCache(tmp_path)
    cache.put(url1, {"v": 1})
    cache.put(url2, {"v": 2})
    assert cache.get(url1) == {"v": 1}
    assert cache.get(url2) == {"v": 2}
