"""WAF / block-page detection.

Some sites (Cloudflare and other WAFs) return a **block or challenge page with HTTP
200** instead of an error status. Without a guard the engine accepts that page as the
speech body: it writes a ~460-char *"Sorry, you have been blocked…"* document as a
speech, marks the URL ``seen`` (so ``--retry-failed`` never re-does it), and the junk is
only caught much later by the cleaner. Net effect: wasted scrape+clean, polluted CSVs,
and the real failure hidden behind a "successful" run (issue #65).

:func:`looks_like_block_page` recognizes the common WAF/challenge signatures so the
fetch path can treat a matched page as a **fetch failure** — the same code path as an
empty/failed fetch, so the retry/backoff + circuit-breaker fire and the URL lands in
``failed_urls`` (retryable via ``--retry-failed``) and ``_errors.csv`` instead of being
written as a row.

Design (kept deliberately conservative to avoid false positives on a genuine long
speech that merely mentions "cloudflare"):

* **Cheap first pass** — scan the raw HTML for any signature substring. The overwhelming
  majority of pages (real speeches) carry none, so they return immediately with no HTML
  parse.
* **Length gate** — only if a signature IS present do we parse the page and measure its
  VISIBLE text. A block page is tiny; a real speech is long. A page whose visible text
  exceeds ``max_text_chars`` is never treated as a block, so a long speech quoting a
  signature phrase cannot trip it.

Per-recipe overrides: ``block_page: false`` disables the guard for the odd site whose
legitimate content matches; ``block_page_patterns`` adds extra signatures.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

# A block page is almost always short. Only pages whose VISIBLE text is under this many
# characters are eligible to be flagged — a genuine speech is far longer, and this is the
# main guard against false positives. (isr_pmo's Cloudflare block page is ~460 chars.)
BLOCK_MAX_TEXT_CHARS = 3000

# Case-insensitive signatures, matched against the raw HTML first (cheap) and confirmed
# only on a short page. Kept to phrases distinctive of a WAF/challenge/denial interstitial
# rather than bare words, but the length gate is what actually prevents false positives.
BLOCK_SIGNATURES = (
    # Cloudflare hard denials (CF-1020 "Attention Required", "you have been blocked")
    "you have been blocked",
    "attention required",
    "cloudflare",
    "cf-error-details",
    # JS challenge interstitials (also handled live by fetch._settle_challenge; caught here
    # when they never clear — e.g. under the static renderer, or a js fetch that timed out)
    "just a moment",
    "checking your browser before accessing",
    "verify you are human",
    "verifying you are human",
    "please enable javascript and cookies to continue",
    "please turn javascript on and reload the page",
    "please stand by, while we are checking your browser",
    # Other WAFs / access-denied pages served as 200
    "access denied",
    "request unsuccessful. incapsula incident",
    "the requested url was rejected",          # F5 BIG-IP ASM
    "this website is using a security service to protect itself",
)


class BlockPageError(Exception):
    """Raised when a fetched page is a WAF/block/challenge page served with HTTP 200.

    A subclass of ``Exception`` so the Fetcher's retry loop catches it (retries/backoff
    fire, which clears a transient rate-limit block), and so an exhausted retry surfaces
    it as an ordinary fetch failure to the scrape loop.
    """


def looks_like_block_page(html, extra_patterns=None,
                          max_text_chars: int = BLOCK_MAX_TEXT_CHARS) -> bool:
    """True if ``html`` looks like a WAF/block/challenge page rather than real content.

    ``extra_patterns`` adds recipe-supplied signatures. ``max_text_chars`` bounds how much
    visible text a page may have and still be flagged (see module docstring). See
    :data:`BLOCK_SIGNATURES` for the built-in list.
    """
    if not html or not isinstance(html, str):
        return False
    patterns = BLOCK_SIGNATURES + tuple(p.lower() for p in (extra_patterns or ()))
    low = html.lower()
    # Cheap path: no signature anywhere in the markup -> definitely not a block, no parse.
    if not any(p in low for p in patterns):
        return False
    # A signature IS present. Confirm the page is SHORT (blocks are tiny); a long speech
    # that quotes a signature is not a block.
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return len(text) <= max_text_chars
