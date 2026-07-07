"""The transcription run loop, exercised without network/GPU by faking the yt-dlp link
harvest, the audio download, and the Whisper transcriber."""

import csv
import json
from pathlib import Path

from leaderspeech.video_audio_scraper import build_recipe
from leaderspeech.video_audio_scraper import download as download_mod
from leaderspeech.video_audio_scraper import harvest as harvest_mod
from leaderspeech.video_audio_scraper import run
from leaderspeech.video_audio_scraper.config import AudioConfig


def _entries(*urls):
    return [{"url": u, "title": f"Speech {i}", "id": f"vid{i}",
             "duration": 120, "upload_date": "20200101"} for i, u in enumerate(urls, 1)]


class StubTranscriber:
    name = "stub"
    model = "stub-model"

    def __init__(self, *a, **k):
        pass

    def transcribe(self, audio_path, language=None):
        return {"text": "Ciao a tutti, questo e un discorso.", "language": "it"}

    def close(self):
        pass


def _fake_download_factory(skip_urls=()):
    def fake_download(url, out_dir, recipe=None, audio_format="mp3", audio_quality="192", quiet=True):
        if url in skip_urls:                 # simulate a date/duration filter rejection
            return None
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        vid = url.rsplit("/", 1)[-1]
        f = out_dir / f"20200101_{vid}.mp3"
        f.write_text("AUDIO BYTES", encoding="utf-8")
        return {"id": vid, "title": f"Title {vid}", "upload_date": "20200101",
                "description": "the description", "language": "it", "tags": "a, b",
                "duration": 120, "view_count": 9, "like_count": 3, "channel": "Palazzo Chigi",
                "uploader": "Palazzo Chigi", "uploader_id": "@chigi", "webpage_url": url,
                "audio_path": str(f)}
    return fake_download


def _patch(monkeypatch, entries, skip_urls=()):
    monkeypatch.setattr(harvest_mod, "harvest_entries", lambda recipe: list(entries))
    monkeypatch.setattr(download_mod, "download_audio", _fake_download_factory(skip_urls))
    monkeypatch.setattr(run, "get_transcriber", lambda *a, **k: StubTranscriber())


def _recipe():
    return build_recipe(country="Italy",
                        urls=["https://www.youtube.com/playlist?list=PLConte"],
                        speaker="Giuseppe Conte", language="Italian")


def _read_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_maps_schema_and_writes_sidecar(tmp_path, monkeypatch):
    entries = _entries("https://x/a", "https://x/b")
    _patch(monkeypatch, entries)
    out, state, audio = tmp_path / "scraped", tmp_path / "state", tmp_path / "audio"

    res = run.transcribe_source(_recipe(), AudioConfig(),
                                out_root=str(out), state_root=str(state), audio_root=str(audio))
    assert res["transcribed_this_run"] == 2
    assert res["failed_this_run"] == 0

    rows = _read_csv(out / "Italy" / f"{_recipe().source_id}.csv")
    assert [r["doc_id"] for r in rows] == ["ITA0001", "ITA0002"]
    # Italian source -> transcript lands in the origin-language column, English stays empty
    assert rows[0]["text_originlanguage"].startswith("Ciao")
    assert rows[0]["text"] == ""
    assert rows[0]["speaker"] == "Giuseppe Conte"
    assert rows[0]["dataset"] == "LeaderSpeech"
    assert rows[0]["date"] == "2020-01-01"

    media = _read_csv(out / "Italy" / f"{_recipe().source_id}_media.csv")
    assert media[0]["kind"] == "playlist"
    assert media[0]["backend"] == "stub"
    assert media[0]["audio_status"] == "kept"
    assert Path(media[0]["audio_path"]).exists()


def test_delete_audio_removes_file(tmp_path, monkeypatch):
    entries = _entries("https://x/a")
    _patch(monkeypatch, entries)
    out, state, audio = tmp_path / "scraped", tmp_path / "state", tmp_path / "audio"

    run.transcribe_source(_recipe(), AudioConfig(), out_root=str(out), state_root=str(state),
                          audio_root=str(audio), delete_audio=True)
    media = _read_csv(out / "Italy" / f"{_recipe().source_id}_media.csv")
    assert media[0]["audio_status"] == "deleted"
    assert media[0]["audio_path"] == ""
    assert not any(audio.rglob("*.mp3"))


def test_resumable_skips_seen(tmp_path, monkeypatch):
    entries = _entries("https://x/a", "https://x/b")
    _patch(monkeypatch, entries)
    out, state, audio = tmp_path / "scraped", tmp_path / "state", tmp_path / "audio"

    run.transcribe_source(_recipe(), AudioConfig(), out_root=str(out), state_root=str(state),
                          audio_root=str(audio))
    res2 = run.transcribe_source(_recipe(), AudioConfig(), out_root=str(out), state_root=str(state),
                                 audio_root=str(audio))
    assert res2["transcribed_this_run"] == 0


def test_doc_id_continues_shared_country_state(tmp_path, monkeypatch):
    # a prior (text) scrape already used ITA0001..ITA0005 for this country
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "Italy.json").write_text(
        json.dumps({"last_doc_num": 5, "seen_urls": [], "failed_urls": []}), encoding="utf-8")

    entries = _entries("https://x/a")
    _patch(monkeypatch, entries)
    out, audio = tmp_path / "scraped", tmp_path / "audio"
    run.transcribe_source(_recipe(), AudioConfig(), out_root=str(out), state_root=str(state_dir),
                          audio_root=str(audio))
    rows = _read_csv(out / "Italy" / f"{_recipe().source_id}.csv")
    assert rows[0]["doc_id"] == "ITA0006"   # continued, not restarted


def test_filtered_video_is_skipped_not_failed(tmp_path, monkeypatch):
    entries = _entries("https://x/keep", "https://x/drop")
    _patch(monkeypatch, entries, skip_urls={"https://x/drop"})
    out, state, audio = tmp_path / "scraped", tmp_path / "state", tmp_path / "audio"

    res = run.transcribe_source(_recipe(), AudioConfig(), out_root=str(out), state_root=str(state),
                                audio_root=str(audio))
    assert res["transcribed_this_run"] == 1
    assert res["skipped_filtered"] == 1
    assert res["failed_this_run"] == 0


def test_dry_run_makes_no_output(tmp_path, monkeypatch):
    entries = _entries("https://x/a")
    _patch(monkeypatch, entries)
    out, state, audio = tmp_path / "scraped", tmp_path / "state", tmp_path / "audio"

    res = run.transcribe_source(_recipe(), AudioConfig(), out_root=str(out), state_root=str(state),
                                audio_root=str(audio), dry_run=True)
    assert res["proceeded"] is False
    assert res["transcribed_this_run"] == 0
    assert not (out / "Italy" / f"{_recipe().source_id}.csv").exists()
