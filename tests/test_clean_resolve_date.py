"""The cleaner's date resolution: Jalali(text) > model/scraped > wayback_capture."""

from leaderspeech.clean_structure_metadata import pipeline


def test_jalali_text_beats_scraped_and_wayback():
    row = {"text_originlanguage": "۱۹ حمل ۱۴۰۴ سخنرانی رئیس", "date": "2020-01-01",
           "wayback_capture": "2024-06-01"}
    assert pipeline.resolve_date(row) == ("2025-04-08", "day")


def test_jalali_year_only_when_no_full_date():
    row = {"text_originlanguage": "در جریان سال ۱۴۰۳ اقدامات", "date": "2020-01-01",
           "wayback_capture": "2024-06-01"}
    assert pipeline.resolve_date(row) == ("2024", "year")


def test_wayback_capture_is_last_resort_when_no_text_date_and_no_scraped():
    row = {"text_originlanguage": "متن بدون هیچ تاریخ", "date": "", "wayback_capture": "2024-06-01"}
    assert pipeline.resolve_date(row) == ("2024-06-01", "wayback_capture")


def test_scraped_date_beats_wayback_capture():
    row = {"text": "a normal english speech, no jalali", "date": "2019-05-05",
           "wayback_capture": "2024-06-01"}
    assert pipeline.resolve_date(row) == ("2019-05-05", "scraped")


def test_model_corrected_date_used_when_meta_says_mismatch():
    row = {"text": "english speech", "date": "2020-01-01"}
    meta = {"date": "2018-03-03", "date_matches_metadata": "no"}
    assert pipeline.resolve_date(row, meta) == ("2018-03-03", "model")


def test_nothing_available():
    assert pipeline.resolve_date({"text": "no date at all", "date": "", "wayback_capture": ""}) == ("", None)
