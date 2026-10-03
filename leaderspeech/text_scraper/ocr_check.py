"""Is OCR usable on this machine? — the doctor behind `pdf_ocr` / `run --ocr`.

    python -m leaderspeech.text_scraper.ocr_check            # full report + smoke test
    python -m leaderspeech.text_scraper.ocr_check --needed   # just the Tesseract codes the
                                                             # recipes need (setup script input)
    python -m leaderspeech.text_scraper.ocr_check --langs por+eng --quiet   # exit code only

Checks ocrmypdf, the Tesseract binary (path, version — 5.4.0 is refused by ocrmypdf), the
tessdata folder in effect (`TESSDATA_PREFIX`), which language packs are installed against
the ones the recipes need, and Ghostscript (reported, NOT required: the engine never asks for
PDF/A output). Then a SMOKE TEST: it renders a line of text to an image-only PDF and runs it
through the engine's own `pdf.pdf_bytes_to_text(..., ocr=True)` — so a PASS means the scraper
will OCR, not merely that the binaries exist.

Exit codes: 0 = OCR works and every needed pack is installed; 1 = OCR does not work here;
2 = OCR works but some needed language packs are missing (those scans will fail cleanly as
`empty_text (… OCR unavailable …)` and can be retried later).

Setup on a new machine: scripts/setup_ocr.ps1 (see docs/ocr_setup.md).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

from . import ocr, pdf

SMOKE_TEXT = {
    "eng": "LeaderSpeech optical character recognition check",
    "spa": "Discurso del presidente de la republica",
    "por": "Discurso do presidente da republica",
    "fra": "Discours du president de la republique",
}


def _smoke_pdf(text: str) -> bytes:
    """An image-only one-page PDF showing `text` (no text layer at all)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (2000, 260), 255)
    draw = ImageDraw.Draw(img)
    font = None
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            font = ImageFont.truetype(name, 72)
            break
        except OSError:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=72)
        except TypeError:  # Pillow < 10.1
            font = ImageFont.load_default()
    draw.text((40, 80), text, fill=0, font=font)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "smoke.pdf")
        img.save(path, "PDF", resolution=200.0)
        with open(path, "rb") as fh:
            return fh.read()


def smoke_test(lang: str = "eng") -> tuple[bool, str]:
    """OCR a rendered line through the engine's real PDF path. (ok, what came back)."""
    words = SMOKE_TEXT.get(lang, SMOKE_TEXT["eng"])
    spec = lang if lang == "eng" else f"{lang}+eng"
    try:
        data = _smoke_pdf(words)
    except Exception as e:
        return False, f"could not render the test image ({type(e).__name__}: {e})"
    pdf.take_empty_reason()
    got = pdf.pdf_bytes_to_text(data, ocr=True, ocr_language=spec)
    reason = pdf.take_empty_reason()
    if not got.strip():
        return False, reason or "OCR returned no text"
    want = [w.lower() for w in words.split() if len(w) > 3]
    hit = sum(1 for w in want if w in got.lower())
    return hit >= max(1, len(want) - 1), " ".join(got.split())[:120]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check that PDF OCR works on this machine")
    ap.add_argument("--needed", action="store_true",
                    help="print the Tesseract codes the recipes need (space-separated) and exit")
    ap.add_argument("--documents-only", action="store_true",
                    help="with --needed / the report: only recipes that read PDFs")
    ap.add_argument("--langs", default=None,
                    help="'+'-joined codes to require instead of the recipes' set (e.g. por+eng)")
    ap.add_argument("--smoke-lang", default="eng",
                    help="language of the smoke test (eng, spa, por, fra; default eng)")
    ap.add_argument("--no-smoke", action="store_true", help="skip the OCR smoke test")
    ap.add_argument("--quiet", action="store_true", help="no report; exit code only")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if args.needed:
        print(" ".join(ocr.needed_codes(documents_only=args.documents_only)))
        return 0

    info = ocr.toolchain()
    needed = (sorted(set(args.langs.split("+")) | set(ocr.BASE_PACKS)) if args.langs
              else ocr.needed_codes(documents_only=args.documents_only))
    missing = ocr.missing_codes("+".join(needed), info["languages"]) if info["tesseract"] else needed
    smoke_ok, smoke_msg = (None, "skipped")
    if not args.no_smoke and not info["problems"]:
        smoke_ok, smoke_msg = smoke_test(args.smoke_lang)

    usable = not info["problems"] and smoke_ok is not False
    code = 1 if not usable else (2 if missing else 0)
    if args.quiet:
        return code

    def row(k, v):
        print(f"  {k:<22} {v}")
    print("OCR toolchain")
    row("ocrmypdf", info["ocrmypdf"] or "NOT INSTALLED")
    row("tesseract", info["tesseract"] or "NOT FOUND")
    row("tesseract version", info["tesseract_version"] or "-")
    row("TESSDATA_PREFIX", os.environ.get("TESSDATA_PREFIX") or "(unset - Tesseract's own folder)")
    row("tessdata in effect", info["tessdata"] or "-")
    row("packs installed", f"{len(info['languages'])}: {' '.join(info['languages'])}")
    row("packs needed", f"{len(needed)} ({'recipes reading PDFs' if args.documents_only else '--langs' if args.langs else 'every recipe language'})")
    row("packs MISSING", " ".join(missing) if missing else "none")
    row("ghostscript", (info["ghostscript"] or "not found") + "  (optional - PDF/A only)")
    row("smoke test", ("PASS" if smoke_ok else "FAIL" if smoke_ok is False else "-")
        + f"  [{args.smoke_lang}] {smoke_msg}")
    for p in info["problems"]:
        print(f"  ! {p}")
    verdict = {0: "PASS - OCR works and every needed pack is installed",
               1: "FAIL - OCR does not work on this machine (see docs/ocr_setup.md)",
               2: "PARTIAL - OCR works; install the missing packs (scripts/setup_ocr.ps1)"}[code]
    print(f"\n{verdict}")
    return code


if __name__ == "__main__":
    sys.exit(main())
