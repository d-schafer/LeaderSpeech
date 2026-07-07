"""Shared argparse plumbing for the harvest / run / probe CLIs.

The three entry points all need the same way of naming a source — either a saved
`--recipe` YAML or, more commonly, a playlist/channel `--url` (+ `--country` and a few
optional fixed fields). This builds an `AudioRecipe` from whichever was given.
"""

from __future__ import annotations

import argparse
from typing import Optional

from .recipe import AudioRecipe, HarvestSpec, build_recipe, load_recipe


def add_source_args(ap: argparse.ArgumentParser) -> None:
    src = ap.add_argument_group("source (use --recipe OR --url/--links + --country)")
    src.add_argument("--recipe", help="path to a saved audio recipe YAML")
    src.add_argument("--url", nargs="+", help="playlist / channel / video URL(s) to harvest")
    src.add_argument("--links", help="path to a pre-harvested URL list (one per line)")
    src.add_argument("--country", help="country name (required unless --recipe supplies it)")
    src.add_argument("--id", dest="source_id", help="source slug (default: auto from URL + country)")
    src.add_argument("--speaker", help="fixed speaker for a single-leader channel")
    src.add_argument("--position", help="fixed office/position (e.g. 'prime minister')")
    src.add_argument("--language", default="English", help="source language (default English)")
    src.add_argument("--dataset", default="LeaderSpeech", help="provenance tag (default LeaderSpeech)")
    src.add_argument("--user-agent", dest="user_agent")
    src.add_argument("--cookies-from-browser", dest="cookies_from_browser")

    tr = ap.add_argument_group("transcription overrides")
    tr.add_argument("--backend", help="faster-whisper | openai-whisper | openai-api (else config default)")
    tr.add_argument("--model", help="whisper model (e.g. large-v3, medium) — else config default")
    tr.add_argument("--whisper-language", dest="whisper_language",
                    help="language hint for transcription (e.g. it); else auto-detect")

    fl = ap.add_argument_group("harvest filters")
    fl.add_argument("--match-title", dest="match_title", help="regex a title must match")
    fl.add_argument("--max-videos", dest="max_videos", type=int)
    fl.add_argument("--min-duration", dest="min_duration", type=int, help="seconds; skip shorter")
    fl.add_argument("--max-duration", dest="max_duration", type=int, help="seconds; skip longer")
    fl.add_argument("--date-min", dest="date_min", help="YYYYMMDD; skip earlier uploads")
    fl.add_argument("--date-max", dest="date_max", help="YYYYMMDD; skip later uploads")


def recipe_from_args(args) -> tuple[AudioRecipe, bool]:
    """Return (recipe, from_url). `from_url` => invoked via --url (the run CLI prompts
    before transcribing in that case)."""
    if getattr(args, "recipe", None):
        return load_recipe(args.recipe), False

    if not getattr(args, "country", None):
        raise SystemExit("error: --country is required when not using --recipe")
    if not getattr(args, "url", None) and not getattr(args, "links", None):
        raise SystemExit("error: provide --url and/or --links (or a --recipe)")

    harvest = HarvestSpec(
        match_title=getattr(args, "match_title", None),
        max_videos=getattr(args, "max_videos", None),
        min_duration=getattr(args, "min_duration", None),
        max_duration=getattr(args, "max_duration", None),
        date_min=getattr(args, "date_min", None),
        date_max=getattr(args, "date_max", None),
    )
    recipe = build_recipe(
        country=args.country,
        urls=getattr(args, "url", None),
        links_file=getattr(args, "links", None),
        source_id=getattr(args, "source_id", None),
        speaker=getattr(args, "speaker", None),
        position=getattr(args, "position", None),
        language=getattr(args, "language", "English"),
        dataset=getattr(args, "dataset", "LeaderSpeech"),
        backend=getattr(args, "backend", None),
        model=getattr(args, "model", None),
        whisper_language=getattr(args, "whisper_language", None),
        harvest=harvest,
        user_agent=getattr(args, "user_agent", None),
        cookies_from_browser=getattr(args, "cookies_from_browser", None),
    )
    return recipe, bool(getattr(args, "url", None))
