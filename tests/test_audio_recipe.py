"""AudioRecipe: building from CLI params, slug/iso derivation, save/load round-trip,
and source-kind detection."""

import pytest

from leaderspeech.video_audio_scraper import build_recipe, derive_source_id, load_recipe, save_recipe
from leaderspeech.video_audio_scraper.harvest import detect_kind
from leaderspeech.video_audio_scraper.recipe import AudioRecipe, HarvestSpec


def test_build_recipe_derives_id_and_iso3n():
    r = build_recipe(country="Italy",
                     urls=["https://www.youtube.com/playlist?list=PLABC123"],
                     speaker="Giuseppe Conte", language="Italian")
    assert r.source_id.startswith("ita_")
    assert r.iso3n == 380                 # Italy numeric ISO, auto-filled
    assert r.speaker_default == "Giuseppe Conte"
    assert r.source_language == "Italian"
    assert r.dataset == "LeaderSpeech"     # stays LeaderSpeech for audio too


def test_explicit_id_is_slugified():
    assert derive_source_id(None, "Italy", explicit="ITA Conte Interviews!") == "ita-conte-interviews"


def test_recipe_needs_a_source():
    with pytest.raises(Exception):
        AudioRecipe(source_id="x", country="Italy")  # no start_urls and no links_file


def test_save_load_round_trip(tmp_path):
    r = build_recipe(country="Poland",
                     urls=["https://www.youtube.com/playlist?list=PLxyz"],
                     speaker="Mateusz Morawiecki", language="Polish",
                     whisper_language="pl", model="large-v3",
                     harvest=HarvestSpec(max_videos=10, min_duration=60))
    path = save_recipe(r, tmp_path / "pol_test.yml")
    assert path.exists()
    loaded = load_recipe(path)
    assert loaded.source_id == r.source_id
    assert loaded.country == "Poland"
    assert loaded.whisper.language == "pl"
    assert loaded.whisper.model == "large-v3"
    assert loaded.harvest.max_videos == 10
    assert loaded.harvest.min_duration == 60


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/playlist?list=PLABC", "playlist"),
    ("https://www.youtube.com/@SomeChancellery/videos", "channel"),
    ("https://www.youtube.com/channel/UC123", "channel"),
    ("https://example.gov/speech.mp4", "url_list"),
])
def test_detect_kind(url, expected):
    r = build_recipe(country="Germany", urls=[url])
    assert detect_kind(r) == expected


def test_detect_kind_explicit_overrides():
    r = build_recipe(country="Germany", urls=["https://x/whatever"],
                     harvest=HarvestSpec(kind="channel"))
    assert detect_kind(r) == "channel"
