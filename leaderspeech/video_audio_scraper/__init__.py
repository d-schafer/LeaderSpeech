"""video_audio_scraper — grab audio from video/audio sources and transcribe it.

The third LeaderSpeech tool. Unlike the text scraper it is *not* recipe-first:
`yt-dlp` already abstracts away each site's structure, so the primary interface is
a playlist/channel link on the command line (harvest -> confirm -> transcribe).
The result lands in the same standardized schema, per-country `doc_id`, state, and
`scraped_progress_log.xlsx` index as the text scraper, so the cleaning/translation/
merge pipeline treats audio-sourced speeches identically to web-scraped ones.

Public API:
    from leaderspeech.video_audio_scraper import AudioRecipe, load_recipe, build_recipe
"""

from __future__ import annotations

from .recipe import AudioRecipe, build_recipe, derive_source_id, load_recipe, save_recipe

__all__ = ["AudioRecipe", "load_recipe", "save_recipe", "build_recipe", "derive_source_id"]
