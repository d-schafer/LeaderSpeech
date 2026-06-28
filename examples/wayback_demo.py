"""Wayback fallback demo.

Many sites in data/sources have gone offline or been redesigned beyond reach.
This shows the intended fallback: ask the Internet Archive's CDX index what it
has, then fetch a capture and run it through the same extraction the live engine
uses. Run it against a dead presidential site:

    python examples/wayback_demo.py http://www.presidency.gov.sd

Keep this gentle — the Archive is a public good. Defaults already pause between
requests and cap results.
"""

import os
import sys

# allow running directly (`python examples/wayback_demo.py`) without installing
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from leaderspeech.text_scraper import wayback
from leaderspeech.text_scraper.fallback_generic import extract_generic


def main(target: str):
    print(f"Querying the CDX index for archived pages under {target} ...")
    snaps = wayback.list_snapshots(
        target, match_type="domain", collapse="urlkey", limit=25
    )
    ok = [s for s in snaps if s.get("statuscode") == "200"]
    print(f"  {len(snaps)} captures, {len(ok)} with HTTP 200.")
    if not ok:
        print("  No usable captures — try a broader URL or a different site.")
        return

    entry = ok[0]
    print(f"\nFetching {wayback.snapshot_url(entry)}")
    html = wayback.fetch_snapshot(entry)
    record = extract_generic(html, url=entry["original"])
    print("  title:", record["title"][:80])
    print("  date :", record["date"])
    print("  text :", record["text"][:200].replace("\n", " "))
    print(
        "\nIn a real run you'd page through CDX captures of the speeches section and "
        "feed each through a recipe (or extract_generic) into the standard schema."
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://www.presidency.gov.sd")
