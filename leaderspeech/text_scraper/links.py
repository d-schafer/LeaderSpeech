"""What we KNOW how to fetch for a source, read back off disk.

`n_speeches` on its own cannot say whether a source is *finished*: 1,528 rows is complete
for Argentina and about 4% of Romania. The denominator is already written down — a run
saves `<Country>/<id>_links.txt` plus a dated `sample/<id>_links_<stamp>.txt` copy, and
every probe saves `sample/<id>_probe_<stamp>.txt`. All three are the FULL harvest, one bare
URL per line. Nothing re-fetches here; this module only reads what the engine already left.

Three rules earn their keep.

**Union, not precedence.** Every list is evidence and none is authoritative, because
`<id>_links.txt` is *overwritten* by each run: a `--max-pages 20` queue run replaces the
record of a prior full crawl. The dated `sample/` copies survive it, so the history is
intact — but every existing reader opens exactly one file and therefore misses it. Measured
over the tree (2026-08-10): 48 of 170 sources have a current `<id>_links.txt` SMALLER than a
list already in their own archive, and for 34 the current file is also the newest, so a
newest-wins rule picks the small one (`zaf_thepresidency_wayback` 9,981 vs 26,378;
`mda_presedinte` 294 vs 1,378). Unioning recovers all of it.

**Filter the union through the recipe's CURRENT `link_pattern`.** A union alone drifts the
other way. Recipes get tightened to drop a non-substantive site branch, and the dropped URLs
sit in the old snapshots forever, inflating the denominator so `percent_scraped` reads
falsely low. :func:`recipe_link_filter` replays the engine's own test — the same
`re.search(link_pattern, absolute_url)` used by `paginate.extract_links`,
`paginate` (sitemap), `api`, `feed` and `wayback.filter_entries_for_recipe` — so the
denominator is always "what this recipe would harvest today". It self-corrects on the next
index rebuild, with no file to delete and no maintenance rule to remember. Measured: it
prunes 61,266 links (11% of the union) across 22 sources, and it reproduces the engine
exactly — for `zaf_thepresidency_wayback` and `alb_president_english_wayback` the re-filtered
count lands on the current `<id>_links.txt` to the link (9,981 and 168).

**Say when the denominator is a floor.** A harvest can be cut short by a broken pager
(`stopped_early`), by the 200-page default cap (`stop_reason: max_pages`, which
`paginate.NORMAL_STOPS` classifies as a *clean* finish and is therefore the easy one to
miss), or because the only record is a probe that never left page 1. Reporting a percentage
off a floor reads as "nearly done" when it means "we never looked". :data:`STATUS` is that
caveat, in one token.

This module is the single canonical implementation. `index.py` uses it for the workbook's
`n_unique_links` / `percent_scraped` / `links_status` columns; the local triage scripts
should import it rather than re-roll link discovery, which is how they ended up with three
mutually inconsistent precedence rules.

    python -m leaderspeech.text_scraper.links --audit          # per-source union / kept / dropped
    python -m leaderspeech.text_scraper.links --csv out.csv
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# Link lists that are NOT a source's own harvest. Empty today: `<id>_wayback_extend_links.txt`
# is deliberately counted, because a wayback_extend continuation scrapes into the SAME
# `<id>.csv` and its rows are inside `n_speeches` — leaving its URLs out of the denominator
# would be the one way to manufacture a percentage above 100. The constant stays because
# `discover_sources` globs `*_links.txt` by wildcard, and there the exclusion IS needed: the
# suffix would otherwise invent a phantom source id `<X>_wayback_extend`.
EXCLUDE_SUFFIXES: tuple[str, ...] = ()
_DISCOVERY_EXCLUDE: tuple[str, ...] = ("_wayback_extend_links.txt",)

# `paginate.NORMAL_STOPS` treats these as clean finishes — they are, but the harvest is
# still bounded by a cap rather than by the end of the archive, so the count is a floor.
CAPPED_STOP_REASONS = frozenset({"max_pages", "max_links"})

# A harvest must be at least this fraction of the LARGEST harvest before its truncation
# verdict brands the whole source. See the rationale in `link_universe`.
FLAG_CONTRIBUTION = 0.5

STATUS = {
    "": "no link list on disk — n_unique_links and percent_scraped are BLANK, not 0",
    "stale_links": "n_speeches EXCEEDS n_unique_links: the lists are stale or narrower than "
                   "the recipe. percent_scraped reads above 100 and is meaningless.",
    "page1_only": "the only record is a probe that never left page 1 (its JSON listing has "
                  "no `mode` key). A hard FLOOR, often off by ~100x — re-probe with --spread.",
    "stopped_early": "a contributing harvest reported listing.stopped_early: pagination was "
                     "cut short by a pager fault, not by reaching the end. FLOOR.",
    "capped": "a contributing harvest stopped at max_pages / max_links (including the "
              "200-page default). A NORMAL stop that is still a FLOOR.",
    "post_limit": "audio source: the link list is written AFTER --max-videos, so it equals "
                  "what was fetched. percent_scraped is ~100 by construction and says "
                  "nothing about the channel's real size.",
    "unfiltered": "no recipe, or a selector-only listing with no link_pattern — the union "
                  "could not be re-filtered, so the denominator may be too WIDE.",
    "complete": "a real run's harvest is on disk and nothing flags truncation.",
    "probe_only": "no run has harvested this source; the count comes from a full "
                  "(--spread / wayback / api / feed) probe.",
}


def normalize_url(u: str) -> str:
    """Collapse a URL to a comparison key: lowercase, drop scheme / leading `www.` / `:80` /
    doubled and trailing slashes. Query strings are KEPT and nothing is percent-decoded.

    Matches `code/count_scrape_potential.R`'s `norm_url` exactly, so the R analysis and the
    workbook agree on what "unique" means. Two spellings of one document have to collapse —
    a wayback list holds `http://aop.gov.af:80/dari/1025` where the live list holds
    `https://aop.gov.af/dari/1025` — but query-addressed sites (`?id=123`) must stay
    distinct, which is why the query survives.

    Deliberately looser than `wayback.page_identity`, which also drops denylisted noise
    params and WordPress comment sub-paths. That one decides "is this the same DOCUMENT"
    while a crawl is running and can merge two links a recipe would fetch separately; using
    it here would shrink the denominator and inflate `percent_scraped`.
    """
    u = u.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.replace(":80/", "/", 1)
    u = re.sub(r"/{2,}", "/", u)
    return u.rstrip("/")


def _url_path(u: str) -> str:
    try:
        return urlparse(u).path.rstrip("/")
    except Exception:
        return ""


def recipe_link_filter(recipe) -> Optional[Callable[[str], bool]]:
    """The recipe's CURRENT view of "is this URL one of mine", so it can be replayed over
    harvests taken under older versions of the recipe.

    Mirrors the engine: `re.search(listing.link_pattern, <absolute url>)`, plus the
    listing-index drop `wayback.filter_entries_for_recipe` performs (a URL whose *path*
    equals one of `start_urls`' paths is the index page, not a speech — and its `?page=2`
    variants share that path).

    Returns None when there is no recipe, or the listing is selector-only with no
    `link_pattern`. Nothing can be replayed then, so the raw union stands and the caller
    reports `unfiltered` rather than pretending the denominator is exact. Every recipe in
    the tree has a `link_pattern` today, so this is a fallback, not a common path.

    ⚠️ Apply this to the RAW line, before :func:`normalize_url`. Patterns are written
    against real absolute URLs and many are anchored on the scheme or host; matching a
    normalized key would silently reject everything.
    """
    listing = getattr(recipe, "listing", None)
    pattern_src = getattr(listing, "link_pattern", None) if listing is not None else None
    if not pattern_src:
        return None
    try:
        pattern = re.compile(pattern_src)
    except re.error as e:  # a recipe that wouldn't compile can't filter; don't sink the index
        log.warning("links: uncompilable link_pattern %r :: %s", pattern_src, e)
        return None
    index_paths = {_url_path(u) for u in (getattr(recipe, "start_urls", None) or [])}

    def keep(url: str) -> bool:
        return bool(pattern.search(url)) and _url_path(url) not in index_paths

    return keep


def link_files(country_dir: Path, source_id: str) -> list[tuple[str, Path]]:
    """Every on-disk link list for one source as `(kind, path)`, newest first.

    Three shapes live under `data/scraped/<Country>/`:

    ==================================  ======================================================
    ``<id>_links.txt``                   the last run's FULL harvest — written before any
                                         scraping (`run.scrape_recipe`), so neither `--limit`
                                         nor the already-seen dedupe shrinks it. Overwritten.
    ``sample/<id>_links_<stamp>.txt``    dated, never-overwritten copies of the same
    ``sample/<id>_probe_<stamp>.txt``    a probe's harvest (`probe.save_probe_snapshot`)
    ==================================  ======================================================

    Sibling source ids stay apart because the first shape is matched by exact name and the
    other two carry a literal `_links_` / `_probe_` infix: `gha_presidency` never picks up
    `gha_presidency_wayback_probe_*.txt`.
    """
    out: list[tuple[str, Path]] = []
    fixed = country_dir / f"{source_id}_links.txt"
    if fixed.is_file() and not (EXCLUDE_SUFFIXES and fixed.name.endswith(EXCLUDE_SUFFIXES)):
        out.append(("run", fixed))
    sample_dir = country_dir / "sample"
    if sample_dir.is_dir():
        out += [("run_snapshot", p) for p in sample_dir.glob(f"{source_id}_links_*.txt")]
        out += [("probe", p) for p in sample_dir.glob(f"{source_id}_probe_*.txt")]

    def mtime(item: tuple[str, Path]) -> float:
        try:
            return item[1].stat().st_mtime
        except OSError:
            return 0.0

    return sorted(out, key=mtime, reverse=True)


def _read_urls(path: Path) -> list[str]:
    """Raw (un-normalized) http URLs from a link list. Never raises.

    `utf-8-sig` because the `sample/` tree gets opened and re-saved by hand on Windows, and
    a BOM would otherwise corrupt the first URL; `errors="replace"` because one mangled line
    is a better outcome than losing the whole file. `splitlines()` handles CRLF. The
    `http` test drops blank lines and the `#` comments an audio `links_file` may carry.
    """
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as e:
        log.debug("links: unreadable %s :: %s", path, e)
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip().lower().startswith("http")]


def _read_listing_meta(path: Path) -> dict:
    """The `listing` block of a link list's JSON sibling, or `{}`.

    Probes write `<id>_probe_<stamp>.json` next to their `.txt`, and runs write a matching
    `<id>_links_<stamp>.json` — deliberately the same key names, so there is one rule here
    instead of two. A half-written file must never raise: neither writer is atomic, and a
    Dropbox sync can catch one mid-flight.
    """
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        return {}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception as e:  # noqa: BLE001 — corrupt/truncated JSON is expected, not fatal
        log.debug("links: unreadable sidecar %s :: %s", sidecar, e)
        return {}
    listing = payload.get("listing")
    return listing if isinstance(listing, dict) else {}


@dataclass(frozen=True)
class LinkUniverse:
    """Every URL we currently know how to fetch for one source, plus how much to trust it."""

    urls: frozenset[str] = field(default=frozenset(), repr=False, compare=False)
    n_dropped_by_pattern: int = 0
    unfiltered: bool = False
    n_files: int = 0
    kinds: frozenset[str] = frozenset()
    newest: Optional[float] = None
    stopped_early: bool = False
    capped: bool = False
    page1_only: bool = False

    @property
    def n_unique(self) -> int:
        return len(self.urls)

    @property
    def found(self) -> bool:
        """Did we look at all? False means BLANK cells, never 0 — "we know of zero links"
        is the opposite of the truth for a source scraped before link lists were saved."""
        return self.n_files > 0

    def status(self, *, n_scraped: Optional[int] = None, audio: bool = False) -> str:
        """One token from :data:`STATUS`, worst first.

        Truncation outranks `complete` on purpose: a run and a probe share
        `paginate.harvest_links`, so a pager that broke for one broke for the other.
        """
        if not self.found:
            return ""
        if n_scraped is not None and n_scraped > self.n_unique:
            return "stale_links"
        if audio:
            return "post_limit"
        if self.page1_only:
            return "page1_only"
        if self.stopped_early:
            return "stopped_early"
        if self.capped:
            return "capped"
        if self.unfiltered:
            return "unfiltered"
        if self.kinds & {"run", "run_snapshot"}:
            return "complete"
        return "probe_only"


def link_universe(country_dir: Path, source_id: str, recipe=None) -> LinkUniverse:
    """Union every link list for one source, re-filtered through the recipe's current
    `link_pattern`, with the reliability flags of whichever harvest dominates the count.

    Never raises — an unreadable file simply contributes nothing.
    """
    files = link_files(Path(country_dir), source_id)
    keep = recipe_link_filter(recipe)

    union: set[str] = set()
    raw_union: set[str] = set()
    kinds: set[str] = set()
    newest: Optional[float] = None
    contributions: list[tuple[int, float, Path]] = []

    for kind, path in files:
        raw = _read_urls(path)
        kinds.add(kind)
        raw_union |= {normalize_url(u) for u in raw}
        kept = {normalize_url(u) for u in raw if keep(u)} if keep else {normalize_url(u) for u in raw}
        union |= kept
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        newest = mtime if newest is None else max(newest, mtime)
        contributions.append((len(kept), mtime, path))

    # Flags come from the harvests that MATERIALLY built the denominator, not from any file
    # ever written, and not from the single biggest one either.
    #
    # "Any file" is far too noisy: one truncated probe from months ago permanently brands a
    # source that has since been crawled in full (21 flagged vs 17 on this tree, and svn_gov
    # would be branded off a 20-link page-1 probe against a 36,171-link union). "Only the
    # biggest" is too lenient: the biggest is usually the run's `<id>_links.txt`, which
    # carried no sidecar before one was added, so a truncation recorded by a nearly-as-large
    # probe would vanish.
    #
    # So the test is scale-relative — a harvest counts if it is at least half the size of the
    # largest one. Union-relative would fail a source assembled from several partial
    # harvests, where no single file reaches half of what they collectively know.
    stopped_early = capped = False
    if contributions:
        threshold = FLAG_CONTRIBUTION * max(n for n, _, _ in contributions)
        for n_kept, _, path in contributions:
            if n_kept < threshold:
                continue
            meta = _read_listing_meta(path)
            stopped_early = stopped_early or bool(meta.get("stopped_early"))
            capped = capped or str(meta.get("stop_reason") or "") in CAPPED_STOP_REASONS

    # A probe run WITHOUT --spread harvests page 1 of the first start_url only, and is the
    # one branch whose report carries no `mode`. If that is all we have, the count is a floor
    # by two orders of magnitude — but only say so on evidence, so a probe whose JSON is
    # missing entirely counts for nothing either way.
    probe_metas = [_read_listing_meta(p) for k, p in files if k == "probe"]
    probe_metas = [m for m in probe_metas if m]
    page1_only = (not (kinds & {"run", "run_snapshot"})
                  and bool(probe_metas)
                  and not any(m.get("mode") for m in probe_metas))

    return LinkUniverse(
        urls=frozenset(union),
        n_dropped_by_pattern=len(raw_union) - len(union),
        unfiltered=keep is None,
        n_files=len(files),
        kinds=frozenset(kinds),
        newest=newest,
        stopped_early=stopped_early,
        capped=capped,
        page1_only=page1_only,
    )


def discover_sources(out_root: Path) -> dict[str, Path]:
    """Every source id that has a link list anywhere under `out_root`, mapped to its country
    directory — including sources with no CSV, which a CSV glob cannot see.

    Excluding `_wayback_extend_links.txt` is mandatory *here* (unlike in :data:`EXCLUDE_SUFFIXES`):
    the wildcard would otherwise strip only `_links.txt` and invent a source id
    `<X>_wayback_extend` that no recipe and no CSV corresponds to.
    """
    found: dict[str, Path] = {}
    for country_dir in sorted(p for p in Path(out_root).iterdir() if p.is_dir()):
        for path in country_dir.glob("*_links.txt"):
            if path.name.endswith(_DISCOVERY_EXCLUDE):
                continue
            found.setdefault(path.name[: -len("_links.txt")], country_dir)
        sample_dir = country_dir / "sample"
        if not sample_dir.is_dir():
            continue
        for path in sample_dir.glob("*_links_*.txt"):
            found.setdefault(re.sub(r"_links_\d{8}-\d{6}\.txt$", "", path.name), country_dir)
        for path in sample_dir.glob("*_probe_*.txt"):
            found.setdefault(re.sub(r"_probe_\d{8}-\d{6}\.txt$", "", path.name), country_dir)
    return found


def _load_recipes(recipes_dir: str) -> dict:
    from .recipe import load_recipe  # local: keeps `links` importable without the recipe stack

    out = {}
    for yml in sorted(Path(recipes_dir).glob("*.yml")):
        try:
            recipe = load_recipe(yml)
        except Exception as e:  # noqa: BLE001
            log.debug("links: skipping unreadable recipe %s :: %s", yml, e)
            continue
        out[recipe.source_id] = recipe
    return out


def audit(out_root: str = "data/scraped", recipes_dir: str = "recipes") -> list[dict]:
    """Per-source `union / kept / dropped`, worst drift first — the diagnostic behind the
    workbook's numbers. A big `dropped` means the recipe was tightened since those harvests;
    that is the mechanism working, not a fault."""
    recipes = _load_recipes(recipes_dir)
    rows = []
    for source_id, country_dir in sorted(discover_sources(Path(out_root)).items()):
        u = link_universe(country_dir, source_id, recipe=recipes.get(source_id))
        rows.append({
            "source_id": source_id,
            "country": country_dir.name,
            "n_files": u.n_files,
            "union_raw": u.n_unique + u.n_dropped_by_pattern,
            "n_unique_links": u.n_unique,
            "dropped_by_pattern": u.n_dropped_by_pattern,
            "links_status": u.status(),
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Audit the harvested-link universe per source")
    ap.add_argument("--out-root", default="data/scraped")
    ap.add_argument("--recipes-dir", default="recipes")
    ap.add_argument("--audit", action="store_true", help="print the per-source table (default)")
    ap.add_argument("--csv", help="also write the table to this path")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    rows = audit(args.out_root, args.recipes_dir)
    rows.sort(key=lambda r: -r["dropped_by_pattern"])
    print(f"{'source_id':42} {'files':>5} {'union':>8} {'kept':>8} {'dropped':>8}  status")
    for r in rows:
        print(f"{r['source_id'][:42]:42} {r['n_files']:5} {r['union_raw']:8} "
              f"{r['n_unique_links']:8} {r['dropped_by_pattern']:8}  {r['links_status']}")
    kept = sum(r["n_unique_links"] for r in rows)
    dropped = sum(r["dropped_by_pattern"] for r in rows)
    stale = sum(1 for r in rows if r["dropped_by_pattern"])
    print(f"\n{len(rows)} source(s) | {kept:,} unique links known | {dropped:,} dropped by the "
          f"current link_pattern across {stale} source(s) whose recipe has since been tightened")

    if args.csv:
        import csv as _csv

        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = _csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {args.csv}")


if __name__ == "__main__":
    main()
