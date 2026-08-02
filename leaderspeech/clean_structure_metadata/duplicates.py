"""Find and CLASSIFY rows that share identical text. Reports only — never deletes anything.

WHAT A "DUPLICATE" IS HERE (measured over 66 wayback CSVs / 123,024 rows: 5,358 extra rows, 4.4%):
  * always BYTE-IDENTICAL text, and
  * always on DIFFERENT `source` URLs with DIFFERENT `doc_id`s.
    The same URL is never scraped twice -- 0 cases corpus-wide. So the question is never "did we
    fetch this twice", it is "what URL variation produced the same text".

NEVER dedupe on `title`. Of 33,482 rows sharing a title, 93.4% have genuinely DIFFERENT text. That
is two other problems wearing the same costume: a generic site <title> bleeding into every row
(aze_president_english_wayback: 4,595 rows, 348 distinct titles) and legitimately recurring
headlines ("tender announcement" x187). Neither is duplication.

THE CAUSES, and why they are not interchangeable:

  url_variant        same URL modulo query string / http-vs-https / :80 / www / trailing slash
  mirror             same path on a different host (president.al <-> arkiva.president.al)
  id_variant         same numeric article id reached by a different slug or section path
  slug_variant       CMS duplicate slug (-2 / -4)
        ^ for all four the rows really are ONE document. Collapsing to one representative is safe.

  junk_stub          short placeholder/boilerplate ("this page is under construction", "Higher
                     resolution"). Not a document at all -- drop the whole cluster, keep none.

  shared_text_suspect
                     identical LONG text on genuinely unrelated URLs. THIS IS NOT DUPLICATION --
                     it is an extraction failure: the text does not belong to the URL. 107 distinct
                     Belarus article URLs all carry the same 40,078-char press-release INDEX; 51
                     Armenian 2008 URLs all carry the same 2018 commemoration page (the archived
                     URLs redirected to then-current content). Keeping one representative would
                     attach the wrong speech to a real URL, so these want deleting, not deduping --
                     which is exactly why the cause is reported rather than silently collapsed.

Run it:
    python -m leaderspeech.clean_structure_metadata.duplicates --all
    python -m leaderspeech.clean_structure_metadata.duplicates --source uzb_president_english_wayback
-> data/_build/duplicate_clusters.csv, one row per cluster, for eyeballing before any decision.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

log = logging.getLogger("leaderspeech.clean_structure_metadata.duplicates")

# below this, identical text is boilerplate rather than a document
JUNK_MAX_CHARS = 300

_JUNK_MARKERS = (
    "under construction", "higher resolution", "link to video", "page not found",
    "access denied", "coming soon",
)
_SLUG_DUP = re.compile(r"-(\d+)$")
_NUM_ID = re.compile(r"/(\d{2,})(?:/|$)")


def pick_text(row) -> str:
    """Speech text lives in `text` (English sources) or `text_originlanguage` (others).

    Checking BOTH matters: afg_aop_wayback.csv has an empty `text` column for all 2,379 rows (the
    Dari content is in the *_originlanguage columns), so hashing `text` alone would report the whole
    file as one giant duplicate cluster.
    """
    for key in ("text", "text_originlanguage"):
        v = row.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def normalize_text(text: str) -> str:
    """Case/whitespace-normalized form used for hashing. Albania's `arkiva` mirror renders slightly
    different boilerplate around the same article, so exact matching alone under-counts it by ~505
    rows."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def text_hash(text: str) -> str:
    return hashlib.sha1(normalize_text(text).encode("utf-8")).hexdigest()


def _canonical_url(url: str) -> tuple[str, str, str]:
    """(host_without_www, path_without_trailing_slash, canonical) with scheme/port/query dropped."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return "", "", (url or "")
    host = (parts.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    path = (parts.path or "").rstrip("/")
    return host, path, f"{host}{path}"


def classify(urls: list[str], text: str) -> str:
    """Why do these URLs share text? See the module docstring for what each verdict implies."""
    if len(normalize_text(text)) < JUNK_MAX_CHARS:
        low = (text or "").lower()
        if any(m in low for m in _JUNK_MARKERS) or len(normalize_text(text)) < 120:
            return "junk_stub"

    canon = {_canonical_url(u) for u in urls}
    hosts = {h for h, _, _ in canon}
    paths = {p for _, p, _ in canon}

    if len({c for _, _, c in canon}) == 1:
        return "url_variant"            # differed only by scheme/port/www/query/trailing slash
    if len(paths) == 1 and len(hosts) > 1:
        return "mirror"                 # same path, different host

    # same numeric article id reached by different slugs/sections
    ids = [set(_NUM_ID.findall(p)) for _, p, _ in canon]
    if ids and all(ids[0] & other for other in ids[1:]) and ids[0]:
        return "id_variant"

    stripped = {_SLUG_DUP.sub("", p) for _, p, _ in canon}
    if len(stripped) == 1:
        return "slug_variant"

    return "shared_text_suspect"        # NOT duplication -- an extraction failure


def _iter_csvs(root: Path, source: str | None, country: str | None):
    pattern = f"{country}/*.csv" if country else "*/*.csv"
    for p in sorted(root.glob(pattern)):
        if p.name.endswith(("_errors.csv", "_media.csv")):
            continue
        if source and p.stem != source:
            continue
        yield p


def find_clusters(csv_path: Path) -> list[dict]:
    """Clusters of rows in one scraped CSV that share normalized text."""
    try:
        df = pd.read_csv(csv_path, low_memory=False)
    except Exception as e:
        log.warning("could not read %s: %s", csv_path, e)
        return []
    if df.empty:
        return []

    df = df.copy()
    df["_text"] = [pick_text(r) for _, r in df.iterrows()]
    df = df[df["_text"].str.strip().astype(bool)]
    if df.empty:
        return []
    df["_hash"] = df["_text"].map(text_hash)

    out = []
    for h, grp in df.groupby("_hash"):
        if len(grp) < 2:
            continue
        urls = [str(u) for u in grp.get("source", pd.Series(dtype=str)).fillna("")]
        text = grp["_text"].iloc[0]
        doc_ids = [str(d) for d in grp.get("doc_id", pd.Series(dtype=str)).fillna("")]
        caps = [str(c) for c in grp.get("wayback_capture", pd.Series(dtype=str)).fillna("")]
        out.append({
            "source_id": csv_path.stem,
            "country": csv_path.parent.name,
            "cause": classify(urls, text),
            "rows": len(grp),
            "extra_rows": len(grp) - 1,
            "text_chars": len(text),
            "text_hash": h[:12],
            "doc_ids": " | ".join(doc_ids[:8]),
            "urls": " | ".join(urls[:8]),
            "captures": " | ".join(sorted({c for c in caps if c})[:8]),
            "titles": " | ".join(sorted({str(t) for t in grp.get("title", pd.Series(dtype=str)).fillna("")
                                         if str(t).strip()})[:4]),
            "text_head": re.sub(r"\s+", " ", text[:300]),
        })
    return out


def build_report(in_root: str = "data/scraped", out_path: str = "data/_build/duplicate_clusters.csv",
                 source: str | None = None, country: str | None = None) -> dict:
    """Write one row per duplicate-text cluster. READ-ONLY over the scraped data; the only file
    written is the report itself. Nothing is ever removed from a source CSV by this tool."""
    root = Path(in_root)
    clusters: list[dict] = []
    for csv_path in _iter_csvs(root, source, country):
        clusters.extend(find_clusters(csv_path))

    summary = {"clusters": len(clusters), "extra_rows": sum(c["extra_rows"] for c in clusters),
               "output": str(out_path), "by_cause": {}}
    if not clusters:
        log.info("no duplicate-text clusters found")
        return summary

    df = pd.DataFrame(clusters).sort_values(["extra_rows", "source_id"], ascending=[False, True])
    summary["by_cause"] = (df.groupby("cause")["extra_rows"].sum().sort_values(ascending=False)
                           .astype(int).to_dict())
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    log.info("duplicates: %d clusters, %d extra rows -> %s",
             len(clusters), summary["extra_rows"], out)
    for cause, n in summary["by_cause"].items():
        log.info("  %-20s %6d extra rows", cause, n)
    return summary


def main():
    ap = argparse.ArgumentParser(
        description="Report clusters of scraped rows that share identical text. Never deletes.")
    ap.add_argument("--source", help="a single source_id")
    ap.add_argument("--country", help="only this country folder")
    ap.add_argument("--all", action="store_true", help="every scraped source")
    ap.add_argument("--in-root", default="data/scraped")
    ap.add_argument("--out", default="data/_build/duplicate_clusters.csv")
    args = ap.parse_args()
    if not (args.source or args.country or args.all):
        ap.error("pass --source, --country or --all")

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    summary = build_report(args.in_root, args.out, args.source,
                           None if args.all else args.country)
    print(summary)


if __name__ == "__main__":
    main()
