import pandas as pd

from leaderspeech.clean_structure_metadata import tenure


def _tenure_df():
    rows = [
        {"speaker": "Néstor Kirchner", "country": "Argentina", "year": 2005, "is_ceremonial": False},
        {"speaker": "Cristina Fernandez de Kirchner", "country": "Argentina", "year": 2010, "is_ceremonial": False},
        {"speaker": "Sebastián Piñera", "country": "Chile", "year": 2019, "is_ceremonial": False},
        {"speaker": "Frank-Walter Steinmeier", "country": "Germany", "year": 2020, "is_ceremonial": True},
    ]
    df = pd.DataFrame(rows)
    df["_speaker_norm"] = df["speaker"].map(tenure.normalize)
    return df


def test_normalize_strips_accents_and_case():
    assert tenure.normalize("Néstor Kirchner") == "nestor kirchner"
    assert tenure.normalize("  PIÑERA  ") == "pinera"


def test_leaders_for_country_year_window():
    df = _tenure_df()
    leaders = tenure.leaders_for(df, "Argentina", 2005, window=1)
    assert "Néstor Kirchner" in leaders
    assert "Sebastián Piñera" not in leaders


def test_exact_match_accent_insensitive():
    df = _tenure_df()
    tm, ceremonial, matched = tenure.match_speaker(df, "Nestor Kirchner", "Argentina", 2005)
    assert tm == tenure.EXACT
    assert matched == "Néstor Kirchner"
    assert ceremonial is False


def test_surname_only_match():
    df = _tenure_df()
    tm, _, matched = tenure.match_speaker(df, "Piñera", "Chile", 2019)
    assert tm == tenure.EXACT
    assert matched == "Sebastián Piñera"


def test_other_country_detected():
    df = _tenure_df()
    # a Chilean leader's name attributed to an Argentina speech -> other_country
    tm, _, matched = tenure.match_speaker(df, "Sebastian Pinera", "Argentina", 2019)
    assert tm == tenure.OTHER_COUNTRY
    assert matched == "Sebastián Piñera"


def test_no_match():
    df = _tenure_df()
    tm, _, matched = tenure.match_speaker(df, "Nobody Atall", "Argentina", 2005)
    assert tm == tenure.NONE
    assert matched == ""


def test_step2_requires_strong_match():
    # issue #68 Part 4: an unknown domestic speaker sharing only ONE surname token with a foreign
    # leader must NOT be labeled other_country (the old loose token match did). "Cristina Lopez"
    # for Afghanistan shares just "cristina" with "Cristina Fernandez de Kirchner" (Argentina).
    df = _tenure_df()
    tm, _, matched = tenure.match_speaker(df, "Cristina Lopez", "Afghanistan", 2021)
    assert tm == tenure.NONE                                   # was OTHER_COUNTRY under the loose rule
    assert matched == ""
    # a genuine full-name foreign match still resolves (containment), preserving wrong-country signal
    tm2, _, matched2 = tenure.match_speaker(df, "Sebastian Pinera", "Afghanistan", 2021)
    assert tm2 == tenure.OTHER_COUNTRY and matched2 == "Sebastián Piñera"
