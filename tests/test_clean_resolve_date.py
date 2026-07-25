"""The cleaner's date resolution. A date PARSED FROM TEXT (a Solar-Hijri date in the body) is
cross-checked against the Wayback capture date + the model and adjudicated/flagged on a material
disagreement, instead of being trusted blindly (see pipeline.resolve_date / DateResolution)."""

from leaderspeech.clean_structure_metadata import pipeline


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


def test_model_corrected_date_used_when_meta_says_mismatch():
    row = {"text": "english speech", "date": "2020-01-01"}
    meta = {"date": "2018-03-03", "date_matches_metadata": "no"}
    res = pipeline.resolve_date(row, meta)
    assert (res.date, res.precision) == ("2018-03-03", "model")
    assert res.disagreement is True
    assert res.model_date == "2018-03-03"


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
