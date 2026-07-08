# `recipes_audio/` — optional, auto-generated audio recipes

**You usually don't need a file here.** Unlike the text scraper's `recipes/` (where a per-site YAML is
*required* because every website is structured differently), the video/audio scraper leans on `yt-dlp`,
which already knows how to extract media + metadata from a playlist/channel/video URL on YouTube and ~1000
other sites. So there is essentially nothing to author per source.

## The normal way: just pass a link

```bash
# harvest the links (summary only, no download)
python -m leaderspeech.video_audio_scraper.harvest --url "<playlist-url>" --country Italy

# download audio + transcribe (prompts before spending compute/disk)
python -m leaderspeech.video_audio_scraper.run --url "<playlist-url>" --country Italy \
    --speaker "Giuseppe Conte" --language Italian --limit 5
```

The only things you must supply that yt-dlp can't know are `--country` (sets the `doc_id` prefix + output
folder) and, for a single-leader channel, the optional `--speaker` / `--position` / `--language`.

## When a saved recipe helps

Add `--save-recipe` and the run writes `recipes_audio/<id>.yml` capturing exactly those parameters + the
URL(s). It's purely a convenience for:

- **Re-running / updating** a source to pick up new uploads: `run --recipe recipes_audio/<id>.yml --update`.
- **Batch processing** several sources without retyping flags.
- **Reproducibility** (others can re-run your collection).

A saved recipe is small — here's the full shape:

```yaml
source_id: ita_conte            # auto-derived; override with --id
country: Italy
source_language: Italian        # non-English routes text to *_originlanguage
dataset: LeaderSpeech
source_type: audio
start_urls:
  - https://www.youtube.com/playlist?list=PLA9xPbzYNhmioYEMNskKayu3J0H4nwbOz
speaker_default: Giuseppe Conte  # single-leader channel; omit for mixed channels
# position: prime minister
whisper:
  language: it                  # hint; omit to auto-detect
  # model: large-v3             # overrides configs/audio_config.yml
  # backend: faster-whisper
harvest:
  # kind: playlist              # auto-detected from the URL if omitted
  # max_videos: 200
  # match_title: "Conte"        # regex a title must match
  # date_min: "20180101"        # YYYYMMDD; date/duration filters run at download time
  # min_duration: 60            # seconds; skip shorter clips
# user_agent: ...               # for a UA-gated source
# cookies_from_browser: chrome  # for a login-gated channel
```

Naming convention: `<iso3>_<slug>.yml` (e.g. `ita_conte.yml`, `pol_morawiecki.yml`).

Full reference: [`../docs/audio_transcription.md`](../docs/audio_transcription.md).
