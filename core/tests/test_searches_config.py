"""Tests for searches.yaml expansion (no network)."""

from jobpilot.config import expand_searches_to_scrape_calls


def test_expand_queries_times_locations():
    raw = {
        "defaults": {
            "location": "Netherlands",
            "distance": 1000,
            "hours_old": 240,
            "results_per_site": 0,
        },
        "locations": [
            {"location": "Netherlands", "remote": False},
        ],
        "queries": [
            {"query": "Software Engineer", "tier": 1},
            {"query": "AI Engineer", "tier": 1},
        ],
    }
    calls = expand_searches_to_scrape_calls(raw)
    assert len(calls) == 2
    assert calls[0]["search_term"] == "Software Engineer"
    assert calls[1]["search_term"] == "AI Engineer"
    for c in calls:
        assert c["location"] == "Netherlands"
        assert c["is_remote"] is False
        assert c["distance"] == 1000
        assert c["hours_old"] == 240
        assert c["results_wanted"] == 1000
        assert c["site_name"] == "linkedin"


def test_expand_without_locations_uses_defaults():
    raw = {
        "defaults": {
            "location": "Netherlands",
            "results_per_site": 10,
        },
        "queries": [{"query": "Dev", "tier": 1}],
    }
    calls = expand_searches_to_scrape_calls(raw)
    assert len(calls) == 1
    assert calls[0]["search_term"] == "Dev"
    assert calls[0]["location"] == "Netherlands"
    assert calls[0]["is_remote"] is False
    assert calls[0]["results_wanted"] == 10
