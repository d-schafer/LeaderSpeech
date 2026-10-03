# OCR for scanned PDFs — setting up a machine

Some sources publish speeches as **image-only PDFs**: scans with no text layer (Brazil's Old
Republic messages to Congress, typewritten transcripts) or exports whose text is drawn as
outlines (El Salvador 2021). `pdfminer` extracts nothing from them. With OCR on, the engine
renders each page and reads it with **Tesseract** (through `ocrmypdf`).

Without OCR on a machine, nothing breaks: those documents fail cleanly as
`empty_text (document has no text layer; …)`, stay in the source's `failed_urls`, and a later
`--retry-failed --ocr` run on a machine that has OCR recovers them.

## One-time setup (per machine, ~5 minutes + ~360 MB of downloads)

Run the setup script from PowerShell. It is idempotent, so you can re-run it any time:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& ".\github_repo\LeaderSpeech\scripts\setup_ocr.ps1"
```

From a Command Prompt instead:

```
powershell -NoProfile -ExecutionPolicy Bypass -File .\github_repo\LeaderSpeech\scripts\setup_ocr.ps1
```

What it does:

1. **ocrmypdf.** It installs the `pdf-ocr` extra into the `leaderspeech_scrape` venv. It finds the
   venv on any of the three machines, or you can pass `-Python <path>`.
2. **Tesseract 5.5+.** It keeps an install that is already good enough. Otherwise it runs
   `winget install tesseract-ocr.tesseract`, which brings **one UAC prompt to approve**.
   - It does **not** use winget's `UB-Mannheim.TesseractOCR`. That package is 5.4.0, and ocrmypdf
     refuses 5.4.0 outright ("not supported due to regressions").
   - If 5.4.0 is installed, the script removes it first.
3. **PATH.** It adds Tesseract's folder to your *user* PATH if it is on no PATH yet.
4. **Language packs.** It downloads **tessdata_best** packs into
   `%LOCALAPPDATA%\leaderspeech\tessdata`, a per-user folder that needs no admin rights.
   - By default it takes every language a recipe uses (38 on 2026-09-30) plus `eng` and `osd`.
   - It also copies Tesseract's own `configs/`, `tessconfigs/` and `pdf.ttf`, along with any packs
     already installed there.
5. **TESSDATA_PREFIX.** It sets your *user* environment variable `TESSDATA_PREFIX` to that folder.
6. **The doctor.** It runs a check that includes a real OCR test, and ends with PASS, PARTIAL
   or FAIL.

**Ghostscript is not needed.** The engine asks ocrmypdf for text only, never for PDF/A output,
and ocrmypdf 17 renders pages with pypdfium2. `-Ghostscript` installs it anyway.

Switches:

| switch | effect |
|---|---|
| `-PdfOnly` | Only the languages of recipes that read PDFs (7 packs, ≈66 MB instead of ≈360 MB). |
| `-All` | Every tessdata pack (~130 languages). |
| `-Fast` | `tessdata_fast` instead of `tessdata_best`. Smaller and quicker, but worse on old typewritten scans. |
| `-Force` | Re-download packs that are already present. |
| `-SkipTesseract` / `-SkipPip` | Report only, or don't touch the venv. |

After it passes, **open a new PowerShell window** before starting a queue, so the new PATH and
`TESSDATA_PREFIX` are inherited. The engine also reads the user-level `TESSDATA_PREFIX` from the
registry when a process doesn't have it, so a queue started from an old window still finds the
packs.

## Check a machine

```powershell
& "<venv>\Scripts\python.exe" -m leaderspeech.text_scraper.ocr_check
```

It prints the ocrmypdf and Tesseract versions, the tessdata folder in effect, the installed
packs against the ones the recipes need, and a smoke test that OCRs a rendered line through the
engine's own PDF code. Exit codes:

- **0 (PASS):** OCR works and every needed pack is present.
- **1 (FAIL):** OCR doesn't work here.
- **2 (PARTIAL):** OCR works, but some packs are missing. Scans in those languages fail cleanly
  until you re-run the setup script.

`--smoke-lang spa|por|fra` tests another language, and `--needed` prints the codes the recipes
need.

| machine | status |
|---|---|
| home desktop | **PASS** 2026-09-30: Tesseract 5.5.3, tessdata_best, 42 packs. |
| MSU workstation | not set up yet. Run the script there (you have admin). |
| laptop | not set up yet. |

## Using it

- **Per recipe:** `pdf_ocr: true`. The language comes from `source_language` (`Portuguese` →
  `por+eng`). `pdf_ocr_language` overrides it, e.g. `fas+pus+eng`. Since 2026-09-30, every
  recipe that reads PDFs or Word files sets `pdf_ocr: true`.
- **When it triggers:** only when a document's text layer is empty or nearly empty (< 50 word
  characters). A normal PDF never pays for OCR.
- **Per run:** `python -m leaderspeech.text_scraper.run --recipe … --ocr` turns it on even where
  the recipe doesn't. The same flag exists for `probe --ocr`, and the queue runner has `-Ocr`.
- **Queue preflight:** when a queue would OCR, `scrape_queue_wayback.ps1` warns if this machine
  can't.
- **Speed:** with tessdata_best, a long scanned message takes about 1 minute. The 1908 Afonso
  Pena message (a 2.3 MB scan) took 57 s and gave 93,770 characters of good Portuguese.

## Recovering the backlog

```powershell
& "<venv>\Scripts\python.exe" recipe_tools\ocrbacklog.py
```

This lists, per source, the documents that are *currently* failed as `empty_text`. It reads the
state file's `failed_urls`; the `_errors.csv` history alone overcounts. It also lists how many
other failures a `-RetryFailed` run would retry.

The recovery queues live in `queues\retry\` (finished ones move to `queues\retry\done\`), run with
`-NoIndex -RetryFailed -Ocr`. Don't run one at the same time as a queue that covers the same
country.

**Not every empty document is a scan.** The Internet Archive holds many large PDFs only as a
1 MiB / 5 MiB prefix. Before 2026-10-02 a cut PDF failed exactly like a scan. ocrmypdf can't open a
file without its page tree: `InputFileError`, logged as a blank `OCR failed to process a PDF:`.
The engine now rebuilds the surviving pages, OCRs them, and writes the row flagged
`document_truncated` (recipes.md → "Truncated archived documents"). `ocrbacklog.py` counts cut
captures in its own `cut` column.

## Troubleshooting

| symptom | cause, fix |
|---|---|
| `OCR unavailable: … does not have language data for … por` | The pack isn't in the tessdata folder in effect. Re-run the setup script. Check `ocr_check`'s "tessdata in effect" line. |
| `Tesseract 5.4.0 is refused by ocrmypdf` | That's the UB-Mannheim winget package. The setup script replaces it with `tesseract-ocr.tesseract`. |
| `no Tesseract binary on PATH or in the standard install folders` | The install was declined at the UAC prompt. Re-run the script from an elevated PowerShell. |
| `OCR requested but ocrmypdf is not installed` | Run `pip install -e ".[pdf,pdf-ocr]"` in the venv. The script does this. |
| OCR works in a new window but not in a queue | The queue was started from a window opened before setup. Since 2026-09-30 the engine finds the per-user packs anyway. If not, open a new window. |
