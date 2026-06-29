"""Seed data/sources/master_sources.xlsx — the curated, committed source list.

This produces a *starting point* only. master_sources.xlsx is maintained by hand
afterward; re-running this would overwrite it, so run it once (or merge by hand).

Inputs (kept local, not committed):
    ../../data/sources/urls_deanscrape.txt          (88 presidential sites)
    ../../data/sources/LeadersSpeeches_Africa.xlsx   (RA-collected African sources)
"""

from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pycountry

REPO = Path(__file__).resolve().parents[1]
# the raw sub-lists live in the working project's data/sources (one level above the repo)
WORK_SOURCES = REPO.parent.parent / "data" / "sources"
OUT = REPO / "data" / "sources" / "master_sources.xlsx"

COLUMNS = [
    "source_id", "country", "region", "iso3n", "source_name", "source_url",
    "source_type", "renderer", "leaders_covered", "date_start", "date_end",
    "language", "content_format", "recipe_status", "last_checked", "notes",
]

# ccTLD -> country exceptions where the final label isn't an ISO alpha-2 code
TLD_FIXES = {"gov": "US", "uk": "GB"}


def host_of(url: str) -> str:
    u = url.strip()
    if "//" not in u:
        u = "http://" + u
    return urlparse(u).netloc.lower().lstrip("www.")


def country_from_url(url: str):
    host = host_of(url)
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    alpha2 = TLD_FIXES.get(tld, tld.upper())
    try:
        c = pycountry.countries.lookup(alpha2)
        return c.name, c.alpha_3, int(c.numeric)
    except Exception:
        return "", "", ""


def slug(url: str, alpha3: str) -> str:
    host = host_of(url)
    label = host.split(".")[0] if host else "site"
    return f"{(alpha3 or 'xxx').lower()}_{label}"


def deanscrape_rows() -> list[dict]:
    rows = []
    path = WORK_SOURCES / "urls_deanscrape.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if not url:
            continue
        name, a3, n = country_from_url(url)
        rows.append({
            "source_id": slug(url, a3), "country": name, "region": "",
            "iso3n": n, "source_name": host_of(url), "source_url": url,
            "source_type": "official_gov", "renderer": "unknown",
            "recipe_status": "none", "notes": "auto-seeded from urls_deanscrape.txt",
        })
    return rows


def africa_rows() -> list[dict]:
    path = WORK_SOURCES / "LeadersSpeeches_Africa.xlsx"
    if not path.exists():
        return []
    df = pd.read_excel(path)
    df = df[df["link"].astype(str).str.startswith("http")]
    rows = []
    for host, grp in df.groupby(df["link"].map(host_of)):
        country = grp["country"].mode().iat[0] if not grp["country"].mode().empty else ""
        a3 = ""
        try:
            a3 = pycountry.countries.lookup(country).alpha_3
        except Exception:
            pass
        speakers = sorted({s for s in grp["speaker"].dropna().astype(str)})
        types = sorted({t for t in grp["source_type"].dropna().astype(str)})
        rows.append({
            "source_id": slug("http://" + host, a3), "country": country,
            "region": "Africa", "iso3n": "", "source_name": host,
            "source_url": "http://" + host, "source_type": "; ".join(types)[:60],
            "renderer": "unknown",
            "leaders_covered": "; ".join(speakers)[:120],
            "recipe_status": "none",
            "notes": f"from LeadersSpeeches_Africa.xlsx ({len(grp)} link(s))",
        })
    return rows


# the milestone recipes we actually built + validated this round
MILESTONE = {
    "arg_casarosada": dict(
        region="South America", renderer="static", language="Spanish",
        leaders_covered="Milei, Fernández, Macri, Kirchner", content_format="fulltext",
        recipe_status="validated", last_checked="2026-06-27",
        notes="recipe: recipes/arg_casarosada.yml — validated live"),
    "arg_casarosada_wayback": dict(
        region="South America", renderer="static", language="Spanish",
        leaders_covered="Kirchner, Fernández", content_format="fulltext",
        recipe_status="validated", last_checked="2026-06-27",
        notes="recipe: recipes/arg_casarosada_wayback.yml — archived history"),
    "mex_presidencia": dict(
        region="North America", renderer="static", language="Spanish",
        leaders_covered="Sheinbaum, López Obrador (paging back)", content_format="fulltext",
        recipe_status="validated", last_checked="2026-06-27",
        notes="recipe: recipes/mex_presidencia.yml — validated live"),
    "fra_elysee": dict(
        region="Europe", renderer="static", language="French",
        leaders_covered="Macron", content_format="fulltext",
        recipe_status="validated", last_checked="2026-06-27",
        notes="recipe: recipes/fra_elysee.yml — validated live (server-rendered, static)"),
}


def main():
    rows = {r["source_id"]: r for r in deanscrape_rows()}
    for r in africa_rows():
        rows.setdefault(r["source_id"], r)
    # ensure milestone source_ids exist, then enrich
    rows.setdefault("mex_presidencia", {
        "source_id": "mex_presidencia", "country": "Mexico", "iso3n": 484,
        "source_name": "gob.mx/presidencia",
        "source_url": "https://www.gob.mx/presidencia/es/archivo/articulos",
        "source_type": "official_gov"})
    rows.setdefault("fra_elysee", {
        "source_id": "fra_elysee", "country": "France", "iso3n": 250,
        "source_name": "elysee.fr",
        "source_url": "https://www.elysee.fr/toutes-les-actualites",
        "source_type": "official_gov"})
    for sid, extra in MILESTONE.items():
        rows.setdefault(sid, {"source_id": sid})
        rows[sid].update(extra)

    df = pd.DataFrame(list(rows.values()))
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[COLUMNS].fillna("").sort_values(["recipe_status", "country"],
                                            ascending=[True, True])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(OUT, index=False)
    print(f"Wrote {len(df)} sources to {OUT}")
    print(df["recipe_status"].value_counts().to_dict())


if __name__ == "__main__":
    main()
