"""issue #65 — WAF/block-page detection.

A Cloudflare/WAF block page served with HTTP 200 must be recognised as a block (so the
fetch path treats it as a failure) while a genuine speech — even a short one, even one
that quotes "cloudflare" — must not be.
"""

from leaderspeech.text_scraper.block import (BLOCK_MAX_TEXT_CHARS, BlockPageError,
                                             looks_like_block_page)

# A trimmed but faithful copy of gov.il's Cloudflare "you have been blocked" page — the
# isr_pmo motivating case (~460 chars of visible text, HTTP 200).
CLOUDFLARE_BLOCK = """<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head>
<body><h1>Sorry, you have been blocked</h1>
<h2>You are unable to access gov.il</h2>
<p>This website is using a security service to protect itself from online attacks. The
action you just performed triggered the security solution. There are several actions that
could trigger this block including submitting a certain word or phrase, a SQL command or
malformed data.</p>
<p>Cloudflare Ray ID: 8b2c &bull; Performance &amp; security by Cloudflare</p></body></html>"""

JUST_A_MOMENT = """<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body><div>Checking your browser before accessing the site.</div>
<div>Please enable JavaScript and cookies to continue.</div></body></html>"""

# A real (short) speech page: no block signatures, real body text.
REAL_SPEECH = """<html><head><title>Remarks by the President</title></head><body>
<article><h1>Remarks on the Economy</h1>
<p>Thank you all for being here today. Our nation has made real progress this year, and I
want to speak plainly about the work still ahead of us on jobs, on trade, and on the
security of every family.</p></article></body></html>"""


def test_cloudflare_block_page_is_detected():
    assert looks_like_block_page(CLOUDFLARE_BLOCK) is True


def test_just_a_moment_interstitial_is_detected():
    assert looks_like_block_page(JUST_A_MOMENT) is True


def test_real_short_speech_is_not_a_block():
    assert looks_like_block_page(REAL_SPEECH) is False


def test_long_speech_mentioning_cloudflare_is_not_a_block():
    """The length gate: a genuine long speech that happens to say "cloudflare" (or any
    signature) must not trip the guard."""
    body = "<p>" + ("We discussed cybersecurity, including Cloudflare and other vendors. "
                     * 200) + "</p>"
    html = f"<html><body><article>{body}</article></body></html>"
    assert len(html) > BLOCK_MAX_TEXT_CHARS
    assert looks_like_block_page(html) is False


def test_empty_or_non_string_is_not_a_block():
    assert looks_like_block_page("") is False
    assert looks_like_block_page(None) is False
    assert looks_like_block_page(b"bytes") is False


def test_extra_patterns_add_site_specific_signatures():
    page = "<html><body><h1>Zugriff verweigert</h1><p>Bitte versuchen Sie es später.</p></body></html>"
    assert looks_like_block_page(page) is False                       # not a built-in signature
    assert looks_like_block_page(page, extra_patterns=["zugriff verweigert"]) is True


def test_block_page_error_is_an_exception():
    # so the Fetcher retry loop (except Exception) catches it
    assert issubclass(BlockPageError, Exception)


# --- regression: the Cloudflare ANALYTICS BEACON is not a block page --------------------
# Until 2026-07-28 the bare word "cloudflare" was a block signature, so any page merely
# loading a Cloudflare asset fell through to the length gate alone. Short legitimate pages
# (listing pages run 2-3k visible chars) were then rejected at random, silently truncating
# harvests: presidency.gov.mv's speech pager died at whichever page had shorter headlines.

CF_BEACON = (
    '<html><head><script type="module" '
    'src="https://static.cloudflareinsights.com/beacon.min.js/v4513226cdae34746"></script>'
    "</head><body><h1>President's Speeches</h1>"
    "<a href='/Press/Article/36811'>Address at the opening ceremony</a>"
    "<a href='/Press/Article/36602'>Remarks at the national day event</a>"
    "</body></html>"
)


def test_cloudflare_analytics_beacon_is_not_a_block_page():
    """A short listing page that loads Cloudflare's RUM beacon must pass, however short."""
    assert not looks_like_block_page(CF_BEACON)


def test_cloudflare_cdn_asset_is_not_a_block_page():
    html = ("<html><head><link rel='stylesheet' "
            "href='https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css'>"
            "</head><body><p>Short page.</p></body></html>")
    assert not looks_like_block_page(html)


def test_real_cloudflare_block_pages_are_still_caught():
    for html in (
        "<html><body><h1>Attention Required!</h1><p>Sorry, you have been blocked</p></body></html>",
        "<html><body><div class='cf-error-details'>Error 1020</div></body></html>",
        "<html><body><p>Cloudflare Ray ID: 8f2b1c</p><p>Access denied</p></body></html>",
        "<html><body><p>Performance &amp; security by Cloudflare</p></body></html>",
    ):
        assert looks_like_block_page(html), html[:60]
