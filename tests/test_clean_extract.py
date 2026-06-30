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
    assert "CONFIRMED LEADERS IN OFFICE (authoritative): Pat Leader (2019-2023)" in msg
    assert "Discurso" in msg            # pulled from title_originlanguage
    assert "[...]" in msg               # truncated
    # only ~50 words of body text were included
    body = msg.split("TEXT (first ~50 words):\n", 1)[1]
    assert body.split().index("[...]") <= 51


def test_build_user_message_blank_fields():
    msg = extract.build_user_message({"country": "Chile"}, "", max_words=100)
    assert "SPEAKER: not available" in msg
    assert "TEXT (first ~100 words):\nnot available" in msg
