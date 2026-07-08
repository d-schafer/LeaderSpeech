"""The shared index must mark audio sources from their `<id>_media.csv` sidecar
(no recipe needed): renderer=audio:<backend>, pagination_type=<kind>."""

import csv

import pandas as pd

from leaderspeech.text_scraper import index
from leaderspeech.text_scraper.run import SCHEMA_COLUMNS
from leaderspeech.video_audio_scraper.run import MEDIA_COLUMNS


def _write(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def test_audio_source_marked_from_sidecar(tmp_path):
    out_root = tmp_path / "scraped"
    _write(out_root / "Italy" / "ita_conte.csv", SCHEMA_COLUMNS, [
        {"doc_id": "ITA0001", "country": "Italy", "date": "2020-01-01",
         "text_originlanguage": "ciao", "dataset": "LeaderSpeech",
         "source": "https://www.youtube.com/watch?v=vid1"},
        {"doc_id": "ITA0002", "country": "Italy", "date": "2020-02-02",
         "text_originlanguage": "ciao2", "dataset": "LeaderSpeech",
         "source": "https://www.youtube.com/watch?v=vid2"},
    ])
    _write(out_root / "Italy" / "ita_conte_media.csv", MEDIA_COLUMNS, [
        {"doc_id": "ITA0001", "kind": "playlist", "backend": "faster-whisper", "model": "large-v3"},
        {"doc_id": "ITA0002", "kind": "playlist", "backend": "faster-whisper", "model": "large-v3"},
    ])

    path = index.build_index(str(out_root), str(tmp_path / "recipes"))
    df = pd.read_excel(path)
    assert len(df) == 1                          # the _media.csv sidecar is not its own source
    row = df.iloc[0]
    assert row["source_id"] == "ita_conte"
    assert row["renderer"] == "audio:faster-whisper"
    assert row["pagination_type"] == "playlist"
    assert row["dataset"] == "LeaderSpeech"      # provenance stays LeaderSpeech
    assert row["n_speeches"] == 2
    assert row["doc_id_first"] == "ITA0001"
