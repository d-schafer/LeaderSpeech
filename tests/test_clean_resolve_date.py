"""The cleaner's date resolution. A date PARSED FROM TEXT (a Solar-Hijri date in the body) is
cross-checked against the Wayback capture date + the model and adjudicated/flagged on a material
disagreement, instead of being trusted blindly (see pipeline.resolve_date / DateResolution)."""

from leaderspeech.clean_structure_metadata import pipeline
from leaderspeech.clean_structure_metadata.config import CleanConfig


def test_jalali_text_beats_scraped_and_wayback_when_consistent():
    # full Jalali date, capture shortly AFTER it -> consistent, trusted, no disagreement
    row = {"text_originlanguage": "۱۹ حمل ۱۴۰۴ سخنرانی رئیس", "date": "2020-01-01",
           "wayback_capture": "2025-06-01"}
    res = pipeline.resolve_date(row)
    assert (res.date, res.precision) == ("2025-04-08", "day")
    assert res.disagreement is False


def test_jalali_year_only_when_no_full_date():
    row = {"text_originlanguage": "در جریان سال ۱۴۰۳ اقدامات", "date": "2020-01-01",
           "wayback_capture": "2024-06-01"}
    res = pipeline.resolve_date(row)
    assert (res.date, res.precision) == ("2024", "year")
    assert res.disagreement is False


def test_wayback_capture_is_last_resort_when_no_text_date_and_no_scraped():
    row = {"text_originlanguage": "متن بدون هیچ تاریخ", "date": "", "wayback_capture": "2024-06-01"}
    res = pipeline.resolve_date(row)
    assert (res.date, res.precision) == ("2024-06-01", "wayback_capture")


def test_scraped_date_beats_wayback_capture():
    row = {"text": "a normal english speech, no jalali", "date": "2019-05-05",
           "wayback_capture": "2024-06-01"}
    res = pipeline.resolve_date(row)
    assert (res.date, res.precision) == ("2019-05-05", "scraped")
    assert res.disagreement is False


def test_selector_date_survives_a_model_contradiction_but_is_flagged():
    """TIER 1. The recipe's date selector is the site's OWN field, so it stays even when the model
    disagrees -- the row is flagged for a human instead. A systematic mismatch means the RECIPE is
    broken (this is how geo_president_wayback's DD.MM-vs-MM.DD misparse surfaces), and silently
    overwriting it would hide the bug rather than fix it. The model's answer is kept for audit."""
    row = {"text": "english speech", "date": "2020-01-01"}
    meta = {"date": "2018-03-03", "date_matches_metadata": "no"}
    res = pipeline.resolve_date(row, meta)
    assert (res.date, res.precision) == ("2020-01-01", "scraped")
    assert res.disagreement is True
    assert res.model_date == "2018-03-03"


def test_selector_agreeing_with_the_model_is_not_flagged():
    row = {"text": "english speech", "date": "2020-01-01"}
    meta = {"date": "2020-01-01", "date_matches_metadata": "yes"}
    res = pipeline.resolve_date(row, meta)
    assert (res.date, res.precision) == ("2020-01-01", "scraped")
    assert res.disagreement is False


def test_nothing_available():
    res = pipeline.resolve_date({"text": "no date at all", "date": "", "wayback_capture": ""})
    assert (res.date, res.precision) == ("", None)
    assert res.disagreement is False


# --- the AFG2396-style silent-bad-date cases the redesign targets ---

def test_jalali_day_far_from_capture_is_flagged_and_bounded_to_capture():
    # a stray Solar-Hijri date (1351/12/22 -> 1973) on a page captured 2021: implausible. With no
    # model date to adjudicate, fall back to the capture BOUND -- but FLAGGED, never silently trusted.
    row = {"text_originlanguage": "۱۳۵۱/۱۲/۲۲ سند", "date": "", "wayback_capture": "2021-08-16"}
    res = pipeline.resolve_date(row)
    assert res.disagreement is True
    assert res.parsed == "1973-03-13"                       # the raw misparse is recorded for audit
    assert (res.date, res.precision) == ("2021-08-16", "wayback_capture")


def test_model_adjudicates_a_far_jalali_date_when_it_offers_a_plausible_one():
    row = {"text_originlanguage": "۱۳۵۱/۱۲/۲۲ سند", "date": "", "wayback_capture": "2023-12-04"}
    meta = {"date": "2023-01-15", "date_matches_metadata": "no"}
    res = pipeline.resolve_date(row, meta)
    assert res.disagreement is True
    assert (res.date, res.precision) == ("2023-01-15", "model")   # GPT wins over the bad parse
    assert res.parsed == "1973-03-13"


def test_jalali_day_close_to_capture_is_trusted():
    # a 2016 Ghani-era speech captured 2021 (gap == 5, not > default 5) -> trusted, no flag
    row = {"text_originlanguage": "۱۹ حمل ۱۳۹۵ سخنرانی", "date": "", "wayback_capture": "2021-08-16"}
    res = pipeline.resolve_date(row)
    assert res.disagreement is False
    assert res.precision == "day" and res.date.startswith("2016")


def test_stricter_flag_years_flags_a_borderline_gap():
    # same 2016-vs-2021 gap of 5, but a stricter flag_years=3 now trips the disagreement
    row = {"text_originlanguage": "۱۹ حمل ۱۳۹۵ سخنرانی", "date": "", "wayback_capture": "2021-08-16"}
    res = pipeline.resolve_date(row, flag_years=3)
    assert res.disagreement is True


def test_parsed_date_after_capture_is_impossible_and_flagged():
    # 1404 -> 2025, but the page was captured 2022 -> a speech cannot post-date its own archival
    row = {"text_originlanguage": "۱۹ حمل ۱۴۰۴ سخنرانی", "date": "", "wayback_capture": "2022-01-01"}
    res = pipeline.resolve_date(row)
    assert res.disagreement is True
    assert (res.date, res.precision) == ("2022-01-01", "wayback_capture")


# --- the generic-extractor / head-line-date cases (UZB0001 and friends) ------------------------

# the real row: delivered 05.12.2016, crawled 2024-05-27. Before this work it resolved to the
# CAPTURE date -- an 8-year error, unflagged.
UZB_TEXT = ("05.12.2016\nThe following congratulatory message has come from President of the "
            "Russian Federation Vladimir Putin, addressed to President-elect of the Republic of "
            "Uzbekistan Shavkat Mirziyoyev:")


def test_model_beats_the_capture_date_when_there_is_no_selector_date():
    """The whole point: GPT reads the text, and its answer outranks the crawl timestamp."""
    row = {"text": UZB_TEXT, "date": "", "wayback_capture": "2024-05-27"}
    meta = {"date": "2016-12-05", "date_matches_metadata": "unsure"}
    res = pipeline.resolve_date(row, meta)
    assert (res.date, res.precision) == ("2016-12-05", "model")
    assert res.is_fallback is False
    assert res.regex == "2016-12-05"          # the regex candidate is recorded even though it lost


def test_regex_wins_only_when_the_model_offers_nothing():
    row = {"text": UZB_TEXT, "date": "", "wayback_capture": "2024-05-27"}
    res = pipeline.resolve_date(row)          # meta=None -> pre-LLM
    assert (res.date, res.precision) == ("2016-12-05", "regex_text")
    assert res.is_fallback is False


def test_selector_date_still_beats_the_regex_candidate():
    """Additivity guard: a working recipe date selector is untouched by any of this. The regex is
    still recorded, which is what makes 'the site's date disagrees with the body' a one-query audit."""
    row = {"text": UZB_TEXT, "date": "2019-05-05", "wayback_capture": "2024-05-27"}
    res = pipeline.resolve_date(row)
    assert (res.date, res.precision) == ("2019-05-05", "scraped")
    assert res.regex == "2016-12-05"


def test_date_text_first_lets_the_regex_outrank_a_known_bad_selector():
    # the irn_khamenei_english_wayback / geo_president_wayback escape hatch
    cfg = CleanConfig(date_text_first=True)
    row = {"text": UZB_TEXT, "date": "2019-05-05", "wayback_capture": "2024-05-27"}
    res = pipeline.resolve_date(row, config=cfg)
    assert (res.date, res.precision) == ("2016-12-05", "regex_text")


def test_model_date_after_the_capture_is_rejected_and_flagged():
    row = {"text": UZB_TEXT, "date": "", "wayback_capture": "2018-01-01"}
    meta = {"date": "2020-06-06", "date_matches_metadata": "no"}
    res = pipeline.resolve_date(row, meta)
    assert res.date != "2020-06-06"
    assert res.disagreement is True


def test_capture_fallback_is_marked_when_nothing_better_exists():
    """An echo (the model returns exactly the capture date) is recorded HONESTLY rather than
    relabelled 'model': the row's date really is only the crawl bound, and is_fallback says so."""
    row = {"text": "no date anywhere in this body", "date": "", "wayback_capture": "2024-05-27"}
    meta = {"date": "2024-05-27", "date_matches_metadata": "unsure"}
    res = pipeline.resolve_date(row, meta)
    assert (res.date, res.precision) == ("2024-05-27", "wayback_capture")
    assert res.is_fallback is True


def test_is_fallback_is_false_whenever_a_real_date_was_found():
    row = {"text": UZB_TEXT, "date": "2019-05-05"}
    assert pipeline.resolve_date(row).is_fallback is False


def test_prose_date_is_not_mistaken_for_the_document_date():
    """The failure mode a naive regex has (measured: 45-64% wrong-year). The parser refuses, so
    the row honestly falls back to the capture bound rather than asserting 1990."""
    row = {"text": ("20 January 1990 went down in the history of modern Azerbaijan as one of the "
                    "most tragic and at the same time heroic pages."),
           "date": "", "wayback_capture": "2013-11-08"}
    res = pipeline.resolve_date(row)
    assert res.regex is None
    assert (res.date, res.precision) == ("2013-11-08", "wayback_capture")


def test_jalali_still_outranks_the_regex_candidate():
    row = {"text_originlanguage": "۱۹ حمل ۱۳۹۵ سخنرانی\n05.12.2016", "date": "",
           "wayback_capture": "2021-08-16"}
    res = pipeline.resolve_date(row)
    assert res.precision == "day" and res.date.startswith("2016-04")


def test_disabling_the_text_parser_restores_the_old_behaviour():
    cfg = CleanConfig(date_text_enabled=False)
    row = {"text": UZB_TEXT, "date": "", "wayback_capture": "2024-05-27"}
    res = pipeline.resolve_date(row, config=cfg)
    assert (res.date, res.precision) == ("2024-05-27", "wayback_capture")
    assert res.regex is None
