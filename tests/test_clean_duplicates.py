"""Duplicate-text clustering and cause classification. Every fixture mirrors a real pattern
measured in data/scraped; the point of the cause label is that the buckets are NOT interchangeable
(see duplicates.py's module docstring)."""

import pandas as pd
import pytest

from leaderspeech.clean_structure_metadata import duplicates
from leaderspeech.text_scraper.run import SCHEMA_COLUMNS

LONG = ("Friends, today I am representing amid you the land which gave this mantra thousands of "
        "years ago. " * 12)


def _write(tmp_path, rows, source_id="src", country="Testland"):
    p = tmp_path / "scraped" / country / f"{source_id}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    for c in SCHEMA_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df[SCHEMA_COLUMNS].to_csv(p, index=False)
    return p


def _causes(tmp_path, rows):
    return [c["cause"] for c in duplicates.find_clusters(_write(tmp_path, rows))]


# --- cause classification -----------------------------------------------------------------------

def test_query_string_variant(tmp_path):
    # ind_pmindia_wayback: 1,169 rows, the single most common cause
    base = "https://www.pmindia.gov.in/en/news_updates/national-statement-by-pm-at-cop26/"
    rows = [dict(doc_id="IND1", source=base, text=LONG),
            dict(doc_id="IND2", source=base + "?tag_term=pmspeech&comment=disable", text=LONG),
            dict(doc_id="IND3", source=base + "?comment=disable", text=LONG)]
    assert _causes(tmp_path, rows) == ["url_variant"]


def test_scheme_and_port_and_www_variants(tmp_path):
    rows = [dict(doc_id="A1", source="http://president.gov.by:80/en/press1.html", text=LONG),
            dict(doc_id="A2", source="https://www.president.gov.by/en/press1.html", text=LONG)]
    assert _causes(tmp_path, rows) == ["url_variant"]


def test_mirror_host(tmp_path):
    # alb_president_wayback: 891 rows on the arkiva mirror
    rows = [dict(doc_id="ALB1", source="https://president.al/dekret-nr-10756-2-2/", text=LONG),
            dict(doc_id="ALB2", source="https://arkiva.president.al/dekret-nr-10756-2-2/", text=LONG)]
    assert _causes(tmp_path, rows) == ["mirror"]


def test_same_article_id_different_slug(tmp_path):
    rows = [dict(doc_id="AFG1", source="http://aop.gov.af/english/3687", text=LONG),
            dict(doc_id="AFG2", source="http://aop.gov.af/english/3687/Employment-of-Youth", text=LONG)]
    assert _causes(tmp_path, rows) == ["id_variant"]


def test_cms_duplicate_slug(tmp_path):
    rows = [dict(doc_id="X1", source="https://president.al/fjala-e-presidentit", text=LONG),
            dict(doc_id="X2", source="https://president.al/fjala-e-presidentit-2", text=LONG)]
    assert _causes(tmp_path, rows) == ["slug_variant"]


def test_junk_stub_is_its_own_cause(tmp_path):
    # afg_aop_english_wayback: 71 of its 94 duplicate rows. Real, DIFFERENT pages -- so without the
    # length/marker check these would be misread as "unrelated URLs sharing text".
    junk = "this page is under construction ..."
    rows = [dict(doc_id="A1", source="http://aop.gov.af/english/100/kuchi-affairs", text=junk),
            dict(doc_id="A2", source="http://aop.gov.af/english/101/high-offices", text=junk),
            dict(doc_id="A3", source="http://aop.gov.af/english/102/anti-corruption", text=junk)]
    assert _causes(tmp_path, rows) == ["junk_stub"]


def test_unrelated_urls_sharing_long_text_is_flagged_as_an_extraction_failure(tmp_path):
    """blr_president_english_wayback: 107 distinct article URLs all carrying the same press-release
    INDEX. Collapsing to one representative would attach the wrong speech to a real URL, so this
    must NOT be classified as a collapsible duplicate."""
    rows = [dict(doc_id="BLR1", source="http://president.gov.by/en/press142016.html", text=LONG),
            dict(doc_id="BLR2", source="http://president.gov.by/en/press142022.html", text=LONG),
            dict(doc_id="BLR3", source="http://president.gov.by/en/press142043.html", text=LONG)]
    assert _causes(tmp_path, rows) == ["shared_text_suspect"]


# --- what must NOT be treated as duplication -----------------------------------------------------

def test_shared_title_with_different_text_is_not_a_cluster(tmp_path):
    """93.4% of title-duplicates corpus-wide have different text: a generic site <title> bleeding
    in, or a recurring headline. Neither is duplication."""
    rows = [dict(doc_id="AZE1", title="Official web-site of President of Azerbaijan",
                 source="http://x/1", text=LONG + " one"),
            dict(doc_id="AZE2", title="Official web-site of President of Azerbaijan",
                 source="http://x/2", text=LONG + " two")]
    assert _causes(tmp_path, rows) == []


def test_unique_rows_produce_no_clusters(tmp_path):
    rows = [dict(doc_id="U1", source="http://x/1", text=LONG + " a"),
            dict(doc_id="U2", source="http://x/2", text=LONG + " b")]
    assert _causes(tmp_path, rows) == []


def test_text_in_originlanguage_column_is_used(tmp_path):
    """afg_aop_wayback has an EMPTY `text` column for all 2,379 rows -- hashing it alone would
    report the whole file as one duplicate cluster."""
    rows = [dict(doc_id="D1", source="http://x/1", text="", text_originlanguage=LONG),
            dict(doc_id="D2", source="http://x/2", text="", text_originlanguage=LONG + " differs")]
    assert _causes(tmp_path, rows) == []


def test_empty_text_rows_are_ignored(tmp_path):
    rows = [dict(doc_id="E1", source="http://x/1", text=""),
            dict(doc_id="E2", source="http://x/2", text="")]
    assert _causes(tmp_path, rows) == []


def test_normalization_catches_whitespace_and_case_differences(tmp_path):
    rows = [dict(doc_id="N1", source="https://president.al/x", text=LONG),
            dict(doc_id="N2", source="https://arkiva.president.al/x", text=LONG.upper() + "\n\n ")]
    assert _causes(tmp_path, rows) == ["mirror"]


# --- the report itself ---------------------------------------------------------------------------

def test_report_never_modifies_the_source_csv(tmp_path):
    rows = [dict(doc_id="R1", source="http://x/a", text=LONG),
            dict(doc_id="R2", source="http://x/a?utm=1", text=LONG)]
    csv_path = _write(tmp_path, rows)
    before = csv_path.read_bytes()

    out = tmp_path / "_build" / "dupes.csv"
    summary = duplicates.build_report(str(tmp_path / "scraped"), str(out), country=None)

    assert csv_path.read_bytes() == before          # the data is untouched
    assert summary["clusters"] == 1
    assert summary["extra_rows"] == 1
    report = pd.read_csv(out)
    assert report.iloc[0]["cause"] == "url_variant"
    assert report.iloc[0]["rows"] == 2
    assert "R1" in report.iloc[0]["doc_ids"] and "R2" in report.iloc[0]["doc_ids"]


def test_report_counts_extra_rows_by_cause(tmp_path):
    _write(tmp_path, [dict(doc_id="A1", source="http://x/a", text=LONG),
                      dict(doc_id="A2", source="http://x/a?q=1", text=LONG),
                      dict(doc_id="A3", source="http://x/a?q=2", text=LONG)], source_id="s1")
    _write(tmp_path, [dict(doc_id="B1", source="http://y/1", text="under construction ..."),
                      dict(doc_id="B2", source="http://y/2", text="under construction ...")],
           source_id="s2")
    summary = duplicates.build_report(str(tmp_path / "scraped"), str(tmp_path / "d.csv"))
    assert summary["by_cause"] == {"url_variant": 2, "junk_stub": 1}


def test_report_with_no_duplicates_writes_nothing(tmp_path):
    _write(tmp_path, [dict(doc_id="Z1", source="http://x/1", text=LONG + " a")])
    out = tmp_path / "_build" / "none.csv"
    summary = duplicates.build_report(str(tmp_path / "scraped"), str(out))
    assert summary["clusters"] == 0
    assert not out.exists()


@pytest.mark.parametrize("url", ["", "not a url", "http://", "://bad"])
def test_canonical_url_is_robust(url):
    duplicates._canonical_url(url)   # must not raise
