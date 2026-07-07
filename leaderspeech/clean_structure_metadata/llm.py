"""Shared OpenAI plumbing: key loading, the async client, and a generic chunked
batch runner. Lifts the AsyncOpenAI + semaphore + chunked-gather + per-chunk
checkpoint pattern out of the one-off `gpt_*.py` scripts into one reusable place.

`openai` is imported lazily (only when a client is actually created) so the rest
of the package — and the test suite, which mocks the LLM — imports without it.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Awaitable, Callable, Sequence


def load_api_key(config) -> str:
    """OPENAI_API_KEY env var wins; otherwise read `config.openai_key_file` from the
    cwd or this repo's likely roots (matches the existing scripts' file-based key)."""
    key = os.environ.get("OPENAI_API_KEY")
    if key and key.strip():
        return key.strip()
    name = config.openai_key_file
    seen = []
    for base in (Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parents[2]):
        cand = (base / name) if not Path(name).is_absolute() else Path(name)
        seen.append(str(cand))
        if cand.exists():
            return cand.read_text(encoding="utf-8").strip()
    raise RuntimeError(
        "No OpenAI key found. Set OPENAI_API_KEY, or place "
        f"'{name}' in one of: {seen}"
    )


def create_async_client(api_key: str):
    from openai import AsyncOpenAI  # lazy: keep the package importable without openai
    return AsyncOpenAI(api_key=api_key)


async def run_async_batches(
    items: Sequence,
    worker: Callable[[object, asyncio.Semaphore], Awaitable],
    *,
    batch_size: int,
    chunk_size: int,
    on_chunk: Callable[[list, list], None],
) -> None:
    """Run `worker(item, semaphore)` over `items` with up to `batch_size` concurrent
    requests, in chunks of `chunk_size`. After each chunk, call
    `on_chunk(chunk_items, chunk_results)` so the caller can post-process + checkpoint.
    `chunk_results` are aligned to `chunk_items`; failures arrive as Exception objects
    (gather is run with return_exceptions=True), never raised here."""
    sem = asyncio.Semaphore(batch_size)
    for start in range(0, len(items), chunk_size):
        chunk = list(items[start:start + chunk_size])
        results = await asyncio.gather(
            *(worker(it, sem) for it in chunk), return_exceptions=True
        )
        on_chunk(chunk, list(results))
