"""The harvested-link universe: what we know how to fetch for a source, off disk."""

import json

import pytest

from leaderspeech.text_scraper import links
from leaderspeech.text_scraper.recipe import load_recipe

RECIPE_YAML = r"""
source_id: xxx_gov
country: Testland
source_language: English
start_urls: ["https://x.gov/speeches"]
listing: { link_pattern: "/speech/\\d+" }
pagination: { type: query_param, param: page }
title: { selectors: ["h1"] }
text: { selectors: ["article"] }
date: { selectors: [".date"] }
"""

SELECTOR_ONLY_YAML = RECIPE_YAML.replace(
    r'listing: { link_pattern: "/speech/\\d+" }', 'listing: { link_selector: "a.item" }')


@pytest.fixture
def recipe(tmp_path):
    path = tmp_path / "xxx_gov.yml"
    path.write_text(RECIPE_YAML, encoding="utf-8")
    return load_recipe(path)


def _write(path, urls):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    return path


def _run(country_dir, sid, urls, listing=None):
    path = _write(country_dir / f"{sid}_links.txt", urls)
    if listing is not None:  # the dated snapshot is what carries a run's sidecar
        _write(country_dir / "sample" / f"{sid}_links_20260101-000000.txt", urls)
        (country_dir / "sample" / f"{sid}_links_20260101-000000.json").write_text(
            json.dumps({"listing": listing}), encoding="utf-8")
    return path


def _probe(country_dir, sid, stamp, urls, listing=None):
    _write(country_dir / "sample" / f"{sid}_probe_{stamp}.txt", urls)
    if listing is not None:
        (country_dir / "sample" / f"{sid}_probe_{stamp}.json").write_text(
            json.dumps({"listing": listing}), encoding="utf-8")


SPREAD = {"mode": "spread (full history)", "stopped_early": False, "stop_reason": "empty_page"}


# --- normalization ------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("https://WWW.X.gov/A/", "x.gov/a"),
    ("http://x.gov:80//a", "x.gov/a"),
    ("https://x.gov/a", "x.gov/a"),
    ("  https://x.gov/a///  ", "x.gov/a"),
])
def test_normalize_url_collapses_scheme_www_port_and_slashes(raw, expected):
    assert links.normalize_url(raw) == expected


def test_normalize_url_keeps_the_query_string():
    """Query-addressed sites (?id=123) are whole distinct documents — collapsing them
    would silently halve those sources."""
    assert links.normalize_url("https://x.gov/p?id=1") != links.normalize_url("https://x.gov/p?id=2")


# --- the union ----------------------------------------------------------------------

def test_union_beats_any_single_file(tmp_path, recipe):
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1", "https://x.gov/speech/2"])
    _write(d / "sample" / "xxx_gov_links_20260101-000000.txt",
           ["https://x.gov/speech/2", "https://x.gov/speech/3"])
    _probe(d, "xxx_gov", "20260102-000000",
           ["https://x.gov/speech/3", "https://x.gov/speech/4"], SPREAD)

    u = links.link_universe(d, "xxx_gov", recipe=recipe)
    assert u.n_unique == 4          # no single file holds more than 2
    assert u.n_files == 3
    assert u.kinds == {"run", "run_snapshot", "probe"}


def test_dedupes_across_files_after_normalizing(tmp_path, recipe):
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://www.x.gov/speech/1/"])
    _probe(d, "xxx_gov", "20260102-000000", ["http://x.gov:80/speech/1"], SPREAD)
    assert links.link_universe(d, "xxx_gov", recipe=recipe).n_unique == 1


def test_sibling_ids_do_not_cross_match(tmp_path, recipe):
    """`gha_presidency` must never pick up `gha_presidency_wayback`'s lists — the exact
    name plus the literal `_links_`/`_probe_` infix is what keeps them apart."""
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1"])
    _run(d, "xxx_gov_wayback", ["https://x.gov/speech/8", "https://x.gov/speech/9"])
    _probe(d, "xxx_gov_wayback", "20260102-000000", ["https://x.gov/speech/7"], SPREAD)

    assert links.link_universe(d, "xxx_gov", recipe=recipe).n_unique == 1
    assert links.link_universe(d, "xxx_gov_wayback", recipe=recipe).n_unique == 3


def test_wayback_extend_list_is_counted(tmp_path, recipe):
    """Its captures are scraped into the SAME `<id>.csv` and counted in `n_speeches`, so
    leaving its URLs out of the denominator would manufacture a percentage above 100."""
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1"])
    _write(d / "xxx_gov_wayback_extend_links.txt", ["https://x.gov/speech/2"])
    assert links.discover_sources(tmp_path).keys() == {"xxx_gov"}   # no phantom source id


# --- the recipe re-filter -----------------------------------------------------------

def test_recipe_filter_drops_stale_wide_links(tmp_path, recipe):
    """The regression this module exists for: a tightened `link_pattern` must retire the
    links it no longer harvests, without deleting any history."""
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1", "https://x.gov/speech/2"])
    _probe(d, "xxx_gov", "20260102-000000", ["https://x.gov/gallery/9"], SPREAD)

    u = links.link_universe(d, "xxx_gov", recipe=recipe)
    assert u.n_unique == 2
    assert u.n_dropped_by_pattern == 1
    assert u.unfiltered is False


def test_pattern_is_matched_against_the_raw_url_not_the_normalized_key(tmp_path):
    """Patterns are written against real absolute URLs and many anchor on the scheme or
    host; matching a normalized key would reject everything."""
    path = tmp_path / "r.yml"
    path.write_text(RECIPE_YAML.replace(r'"/speech/\\d+"', r'"^https://x\\.gov/speech/"'),
                    encoding="utf-8")
    recipe = load_recipe(path)
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1", "https://x.gov/speech/2"])
    assert links.link_universe(d, "xxx_gov", recipe=recipe).n_unique == 2


def test_the_listing_index_itself_is_dropped(tmp_path, recipe):
    """A URL whose path equals a start_url's path is the index page, not a speech —
    mirroring `wayback.filter_entries_for_recipe`."""
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speeches?page=2", "https://x.gov/speech/1"])
    assert links.link_universe(d, "xxx_gov", recipe=recipe).n_unique == 1


def test_selector_only_recipe_cannot_be_refiltered(tmp_path):
    path = tmp_path / "r.yml"
    path.write_text(SELECTOR_ONLY_YAML, encoding="utf-8")
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1", "https://x.gov/gallery/9"])

    u = links.link_universe(d, "xxx_gov", recipe=load_recipe(path))
    assert u.n_unique == 2 and u.unfiltered is True
    assert u.status() == "unfiltered"


def test_no_recipe_leaves_the_union_unfiltered(tmp_path):
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1", "https://x.gov/gallery/9"])
    u = links.link_universe(d, "xxx_gov", recipe=None)
    assert u.n_unique == 2 and u.unfiltered is True


# --- status -------------------------------------------------------------------------

def test_status_complete_and_probe_only(tmp_path, recipe):
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1"])
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status() == "complete"

    d2 = tmp_path / "Other"
    _probe(d2, "xxx_gov", "20260102-000000", ["https://x.gov/speech/1"], SPREAD)
    assert links.link_universe(d2, "xxx_gov", recipe=recipe).status() == "probe_only"


def test_status_page1_only(tmp_path, recipe):
    """A probe run without --spread sees page 1 of the first start_url only, and is the
    one branch whose report carries no `mode`."""
    d = tmp_path / "Testland"
    _probe(d, "xxx_gov", "20260102-000000", ["https://x.gov/speech/1"],
           {"url": "https://x.gov/speeches", "links_found": 1})
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status() == "page1_only"


def test_status_stopped_early(tmp_path, recipe):
    d = tmp_path / "Testland"
    _probe(d, "xxx_gov", "20260102-000000", ["https://x.gov/speech/1"],
           {"mode": "spread (full history)", "stopped_early": True,
            "stop_reason": "no_new_links"})
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status() == "stopped_early"


def test_status_capped_on_max_pages(tmp_path, recipe):
    """`max_pages` is in `paginate.NORMAL_STOPS`, so a harvest that died at the 200-page
    default reports stopped_early=False and looks like a clean finish. It is still a floor."""
    d = tmp_path / "Testland"
    _probe(d, "xxx_gov", "20260102-000000", ["https://x.gov/speech/1"],
           {"mode": "spread (full history)", "stopped_early": False,
            "stop_reason": "max_pages"})
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status() == "capped"


def test_truncation_flag_outranks_a_clean_run(tmp_path, recipe):
    """A run and a probe share `paginate.harvest_links`, so a pager that broke for one
    broke for the other."""
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1", "https://x.gov/speech/2"])
    _probe(d, "xxx_gov", "20260102-000000",
           ["https://x.gov/speech/1", "https://x.gov/speech/3"],
           {"mode": "spread (full history)", "stopped_early": True, "stop_reason": "no_new_links"})
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status() == "stopped_early"


def test_a_small_stale_harvest_does_not_brand_the_source(tmp_path, recipe):
    """One truncated 1-link probe must not permanently flag a source since crawled in
    full — the verdict only counts from a harvest at least half the size of the biggest."""
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", [f"https://x.gov/speech/{i}" for i in range(50)])
    _probe(d, "xxx_gov", "20260102-000000", ["https://x.gov/speech/1"],
           {"mode": "spread (full history)", "stopped_early": True, "stop_reason": "no_new_links"})
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status() == "complete"


def test_status_stale_links_when_scraped_exceeds_known(tmp_path, recipe):
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1"])
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status(n_scraped=99) == "stale_links"


def test_status_post_limit_for_audio(tmp_path, recipe):
    """The audio harvester writes its list AFTER --max-videos, so the count equals what was
    fetched and says nothing about the channel's real size."""
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1"])
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status(audio=True) == "post_limit"


def test_run_sidecar_is_read_by_the_same_rule_as_a_probes(tmp_path, recipe):
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1"],
         listing={"mode": "run (query_param)", "links_found": 1,
                  "stopped_early": False, "stop_reason": "max_pages"})
    assert links.link_universe(d, "xxx_gov", recipe=recipe).status() == "capped"


# --- edges --------------------------------------------------------------------------

def test_no_link_record_is_blank_not_zero(tmp_path, recipe):
    """`arg_casarosada` / `chl_presidencia` predate link lists. Reporting 0 there would
    read as "we know of zero links", the opposite of the truth."""
    u = links.link_universe(tmp_path / "Testland", "xxx_gov", recipe=recipe)
    assert u.found is False and u.n_unique == 0 and u.status() == ""


def test_empty_link_file_is_found_but_zero(tmp_path, recipe):
    """The audio harvester writes an empty file on an empty harvest — "we looked and found
    nothing" must stay distinguishable from "we never looked"."""
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", [])
    u = links.link_universe(d, "xxx_gov", recipe=recipe)
    assert u.found is True and u.n_unique == 0


def test_corrupt_sidecar_json_does_not_raise(tmp_path, recipe):
    """Neither writer is atomic and a Dropbox sync can catch one mid-flight."""
    d = tmp_path / "Testland"
    _probe(d, "xxx_gov", "20260102-000000", ["https://x.gov/speech/1"], SPREAD)
    (d / "sample" / "xxx_gov_probe_20260102-000000.json").write_text(
        '{"listing": ', encoding="utf-8")
    u = links.link_universe(d, "xxx_gov", recipe=recipe)
    assert u.n_unique == 1 and u.stopped_early is False


def test_bom_crlf_blank_and_non_http_lines(tmp_path, recipe):
    d = tmp_path / "Testland"
    (d).mkdir(parents=True)
    (d / "xxx_gov_links.txt").write_text(
        "﻿https://x.gov/speech/1\r\n\r\n# a note\r\nhttps://X.gov/speech/1/\r\n",
        encoding="utf-8")
    assert links.link_universe(d, "xxx_gov", recipe=recipe).n_unique == 1


def test_discover_sources_finds_sources_with_no_csv(tmp_path, recipe):
    d = tmp_path / "Testland"
    _run(d, "xxx_gov", ["https://x.gov/speech/1"])
    _probe(d, "yyy_gov", "20260102-000000", ["https://x.gov/speech/2"], SPREAD)
    _write(d / "sample" / "zzz_gov_links_20260101-000000.txt", ["https://x.gov/speech/3"])
    assert links.discover_sources(tmp_path) == {
        "xxx_gov": d, "yyy_gov": d, "zzz_gov": d}
