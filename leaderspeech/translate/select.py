"""Interactive backend picker for the translator.

Recommends a backend from the machine's GPU (VRAM) and what's installed in the current Python
env, but always lets the user choose — deliberately a PROMPT, not silent auto-detection, so the
choice travels to any machine/user of the repo without guessing wrong. Only used when the CLI is
interactive and no `--translator` was passed; scripts/cron fall through to the config default.

Note the two-env split in this project: the online Google backend lives in `leaderspeech_scrape`
(deep-translator, no torch); the local NLLB/OpusMT backends live in `transformers_new2025`
(torch + transformers). So a backend is only usable if its dependency is importable here — the
picker flags that.
"""

from __future__ import annotations

import importlib.util
import subprocess


def detect_gpu() -> tuple[float, str | None]:
    """(VRAM GB, device name) for GPU 0, or (0.0, None) if no CUDA GPU is found."""
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return props.total_memory / 1e9, props.name
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6)
        if r.returncode == 0 and r.stdout.strip():
            mem, name = r.stdout.strip().splitlines()[0].split(",", 1)
            return float(mem) / 1024, name.strip()
    except Exception:
        pass
    return 0.0, None


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


# key, translator name, model override, label, dep module, one-line note
OPTIONS = [
    ("google", "google", None, "Google — deep-translator (online, free)", "deep_translator",
     "no GPU needed; great for short texts; rate-limits on long/bulk documents"),
    ("googletrans", "googletrans", None, "Google — translate_a endpoint (online, free; R-style)", "httpx",
     "handles long texts far better than option 1, but an unofficial endpoint that can break"),
    ("nllb", "nllb", "facebook/nllb-200-distilled-600M", "NLLB-200 600M (local)", "torch",
     "~2-3 GB VRAM; solid quality; offline, no rate limits, any length"),
    ("nllb-large", "nllb", "facebook/nllb-200-3.3B", "NLLB-200 3.3B (local)", "torch",
     "~8+ GB VRAM; best quality; offline, no rate limits"),
    ("opusmt", "opusmt", None, "OpusMT (local, one model per source language)", "torch",
     "light; downloads a small model per source language (no Pashto)"),
]


def recommend(vram_gb: float) -> str:
    """Which option key to recommend for a given amount of VRAM."""
    if vram_gb >= 15:
        return "nllb-large"
    if vram_gb >= 4:
        return "nllb"
    return "google"


def choose_backend(config, *, input_fn=input):
    """Prompt for a backend (recommending by GPU + availability) and return (translator_name,
    config). `config` may gain an `nllb_model` override. `input_fn` is injectable for tests."""
    vram, name = detect_gpu()
    rec = recommend(vram)
    print("\nGPU: " + (f"{name} ({vram:.0f} GB VRAM)" if name else "none detected (CPU only)"))
    print("Choose a translation backend:")
    for i, (key, _tr, _model, label, dep, note) in enumerate(OPTIONS, 1):
        rec_tag = "   <- recommended for this machine" if key == rec else ""
        miss = "" if _installed(dep) else f"   [needs `{dep}`, not in this env]"
        print(f"  {i}. {label}{rec_tag}\n       {note}{miss}")
    default_i = next(i for i, o in enumerate(OPTIONS, 1) if o[0] == rec)
    try:
        raw = (input_fn(f"Enter 1-{len(OPTIONS)} [default {default_i}]: ") or "").strip()
    except EOFError:
        raw = ""
    idx = int(raw) - 1 if raw.isdigit() and 1 <= int(raw) <= len(OPTIONS) else default_i - 1
    key, tr, model, label, dep, note = OPTIONS[idx]
    if not _installed(dep):
        print(f"\nNOTE: {label} needs `{dep}`, which is NOT installed in this Python env.")
        print("  Google -> run with the `leaderspeech_scrape` venv;")
        print("  NLLB/OpusMT -> run with the `transformers_new2025` venv (torch + transformers).")
    if model:
        config = config.model_copy(update={"nllb_model": model})
    print(f"Using backend: {tr}" + (f"  (model: {model})" if model else "") + "\n")
    return tr, config
