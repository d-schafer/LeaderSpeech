import json

from leaderspeech.clean_structure_metadata import extract


def test_parse_meta_valid():
    payload = {k: None for k in extract.META_FIELDS}
    payload.update(document_type="speech", speaker="Pat Leader", speech_type="Policy Announcement")
    meta = extract.parse_meta(json.dumps(payload))
    assert meta["document_type"] == "speech"
    assert meta["speaker"] == "Pat Leader"
    assert set(meta.keys()) == set(extract.META_FIELDS)


def test_parse_meta_invalid_returns_all_none():
    meta = extract.parse_meta("not json at all")
    assert set(meta.keys()) == set(extract.META_FIELDS)
    assert all(v is None for v in meta.values())


def test_parse_meta_empty_string_to_none():
    meta = extract.parse_meta(json.dumps({"speaker": "  ", "venue": "Buenos Aires"}))
    assert meta["speaker"] is None
    assert meta["venue"] == "Buenos Aires"


def test_build_user_message_truncates_and_uses_originlanguage():
    row = {
        "speaker": "", "country": "Argentina", "date": "2020-01-01",
        "position": "", "title_originlanguage": "Discurso", "context": "",
        "source": "http://x", "text_originlanguage": " ".join(str(i) for i in range(1000)),
    }
    msg = extract.build_user_message(row, "Pat Leader (2019-2023)", max_words=50)
    assert "COUNTRY: Argentina" in msg
    assert "KNOWN LEADERS IN OFFICE (may be incomplete): Pat Leader (2019-2023)" in msg
    assert "Discurso" in msg            # pulled from title_originlanguage
    assert "[...]" in msg               # truncated
    # only ~50 words of body text were included
    body = msg.split("TEXT (first ~50 words):\n", 1)[1]
    assert body.split().index("[...]") <= 51


def test_build_user_message_blank_fields():
    msg = extract.build_user_message({"country": "Chile"}, "", max_words=100)
    assert "SPEAKER: not available" in msg
    assert "TEXT (first ~100 words):\nnot available" in msg


# --- the date evidence block: the fix for the capture-date-as-DATE bug --------------------------

UZB_ROW = {
    "country": "Uzbekistan", "title": "Genuine congratulations", "date": "",
    "source": "http://president.uz/en/lists/view/10",
    "wayback_capture": "2024-05-27", "date_regex_recovered": "2016-12-05",
    "text": "05.12.2016\nThe following congratulatory message has come from President Putin",
}


def _date_line(msg):
    return next((ln for ln in msg.splitlines() if ln.startswith("DATE:")), None)


def test_capture_date_never_appears_on_the_DATE_line():
    """THE regression test. The crawl timestamp used to be written straight into `DATE:`, which is
    what made the model echo it back 83-99% of the time instead of reading the text."""
    msg = extract.build_user_message(UZB_ROW, "")
    assert _date_line(msg) == "DATE: not available"
    assert "2024-05-27" not in _date_line(msg)


def test_capture_date_is_shown_but_labelled_as_a_bound():
    msg = extract.build_user_message(UZB_ROW, "")
    line = next(ln for ln in msg.splitlines() if ln.startswith("ARCHIVE CAPTURE DATE:"))
    assert "2024-05-27" in line
    assert "BOUND" in line and "NOT the answer" in line


def test_regex_candidate_is_labelled_unverified():
    msg = extract.build_user_message(UZB_ROW, "")
    line = next(ln for ln in msg.splitlines() if ln.startswith("CANDIDATE DATE FROM TEXT"))
    assert "2016-12-05" in line
    assert "UNVERIFIED" in line


def test_a_real_site_date_is_still_rendered_as_DATE():
    row = dict(UZB_ROW, date="2019-05-05")
    assert _date_line(extract.build_user_message(row, "")) == "DATE: 2019-05-05"


def test_no_evidence_lines_when_there_is_nothing_to_show():
    row = {"country": "Chile", "date": "2019-05-05", "text": "un discurso"}
    msg = extract.build_user_message(row, "")
    assert "ARCHIVE CAPTURE DATE" not in msg
    assert "CANDIDATE DATE FROM TEXT" not in msg


# --- PASS 1: the date-only prompt ---------------------------------------------------------------

def test_date_message_carries_no_leader_roster():
    """The roster is chosen FROM this call's answer, so including it here would reintroduce the
    circularity the pre-pass exists to break."""
    msg = extract.build_date_message(UZB_ROW)
    assert "KNOWN LEADERS IN OFFICE" not in msg
    assert "SPEAKER:" not in msg


def test_date_message_carries_the_evidence_and_the_text():
    msg = extract.build_date_message(UZB_ROW)
    assert "CANDIDATE DATE FROM TEXT" in msg
    assert "ARCHIVE CAPTURE DATE: 2024-05-27" in msg
    assert "05.12.2016" in msg
    assert "COUNTRY: Uzbekistan" in msg


def test_date_message_truncates_to_the_head():
    row = dict(UZB_ROW, text=" ".join(f"w{i}" for i in range(500)))
    msg = extract.build_date_message(row, max_words=10)
    assert "w9 [...]" in msg and "w11" not in msg


def test_date_system_prompt_forbids_returning_the_capture_date():
    p = extract.DATE_SYSTEM_PROMPT
    assert "NEVER return it as the date" in p
    assert "BOUND, NOT the answer" in p


def test_parse_date_meta_roundtrip():
    got = extract.parse_date_meta(
        '{"date": "2016-12-05", "date_confidence": "high", "date_basis": "dateline"}')
    assert got == {"date": "2016-12-05", "date_confidence": "high", "date_basis": "dateline"}


def test_parse_date_meta_degrades_on_junk():
    assert extract.parse_date_meta("not json") == extract.empty_date_meta()
    assert extract.parse_date_meta(None) == extract.empty_date_meta()
    assert extract.parse_date_meta('{"date": null}')["date"] is None


def test_system_prompt_explains_what_an_archive_capture_is():
    assert "ARCHIVE CAPTURE DATE" in extract.SYSTEM_PROMPT
    assert "do NOT fall back to the ARCHIVE CAPTURE DATE" in extract.SYSTEM_PROMPT
