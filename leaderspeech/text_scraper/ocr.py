"""OCR language selection and toolchain discovery for image-only PDFs.

`pdf.py` does the OCR itself (ocrmypdf + Tesseract); this module answers the two questions
around it:

  * **Which Tesseract languages?** :func:`ocr_language_for` derives the spec from the recipe:
    an explicit ``pdf_ocr_language`` wins, otherwise the recipe's ``source_language`` mapped
    to its Tesseract pack, plus ``eng`` for a non-English source (government scans quote
    English names and titles). So ``pdf_ocr: true`` alone is enough on a Portuguese or
    Amharic recipe — no per-recipe language bookkeeping to get wrong.
  * **Is OCR usable on THIS machine?** :func:`toolchain` finds ocrmypdf, the Tesseract binary
    and its language packs, the way ocrmypdf will (PATH first, then the standard Windows
    install folders). ``python -m leaderspeech.text_scraper.ocr_check`` prints it.

:data:`TESSERACT_LANG` covers every ``source_language`` the recipes use (38 on 2026-09-30)
and a few likely next ones. Each code is a tessdata_best file name (``spa`` →
``spa.traineddata``). Somali has no Tesseract pack; it is Latin-script, so ``eng`` reads it
passably.
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Optional

# source_language (lower-case) -> Tesseract language spec ("+"-joined when a language is
# written in two scripts). Codes checked against tessdata_best's file list on 2026-09-30.
TESSERACT_LANG: dict[str, str] = {
    "english": "eng",
    "spanish": "spa",
    "portuguese": "por",
    "french": "fra",
    "arabic": "ara",
    "russian": "rus",
    "romanian": "ron",
    "croatian": "hrv",
    "slovenian": "slv",
    "slovak": "slk",
    "italian": "ita",
    "greek": "ell",
    "german": "deu",
    "dari": "fas",          # Dari is written in the Persian script; Tesseract has no prs pack
    "persian": "fas",
    "farsi": "fas",
    "pashto": "pus",
    "albanian": "sqi",
    "thai": "tha",
    "swedish": "swe",
    "mongolian": "mon",
    "icelandic": "isl",
    "hungarian": "hun",
    "finnish": "fin",
    "estonian": "est",
    "czech": "ces",
    "bulgarian": "bul",
    "vietnamese": "vie",
    "swahili": "swa",
    "somali": "eng",        # no Tesseract pack; Latin script
    "serbian": "srp+srp_latn",
    "polish": "pol",
    "norwegian": "nor",
    "macedonian": "mkd",
    "korean": "kor",
    "japanese": "jpn",
    "georgian": "kat",
    "danish": "dan",
    "azerbaijani": "aze",
    "amharic": "amh",
    # not used by a recipe yet, but plausible next sources
    "ukrainian": "ukr",
    "turkish": "tur",
    "hebrew": "heb",
    "hindi": "hin",
    "bengali": "ben",
    "urdu": "urd",
    "dutch": "nld",
    "catalan": "cat",
    "indonesian": "ind",
    "malay": "msa",
    "chinese": "chi_sim+chi_tra",
    "kazakh": "kaz",
    "uzbek": "uzb+uzb_cyrl",
    "armenian": "hye",
    "latvian": "lav",
    "lithuanian": "lit",
    "belarusian": "bel",
    "filipino": "fil",
    "burmese": "mya",
    "khmer": "khm",
    "lao": "lao",
    "nepali": "nep",
    "sinhala": "sin",
    "tamil": "tam",
    "kyrgyz": "kir",
    "tajik": "tgk",
    "tigrinya": "tir",
    "bosnian": "bos",
    "maltese": "mlt",
}

# Packs every OCR install should have: English, and OSD (orientation/script detection),
# which `rotate_pages` uses to turn a sideways scan upright.
BASE_PACKS = ("eng", "osd")


def tesseract_codes(language: Optional[str]) -> list[str]:
    """The Tesseract codes for one ``source_language`` name (unknown -> ``["eng"]``)."""
    spec = TESSERACT_LANG.get((language or "").strip().lower(), "eng")
    return [c for c in spec.split("+") if c]


def ocr_language_for(recipe) -> str:
    """The Tesseract language spec to OCR this recipe's scans in.

    An explicit ``pdf_ocr_language`` wins. Otherwise the ``source_language``'s pack, with
    ``+eng`` appended for a non-English source. Reads attributes defensively (``getattr``),
    so any object with those two names works — tests pass a SimpleNamespace."""
    explicit = getattr(recipe, "pdf_ocr_language", None)
    if explicit:
        return explicit
    codes = tesseract_codes(getattr(recipe, "source_language", None) or "English")
    if "eng" not in codes:
        codes.append("eng")
    return "+".join(codes)


# --- which packs do the recipes need? ----------------------------------------------------

def _recipe_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "recipes"


def _reads_documents(doc: dict) -> bool:
    return bool(doc.get("pdf_ocr") or doc.get("pdf_link")
                or str(doc.get("content_type", "")).lower() == "pdf")


def needed_codes(recipes_dir: Optional[Path] = None, documents_only: bool = False) -> list[str]:
    """Every Tesseract code the recipes could ask for, plus :data:`BASE_PACKS`.

    Reads each recipe's YAML directly (not ``load_recipe``), so one broken recipe can't hide
    the rest. ``documents_only`` limits it to recipes that read PDFs (``content_type: pdf``,
    ``pdf_link`` or ``pdf_ocr``); the default covers every recipe, since any HTML source may
    later gain a ``pdf_link``."""
    import yaml

    folder = Path(recipes_dir) if recipes_dir else _recipe_dir()
    codes: set[str] = set(BASE_PACKS)
    for path in sorted(folder.glob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(doc, dict) or (documents_only and not _reads_documents(doc)):
            continue
        explicit = doc.get("pdf_ocr_language")
        if explicit:
            codes.update(c for c in str(explicit).split("+") if c)
        else:
            codes.update(tesseract_codes(doc.get("source_language") or "English"))
    return sorted(codes)


# --- toolchain discovery ------------------------------------------------------------------

DEFAULT_TESSDATA = (Path(os.environ["LOCALAPPDATA"]) / "leaderspeech" / "tessdata"
                    if os.environ.get("LOCALAPPDATA") else None)


def _user_env_tessdata() -> Optional[str]:
    """The USER-level TESSDATA_PREFIX from the Windows registry (what setup_ocr.ps1 sets)."""
    if os.name != "nt":
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "TESSDATA_PREFIX")
            return str(value) or None
    except OSError:
        return None


def ensure_tessdata_env() -> Optional[str]:
    """Make sure THIS process points Tesseract at the per-user language packs.

    scripts/setup_ocr.ps1 sets TESSDATA_PREFIX at USER level, but a PowerShell window opened
    BEFORE that (a queue started from it, or this very session) still has the old environment
    and Tesseract then looks only in its own folder — every Portuguese scan fails as "no
    language data for por" (seen 2026-09-30, minutes after setup). So when the variable is
    missing here, take the registry's user value, else the default folder if it holds packs.
    Child processes (ocrmypdf -> tesseract) inherit it. Returns the folder in effect."""
    current = os.environ.get("TESSDATA_PREFIX")
    if current:
        return current
    for cand in (_user_env_tessdata(), DEFAULT_TESSDATA and str(DEFAULT_TESSDATA)):
        if cand and (Path(cand) / "eng.traineddata").is_file():
            os.environ["TESSDATA_PREFIX"] = cand
            return cand
    return None

def _windows_tesseract_candidates() -> Iterable[Path]:
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA") and
                 os.path.join(os.environ["LOCALAPPDATA"], "Programs")):
        if base:
            yield Path(base) / "Tesseract-OCR" / "tesseract.exe"
    home = Path.home()
    yield home / "scoop" / "shims" / "tesseract.exe"


def find_tesseract() -> Optional[str]:
    """Path of the Tesseract binary: PATH first, then the standard Windows install folders
    (ocrmypdf searches those too, so a binary found there is one it will use)."""
    hit = shutil.which("tesseract")
    if hit:
        return hit
    if os.name == "nt":
        for cand in _windows_tesseract_candidates():
            if cand.is_file():
                return str(cand)
    return None


def _run(args: list[str], timeout: float = 30.0) -> str:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                             encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    return (out.stdout or "") + (out.stderr or "")


def tesseract_version(binary: str) -> Optional[str]:
    m = re.search(r"tesseract\s+v?(\d+\.\d+\.\d+)", _run([binary, "--version"]), re.I)
    return m.group(1) if m else None


def tesseract_languages(binary: str) -> tuple[Optional[str], list[str]]:
    """(tessdata folder in effect, installed language codes) from ``--list-langs``."""
    text = _run([binary, "--list-langs"])
    folder = None
    m = re.search(r'List of available languages in "([^"]+)"', text)
    if m:
        folder = m.group(1)
    langs = [ln.strip() for ln in text.splitlines()[1:]
             if ln.strip() and re.fullmatch(r"[A-Za-z_]+(?:\\[A-Za-z_]+)?", ln.strip())]
    return folder, sorted(langs)


# ocrmypdf refuses this release outright ("not supported due to regressions") — and it is
# the version winget's UB-Mannheim.TesseractOCR package installs.
BAD_TESSERACT = {"5.4.0"}


def _version_tuple(v: Optional[str]) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3])


@functools.lru_cache(maxsize=1)
def toolchain() -> dict:
    """What OCR can use on this machine (cached for the process). Keys: ``ocrmypdf``
    (version or None), ``tesseract`` (path or None), ``tesseract_version``, ``tessdata``,
    ``languages``, ``ghostscript`` (path or None — only needed for PDF/A output, which the
    engine doesn't ask for), and ``problems`` (human-readable list; empty = usable)."""
    ensure_tessdata_env()
    info: dict = {"ocrmypdf": None, "tesseract": None, "tesseract_version": None,
                  "tessdata": None, "languages": [], "ghostscript": None, "problems": []}
    try:
        import ocrmypdf  # noqa: F401
        from importlib.metadata import version as _v
        info["ocrmypdf"] = _v("ocrmypdf")
    except Exception:
        info["problems"].append("ocrmypdf is not installed (pip install -e \".[pdf,pdf-ocr]\")")
    binary = find_tesseract()
    if not binary:
        info["problems"].append("no Tesseract binary on PATH or in the standard install folders")
    else:
        info["tesseract"] = binary
        info["tesseract_version"] = tesseract_version(binary)
        if info["tesseract_version"] in BAD_TESSERACT:
            info["problems"].append(f"Tesseract {info['tesseract_version']} is refused by ocrmypdf "
                                    "(regressions) — install 5.5 or later")
        elif _version_tuple(info["tesseract_version"]) < (4, 1, 1):
            info["problems"].append(f"Tesseract {info['tesseract_version']} is older than "
                                    "ocrmypdf's minimum (4.1.1)")
        info["tessdata"], info["languages"] = tesseract_languages(binary)
        missing = [c for c in BASE_PACKS if c not in info["languages"]]
        if missing:
            info["problems"].append(f"missing base language pack(s): {', '.join(missing)}")
    info["ghostscript"] = (shutil.which("gswin64c") or shutil.which("gswin32c")
                           or shutil.which("gs"))
    return info


def missing_codes(spec: str, installed: Iterable[str]) -> list[str]:
    have = set(installed)
    return [c for c in spec.split("+") if c and c not in have]
