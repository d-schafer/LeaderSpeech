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
   `pagination: click`.
4. **Check whether it needs JavaScript.** View source (not the rendered DOM). If the speech list is
   absent from the raw HTML, set `renderer: js`.
5. **Note the language** for date parsing (`date_languages: ["es"]`).

If a site is too irregular to pin down, run `fallback_generic.extract_generic` on a couple of pages to
get a draft, then tighten it into real selectors.

## Field reference

| Key | Required | Notes |
|-----|----------|-------|
| `source_id` | yes | Short slug, e.g. `arg_casarosada`. Names the output CSV and links to `master_sources.xlsx`. |
| `country` | yes | Country name as in `pycountry` (e.g. `United States` — used to derive ISO codes and the `doc_id` prefix). |
| `iso3n` | no | Auto-filled from `country` if omitted. |
| `source_language` | no | Default `English`. Non-English text routes to the `*_originlanguage` columns. |
| `dataset` | no | Default `LeaderSpeech`. Leave as-is for newly scraped data. |
| `start_urls` | yes | One or more listing-page URLs. |
| `renderer` | no | `static` (default) or `js`. |
| `listing.link_selector` | one of these | CSS selector for the `<a>` elements linking to speeches. |
| `listing.link_pattern` | one of these | Regex an href must match (e.g. `"/discursos/\\d+"`). Use with or instead of `link_selector`. |
| `pagination.type` | no | `query_param`, `path`, `click`, `url_list`, or `none` (default). |
| `pagination.param` | for query_param | Query parameter name (`start`, `page`). |
| `pagination.start` / `step` | no | First index/offset and the increment between pages (defaults `0` / `1`). |
| `pagination.max_pages` | no | Safety cap. Omit to stop automatically when a page yields no new links. |
| `pagination.next_selector` | for click | CSS selector of the "next" button. |
| `pagination.url_list` | for url_list | Explicit list of listing URLs. |
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

## Good-citizen reminders

- Pacing is light by default (a breather every 50 requests). If a host starts erroring or rate-limiting,
  raise `pause_seconds` or set a `delay_range` in the recipe rather than pushing through.
- Cap your test runs (`--max-pages`, `--limit`). Only do a full crawl once the recipe is validated.
- If a source is dead, reach for the Wayback fallback (`leaderspeech.text_scraper.wayback`) rather than
  scraping aggressively around the gaps.
