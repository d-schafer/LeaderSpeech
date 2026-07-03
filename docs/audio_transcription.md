# Video & audio transcription (`video_audio_scraper`)

The third LeaderSpeech tool turns leaders' **video/audio** into rows in the same standardized schema as the
text scraper. It downloads the **audio only** (the video is never kept) with [`yt-dlp`](https://github.com/yt-dlp/yt-dlp),
transcribes it with **Whisper**, assigns a per-country `doc_id`, and writes to `data/scraped/<Country>/` —
so `clean_structure_metadata`, `translate`, and `merge` treat an audio-sourced speech exactly like a
web-scraped one.

## Why there's (almost) no recipe

The text scraper needs a per-site recipe because every website's HTML is structured differently. **yt-dlp
already solves that for media**: hand it a playlist, channel, or single-video URL — on YouTube or any of the
~1000 sites it supports — and it extracts the audio + metadata regardless of site. So the only things the
tool needs that yt-dlp can't supply are the **country** (for the `doc_id` prefix and folder) and, for a
single-leader channel, the **speaker / position / language**. You pass those as flags. A YAML recipe is
**optional and auto-generated** (`--save-recipe`), used only to make re-runs/updates and batch processing a
one-liner — see [`recipes_audio/README.md`](../recipes_audio/README.md).

## Install + environment

```bash
pip install -e ".[audio]"     # yt-dlp + faster-whisper (default backend)
```

`ffmpeg` must be on `PATH` (yt-dlp uses it to extract audio). The default backend, **faster-whisper**, needs
no `torch` and runs on **CPU out of the box** (`compute_type: int8`) with nothing extra to install — just
slower.

**GPU is optional but much faster.** It needs the CUDA 12 cuBLAS/cuDNN runtime libraries, which are *not*
bundled in the `faster-whisper` wheel nor pulled in by `.[audio]`; add them once (a fresh env won't have
them):

```bash
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12    # ~1.5 GB; recent CTranslate2 finds the DLLs, no PATH tweak
```

Once present, `device: auto` (the config default) uses the GPU automatically; without them it stays on CPU.
**This project's `D:\environments\whisperscribe` env already has these installed** (GPU validated) — the
`pip install` above is only for a fresh setup elsewhere. Because Whisper + CUDA are heavy and YouTube breaks
old yt-dlp versions, run this tool from that **dedicated venv**, separate from the scraper env.

## The workflow: harvest → confirm → transcribe

```bash
# 1) Harvest — see what a source yields. Saves <id>_links.txt; NO download/transcription.
python -m leaderspeech.video_audio_scraper.harvest --url "<playlist-or-channel>" --country Italy
#    -> "Found 137 video(s) | dates 2018-06 .. 2024-05 | e.g. 'Conferenza stampa ...'"

# 2) Run — download audio + transcribe. With --url it prints the summary and PROMPTS before
#    spending compute/disk (skip with --yes; a non-TTY shell needs --yes).
python -m leaderspeech.video_audio_scraper.run --url "<playlist-or-channel>" --country Italy \
    --speaker "Giuseppe Conte" --language Italian --limit 5 --delete-audio --save-recipe

# 3) Later, pick up only new uploads from a saved recipe:
python -m leaderspeech.video_audio_scraper.run --recipe recipes_audio/<id>.yml --update
```

**probe** is the recipe-oriented diagnostic: it shows per-video metadata for a sample (no transcription),
and `--transcribe-sample` runs ONE short clip end-to-end as a sanity check.

```bash
python -m leaderspeech.video_audio_scraper.probe --url "<playlist>" --country Italy --n 5
python -m leaderspeech.video_audio_scraper.probe --recipe recipes_audio/<id>.yml --transcribe-sample
```

### Source flags

| flag | meaning |
|------|---------|
| `--url URL [URL...]` | playlist / channel / video URL(s) to harvest |
| `--links FILE` | use a pre-harvested URL list instead of (re)harvesting |
| `--recipe FILE` | drive everything from a saved recipe (no prompt) |
| `--country` | **required** (unless `--recipe` supplies it) — sets the `doc_id` prefix + folder |
| `--id` | source slug (default: auto from URL + country) |
| `--speaker` / `--position` | fixed values for a single-leader channel (else left blank for the cleaner) |
| `--language` | source language; non-English goes to the `*_originlanguage` columns (default English) |
| `--dataset` | provenance tag (default `LeaderSpeech`) |
| `--match-title` / `--max-videos` | harvest-time filters (title regex; cap) |
| `--date-min` / `--date-max` / `--min-duration` / `--max-duration` | download-time filters (yt-dlp skips rejects before downloading media) |
| `--backend` / `--model` / `--whisper-language` | transcription overrides (else `configs/audio_config.yml`) |
| `--user-agent` / `--cookies-from-browser` | for UA-gated or login-gated sources |

### Run flags

`--limit N` (cap this run), `--retry-failed`, `--update` (re-harvest, process only new), `--yes` (skip the
prompt), `--dry-run` (harvest + summarize only), `--save-recipe`, `--delete-audio` / `--keep-audio`,
`--out-root` / `--state-root` / `--audio-root` / `--config`.

## Transcription backends

Pluggable (mirrors the translator). Pick the default in `configs/audio_config.yml` (`backend:`) or per
run with `--backend` / per recipe with `whisper.backend`.

| backend | install | notes |
|---------|---------|-------|
| **faster-whisper** (default) | `.[audio]` | CTranslate2 Whisper — same models incl. `large-v3`, ~4× faster, lower VRAM, **no torch**. GPU or CPU (`compute_type: int8`). |
| **openai-whisper** | `.[audio-openai-whisper]` | The reference implementation the prototypes used; needs a (CUDA) `torch`. |
| **openai-api** | `.[llm]` | Paid hosted transcription (`whisper-1`). No GPU. Key via `OPENAI_API_KEY` or `openai_key.txt`. A **cost gate** like the cleaner. |

## Output

```
data/scraped/<Country>/<id>.csv          # canonical: the standardized schema (drops into the pipeline)
data/scraped/<Country>/<id>_media.csv    # sidecar: rich provenance, keyed by doc_id
data/scraped/<Country>/<id>_links.txt    # harvested URL list
data/scraped/<Country>/<id>_errors.csv   # per-URL failures (timestamp, url, error)
data/scraped/<Country>/<id>_<ts>.log     # per-run log
data/audio_video/<Country>/<id>/*.mp3    # downloaded audio (gitignored; kept unless --delete-audio)
data/state/<Country>.json                # SHARED with the text scraper (continuous doc_id)
```

**Schema mapping:** video URL → `source`, title → `title`(`_originlanguage`), transcript →
`text`(`_originlanguage`), description → `context`(`_originlanguage`), upload date → `date`, `dataset` →
`LeaderSpeech`. As elsewhere, a non-English `source_language` routes the text into the `*_originlanguage`
columns for the translator to fill.

**Media sidecar columns:** `doc_id, media_url, video_id, upload_date, duration, channel, uploader,
uploader_id, view_count, like_count, tags, language, detected_language, audio_path, audio_status,
kind, backend, model, transcribed_at`.

### The progress index

Every run rebuilds the shared `data/scraped/scraped_progress_log.xlsx` (one row per source). Audio sources
are marked **without a recipe**, from the `<id>_media.csv` sidecar: the `renderer` column shows
`audio:<backend>` (e.g. `audio:faster-whisper`) and `pagination_type` shows the source `kind`
(`playlist` / `channel` / `url_list`). `dataset` stays `LeaderSpeech`.

## Resumability, retention, safety

- **Resumable.** The shared per-country state records seen/failed URLs and the last `doc_id` number, so
  re-running continues where it left off and `doc_id`s stay unique and contiguous across text **and** audio
  sources in a country. Filtered videos are marked seen (not reprocessed); failures are retried with
  `--retry-failed`. Single-writer: don't run the text and audio scrapers for the *same* country at once.
- **Audio retention.** Kept by default (copy to an external drive if you like); `--delete-audio` removes
  each mp3 after a **successful** transcription (the sidecar records `audio_status` = `kept`/`deleted`).
- **Circuit breaker.** A long unbroken run of failures (bad ffmpeg/yt-dlp/model setup, or a block) aborts
  the run with a clear message rather than grinding on.
- **FULL-RUN / cost gate.** A full channel `run` spends real compute + disk (and money on the openai-api
  backend). `harvest`, `probe`, `--dry-run`, and `run --limit N` are the cheap spot-checks; a complete run
  is the researcher's gated step.
