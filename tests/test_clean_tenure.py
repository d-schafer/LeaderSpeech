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
