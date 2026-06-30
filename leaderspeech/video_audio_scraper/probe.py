"""Cheap diagnostic: harvest a source and show a sample of per-video metadata WITHOUT
downloading media or transcribing — the recipe-oriented sibling of `harvest`.

`--transcribe-sample` additionally downloads ONE short clip and transcribes it, as an
end-to-end sanity check before committing to a full run. (That one clip does spend
compute/disk — and money on the openai-api backend.)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from ._cli import add_source_args, recipe_from_args
from .config import load_config
from . import harvest as harvest_mod

log = logging.getLogger("leaderspeech.video_audio_scraper.probe")


def probe(recipe, config, *, n: int = 5, transcribe_sample: bool = False) -> dict:
    from .download import probe_metadata

    entries = harvest_mod.harvest_entries(recipe)
    report = {"source_id": recipe.source_id, "country": recipe.country,
              "summary": harvest_mod.summarize(entries), "samples": []}

    for e in entries[:n]:
        meta = None
        try:
            meta = probe_metadata(e["url"], recipe)
        except Exception as ex:  # a single bad video shouldn't sink the probe
            report["samples"].append({"url": e["url"], "error": f"{type(ex).__name__}: {ex}"})
            continue
        if meta is None:
            report["samples"].append({"url": e["url"], "note": "filtered out (date/duration)"})
            continue
        report["samples"].append({
            "url": meta.get("webpage_url") or e["url"], "title": meta.get("title", ""),
            "upload_date": meta.get("upload_date", ""), "duration": meta.get("duration", ""),
            "channel": meta.get("channel", ""), "language": meta.get("language", ""),
        })

    if transcribe_sample and entries:
        from .download import download_audio
        from .transcribe import get_transcriber

        sample_dir = Path("data/audio_video") / "_probe" / recipe.source_id
        url = entries[0]["url"]
        meta = download_audio(url, sample_dir, recipe,
                              audio_format=recipe.audio_format, audio_quality=recipe.audio_quality)
        if meta is None:
            report["sample_transcription"] = {"url": url, "note": "filtered out"}
        else:
            tr = get_transcriber(recipe.whisper.backend or config.backend, config,
                                 model=recipe.whisper.model or config.model,
                                 language=recipe.whisper.language or config.language)
            res = tr.transcribe(meta["audio_path"], language=recipe.whisper.language)
            tr.close()
            text = (res.get("text") or "").strip()
            report["sample_transcription"] = {
                "url": meta.get("webpage_url") or url, "title": meta.get("title", ""),
                "backend": tr.name, "model": tr.model, "detected_language": res.get("language", ""),
                "chars": len(text), "preview": text[:400],
            }
    return report


def main():
    ap = argparse.ArgumentParser(
        description="Probe an audio source: harvest + sample metadata (no transcription unless asked)")
    add_source_args(ap)
    ap.add_argument("--config", default=None)
    ap.add_argument("--n", type=int, default=5, help="how many videos to show metadata for")
    ap.add_argument("--transcribe-sample", action="store_true",
                    help="also download + transcribe ONE short clip (spends compute/$$)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    recipe, _ = recipe_from_args(args)
    config = load_config(args.config)
    report = probe(recipe, config, n=args.n, transcribe_sample=args.transcribe_sample)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
