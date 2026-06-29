# Writing a recipe

A recipe is a YAML file in `recipes/` that teaches the engine how one source exposes its speeches.
This guide is the field reference plus a worked example. It is written so that a person — or a coding
agent assigned a "new source" issue — can produce a working recipe by inspecting a site.

## How to inspect a site (the 10-minute version)

1. **Find a listing page** — the index that links to individual speeches (e.g. `.../discursos`,
   `.../press-releases`, `.../news`). Note its URL.
2. **Open one speech page** and, in browser dev tools, find stable selectors for the **title**, the
   **body text**, and the **date**. Prefer a class or id that clearly wraps the content
   (`div.article-body`) over brittle structural paths.
3. **Work out pagination.** Click to page 2 and watch the URL. A changing query string (`?start=40`,
   `?page=2`) is `query_param`. A changing path segment (`/discursos/2`) is `path`. A "load more" or
   "next" button with no URL change usually means the site is JavaScript-rendered (`renderer: js`) and
   `pagination: click`. If the live site is incomplete but the Internet Archive has the history, use
   `pagination: wayback` and point `start_urls` at a CDX prefix like `casarosada.gob.ar/informacion/discursos`
   (no trailing `*` — the engine prefix-matches; a literal `*` makes the CDX query return nothing).
4. **Check whether it needs JavaScript.** View source (not the rendered DOM). If the speech list is
   absent from the raw HTML, set `renderer: js`.
5. **Note the language** for date parsing (`date_languages: ["es"]`).

If a site is too irregular to pin down, run `fallback_generic.extract_generic` on a couple of pages to
get a draft, then tighten it into real selectors.

**Watch for listings that only show recent items.** Some sites render only the latest ~N items and quietly
ignore `?page=`, so a paginated crawl looks clean but stops a few weeks back. If you suspect this (or just
want the full history), check the site's **sitemap** — `/<root>/sitemap.xml` and the entries in
`/robots.txt`. A sitemap usually lists every article URL going back years; use `pagination.type: sitemap`
with `sitemap_urls`, and keep your `listing.link_pattern` to filter it to speeches.

> ⚠️ **Wayback is a fallback, never a replacement.** Use `pagination: wayback` *only*
> to reach speeches from **before** the live site's coverage. **Never convert or edit a
> working live recipe to wayback** — add a *separate* `<id>_wayback.yml` and bound it with
> `wayback_to` at the live recipe's earliest date. The live site gives clean, complete,
> structured data; archive captures are lossy and inconsistent across years, so scraping the
> modern era from the archive degrades quality and breaks `doc_id` continuity.

A Wayback recipe is **recipe-only** — the engine already handles the Internet-Archive CDX listing,
the polite retrying fetch, and dropping the listing/index captures generically, for *any* country.
Your job is entirely in the YAML: point `start_urls` at the CDX prefix (the listing path, **no trailing
`*`** — the engine prefix-matches), set a **tight `link_pattern`** that selects speech URLs and excludes
index / section / bio pages (usually by requiring a numeric id, e.g. `/discursos/\d+[^/]*$`), choose
`title`/`text`/`date` selectors that match the *archived* layout (older captures often fall back to the
generic text extractor, which the engine applies automatically), and bound the era with `wayback_to`.
**Do not modify `leaderspeech/text_scraper/*` for a new source** — per-site variation belongs in the
recipe. Copy [`recipes/arg_casarosada_wayback.yml`](../recipes/arg_casarosada_wayback.yml) as a template.

## JSON / search-API sources (`type: api`)

Some sites serve **only page chrome** as HTML — the speech list is loaded client-side from a JSON
endpoint. The tell: `probe` reports **0 links in both `static` and `js`**, and the page's network tab
(DevTools → Network → Fetch/XHR) shows a request to something like
`…/_api/search/query?querytext=…` (SharePoint "search web-part") or a REST/JSON list. These are common
on government **SharePoint** sites behind a WAF (Colombia's `presidencia.gov.co` is the exemplar).

To author an `api` recipe:

1. **Capture the endpoint.** In DevTools → Network → Fetch/XHR, reload the listing and find the request
   that returns the results as JSON. Copy its full URL (with `querytext`, `rowlimit`, etc.) — that goes in
   `start_urls[0]`. Note the response shape (right-click → copy response).
2. **Map the JSON.** `pagination.api.results_path` is the dotted path to the array of result rows.
   `url_field`/`title_field`/`date_field` are dotted paths within a row. **SharePoint** wraps each row's
   fields in a `Cells.results` list of `{Key, Value}` dicts — set `cells_path: Cells.results` and then the
   `*_field` names are matched against cell **keys** (`Path`, `Title`, `Write`).
3. **Paginate** with the shared knobs: `param` is the offset/page query param (SharePoint uses `startRow`),
   `step` the page size (match `rowlimit`), `max_pages` a cap. Harvesting stops when a page returns no new
   rows. Omit `param` for an endpoint that returns everything in one request.
4. **Headers.** The engine sends browser-like `User-Agent`/`Accept`/`Accept-Language` by default (this is
   what clears the WAF for the per-speech page fetch too). SharePoint usually also needs a precise OData
   `Accept` on the JSON call — set it under `pagination.api.headers`.
5. **Selectors still apply.** Each result's URL is then fetched and run through your `title`/`text`/`date`
   selectors as usual; any field the page misses is **filled from the JSON** (SharePoint's `Write` date is
   reliable when a page date selector isn't). If the JSON itself carries the full body, set `text_field`
   and the page fetch is skipped.

```yaml
source_id: col_presidencia
country: Colombia
source_language: Spanish
start_urls:
  # the JSON the page's JS calls — captured from DevTools (querytext/rowlimit included)
  - "https://www.presidencia.gov.co/_api/search/query?querytext='discurso'&rowlimit=50&clienttype='Custom'"
renderer: static

listing:
  link_pattern: "/prensa/"          # keep results to speech pages, drop other hits

pagination:
  type: api
  param: startRow                    # SharePoint offset param
  start: 0
  step: 50                           # = rowlimit
  max_pages: 200
  api:
    results_path: d.query.PrimaryQueryResult.RelevanceResults.Table.Rows.results
    cells_path: Cells.results        # SharePoint Key/Value cells
    url_field: Path
    title_field: Title
    date_field: Write
    headers:
      Accept: "application/json;odata=nometadata"

title: { selectors: ["h1", ".titulo", "title"] }
text:  { selectors: [".article-body", ".cuerpo", "article", "main"] }
date:  { selectors: ["time", ".fecha"] }
position: president
date_languages: ["es"]
```

## RSS/Atom feeds (`type: feed`)

A lighter-weight option when a source publishes an RSS or Atom feed. Point `start_urls` at the feed URL(s);
the engine reads `link`/`title`/`pubDate` (RSS) or `link[href]`/`title`/`updated` (Atom) and, by default,
the body (`content:encoded`/`description` or `content`/`summary`). Filter to speeches with
`listing.link_pattern`. If the feed carries the full text (`use_content: true`, the default), the
per-speech page fetch is skipped; set `use_content: false` to force a page fetch when the feed only has a
summary. Some feeds paginate (e.g. WordPress `?paged=N`) — use the shared `param`/`start`/`step` knobs.

```yaml
source_id: example_feed
country: Mexico
source_language: Spanish
start_urls:
  - https://example.gob.mx/discursos/feed
listing:
  link_pattern: "/discurso/"
pagination:
  type: feed
  feed:
    use_content: true
title: { selectors: ["h1"] }
text:  { selectors: ["article", ".entry-content"] }
date:  { selectors: ["time"] }
position: president
date_languages: ["es"]
```

## Field reference

| Key | Required | Notes |
|-----|----------|-------|
| `source_id` | yes | Short slug, e.g. `arg_casarosada`. Names the output CSV and links to `master_sources.xlsx`. |
| `country` | yes | Country name as in `pycountry` (e.g. `United States` — used to derive ISO codes and the `doc_id` prefix). |
| `iso3n` | no | Auto-filled from `country` if omitted. |
| `source_language` | no | Default `English`. Non-English text routes to the `*_originlanguage` columns. |
| `dataset` | no | Default `LeaderSpeech`. Leave as-is for newly scraped data. |
| `start_urls` | yes | One or more listing-page URLs (or CDX prefixes for `wayback` recipes). |
| `renderer` | no | `static` (default) or `js`. |
| `verify_ssl` | no | Default `true`. Set `false` for sites with a broken/incomplete TLS cert chain (common on older gov sites) — symptom: a `CERTIFICATE_VERIFY_FAILED` error. |
| `user_agent` | no | Override the default honest bot `User-Agent` (used for the page fetch and the api/feed clients). Only needed for a WAF that hard-blocks the bot UA — symptom: `0 links` / empty pages from the bot UA but real content from a browser UA. Use sparingly; the honest UA is the default. |
| `listing.link_selector` | one of these | CSS selector for the `<a>` elements linking to speeches. |
| `listing.link_pattern` | one of these | Regex an href must match (e.g. `"/discursos/\\d+"`). Use with or instead of `link_selector`. |
| `pagination.type` | no | `query_param`, `path`, `click`, `url_list`, `sitemap`, `wayback`, `api`, `feed`, or `none` (default). |
| `pagination.param` | for query_param | Query parameter name (`start`, `page`). |
| `pagination.start` / `step` | no | First index/offset and the increment between pages (defaults `0` / `1`). |
| `pagination.path_format` | for path | Suffix template appended to `start_url`, with a `{n}` placeholder for the page index. Default (unset) appends `/{n}` (e.g. `/discursos/2`). Use it when the pager isn't a bare number — e.g. `path_format: "P{n}"` with `start: 0, step: 20` yields `…/speeches/P0`, `…/speeches/P20`, `…/speeches/P40` (president.ie). Supports format specs like `{n:03d}` for zero-padding. |
| `pagination.max_pages` | no | Safety cap. Omit to stop automatically when a page yields no new links. |
| `pagination.next_selector` | for click | CSS selector of the "next" button. |
| `pagination.url_list` | for url_list | Explicit list of listing URLs. |
| `pagination.sitemap_urls` | for sitemap | Sitemap `.xml` URL(s). The full URL list comes from the sitemap (a sitemap *index* is followed into its children), filtered by `listing.link_pattern`. Best for full history — see the tip below. |
| `pagination.wayback_limit` / `wayback_match_type` / `wayback_collapse` / `wayback_delay` / `wayback_from` / `wayback_to` | for wayback | CDX/query pacing knobs. `wayback_limit` caps captures per query; `wayback_delay` controls the pause before each archived fetch; the defaults are `prefix`/`urlkey`, `5s`, and no date bounds. |
| `pagination.api.results_path` | for api | Dotted path to the array of result rows in the JSON (e.g. `d.query.PrimaryQueryResult.RelevanceResults.Table.Rows.results`). |
| `pagination.api.url_field` | for api | Dotted path to a row's speech URL — or, in cells mode, the cell **key** naming it (e.g. `Path`). |
| `pagination.api.title_field` / `date_field` / `text_field` / `speaker_field` | no | Same as `url_field` for the other fields. `text_field` lets the JSON carry the full body, skipping the per-speech page fetch. Dates are parsed as standard (ISO/RFC) formats — `date_languages` is **not** applied here. |
| `pagination.api.cells_path` | no | SharePoint cells mode: dotted path within a row to its `{Key, Value}` cell array (e.g. `Cells.results`). When set, the `*_field` names match cell **keys** instead of being row paths. |
| `pagination.api.cell_key` / `cell_value` | no | Attribute names in a cell dict (defaults `Key` / `Value`). |
| `pagination.api.headers` | no | Per-request header overrides for the JSON call — e.g. `Accept: application/json;odata=nometadata` for SharePoint. Browser-like `User-Agent`/`Accept-Language` are sent by default. |
| `pagination.api.delay` | no | Courtesy pause (seconds) between API page requests (default `0`). |
| `pagination.feed.format` | no | `auto` (default), `rss`, or `atom`. |
| `pagination.feed.use_content` | no | Default `true` — populate `text` from the feed body (RSS `content:encoded`/`description`, Atom `content`/`summary`). Set `false` to force a per-speech page fetch. |
| `title` / `text` / `date` | yes | Each is `{ selectors: [...] }`, an ordered fallback chain. First match wins. |
| `speaker` / `context` | no | Same shape as above. |
| `<field>.attr` | no | Read this attribute instead of element text (e.g. `attr: datetime` on a `<time>` tag). |
| `<field>.regex` | no | Pull a substring out of the matched value (e.g. isolate a date from a label). |
| `position` | no | Fixed office when the source is single-office (`president`, `prime minister`). |
| `speaker_default` | no | Fixed speaker when the source is single-leader. |
| `date_languages` | no | Language hints for `dateparser` (e.g. `["es"]`, `["fr"]`). |
| `politeness.delay_range` / `pause_every` / `pause_seconds` / `retries` / `backoff` | no | Pacing. Defaults: no per-request delay (`[0, 0]`), a `5`s breather every `50` requests, `3` retries, `5`s backoff. Raise these for a server that pushes back. |
| `notes` | no | Anything a future maintainer should know. |

## Worked example

```yaml
source_id: mex_amlo
country: Mexico
source_language: Spanish
start_urls:
  - https://www.gob.mx/presidencia/es/archivo/articulos
renderer: static

listing:
  link_selector: "a"
  link_pattern: "/articulos/"

pagination:
  type: query_param
  param: page
  start: 1
  step: 1
  max_pages: 50

title: { selectors: ["h1.article-title", "h1", "title"] }
text:  { selectors: ["div.article-body", "main article", ".bottom-buffer"] }
date:  { selectors: ["time", ".article-date"], attr: datetime }
speaker: { selectors: [".pull-left h2"] }
position: president
date_languages: ["es"]
notes: >
  gob.mx hosts many offices under one CMS; the link_pattern keeps us to article pages.
```

## Test your recipe before committing

```bash
# Validate the YAML against the schema (this is what CI runs):
python -c "from leaderspeech.text_scraper.recipe import load_recipe; print(load_recipe('recipes/mex_amlo.yml').source_id)"

# Do a tiny live run — one or two pages, a handful of speeches:
python -m leaderspeech.text_scraper.run --recipe recipes/mex_amlo.yml --max-pages 1 --limit 5
```

Open the resulting `data/scraped/<Country>/<source_id>.csv` and check that `title`, `text`, and `date`
are populated and clean. Spot-check the speaker and date against the
`leader_tenure_final` key (does the named leader plausibly hold office on that date in that country?).

If something looks wrong, the run's summary, log, and `_errors.csv` tell you what and where — see
[`debugging.md`](debugging.md) for reading them and the fix-and-resume loop.

## The scrape index (for merging)

Output CSVs are named after the *site* (`arg_casarosada.csv`), which makes a folder of them hard to read
and to merge. Every `run` rebuilds **`data/scraped/scraped_progress_log.xlsx`** — one row per source CSV
with its country, website, file path, pagination type, date coverage, doc_id range, and a bad/missing-date
count. Rebuild it on demand with `python -m leaderspeech.text_scraper.index`. A merge step reads the index's
`csv_file` column and concatenates every file it lists. It is a **regenerable, machine-owned** artifact —
distinct from the researcher-curated `data/sources/master_sources.xlsx`, which agents must never touch.

## Good-citizen reminders

- Pacing is light by default (a breather every 50 requests). If a host starts erroring or rate-limiting,
  raise `pause_seconds` or set a `delay_range` in the recipe rather than pushing through.
- Cap your test runs (`--max-pages`, `--limit`). Only do a full crawl once the recipe is validated.
- If a source is dead, reach for the Wayback fallback (`leaderspeech.text_scraper.wayback`) rather than
  scraping aggressively around the gaps.
