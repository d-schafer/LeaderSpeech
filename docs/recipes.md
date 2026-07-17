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
   `pagination: click`. If the URL *does* change but carries a **signed or opaque token** you cannot
   compute (a TYPO3 `cHash`, a cursor, a session id) — the tell is that editing the page number by hand
   404s or silently re-serves page 1 — then the pager can only be *followed*, not synthesised: use
   `pagination: next_link` (see "Pagers you can't synthesise" below). If the live site is incomplete but the Internet Archive has the history, use
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

### Auto-continuing a live recipe into the archive (`wayback_extend`)

Instead of hand-writing a separate `<id>_wayback.yml`, a **live** recipe can opt in to continue into
the Internet Archive automatically once its live coverage runs out. After the normal crawl finishes,
the engine computes the **earliest date it just scraped for the source**, then harvests archived
captures *older* than that (bounded by `wayback_to = that date`, so live and archive don't overlap and
`doc_id` continuity holds), reusing this recipe's own selectors (plus the generic fallback for drifted
old layouts). Everything lands in the **same** output CSV / per-country `doc_id` counter / state file,
and any capture whose URL was already scraped live is deduped away.

Minimal form — reuse everything:

```yaml
# ...a normal live recipe...
wayback_extend: true
```

Or a block of overrides (all optional; each defaults to the live recipe):

```yaml
wayback_extend:
  prefix: casarosada.gob.ar/informacion/discursos   # CDX prefix; default = derived from start_urls[0]
  link_pattern: '/discursos/\d+[^/]*$'               # default = listing.link_pattern
  text: { selectors: ["#content-core", "article"] }  # selector overrides for the archived layout
  wayback_from: "20070101"                            # optional lower bound
  wayback_to: "20151210"                              # explicit cap; overrides the auto earliest-date floor
  wayback_delay: 5.0
```

You can also trigger it per-run without editing the recipe: `run --extend-wayback`.

**Check it before you run it.** Archived pages very often use an *older layout* than the live site —
which is exactly when the selector overrides above are needed, and exactly what you cannot see from a
live probe. `probe` samples the continuation with the same prefix, `link_pattern` and overrides the run
derives, and reports it under a `WAYBACK-EXTEND` heading with `ARCHIVED` per-page diagnostics:

```bash
# automatic when the recipe declares wayback_extend; --extend-wayback forces it for one that doesn't
python -m leaderspeech.text_scraper.probe --recipe recipes/arg_casarosada.yml --n 5

# a real run bounds the archive at the earliest date the LIVE crawl scraped — a value that only
# exists after that crawl. Before anything is scraped there is no floor, so the probe samples the
# WHOLE archive (it says so) and recent captures with the live layout dilute the sample. Aim it at
# the historical slice yourself:
python -m leaderspeech.text_scraper.probe --recipe recipes/arg_casarosada.yml --wayback-to 20151210
```

Once the source has been scraped, the probe picks the floor up from the existing CSV automatically.

> ⚠️ **Two honest limits.**
> 1. **Same host only.** `wayback_extend` reuses the live site's host+prefix. A source that moved its
>    older content to a **different domain** (US NARA `*whitehouse.archives.gov`, Korea
>    `webarchives.pa.go.kr`, Brazil `biblioteca.presidencia.gov.br`) is *not* reached by it — author a
>    dedicated archive-site recipe instead (see below).
> 2. **Prefix = the listing path by default.** The default CDX prefix is derived from `start_urls[0]`.
>    If a site's speeches don't live *under* its listing path (e.g. the listing is `/news/` but speeches
>    are `/remarks/2020/...`), set `wayback_extend.prefix` to the path the speeches actually sit under.

### Reaching earlier administrations: archive subdomains

Many governments **relocate a departing administration's content to a new domain** rather than keeping
it live. When that domain is a clean, static, frozen archive, a **dedicated live recipe there beats
Wayback** — the pages are complete and consistently structured, unlike lossy archive captures. Known
examples:

- **United States** — the White House moves each administration to a NARA subdomain:
  `obamawhitehouse.archives.gov`, `trumpwhitehouse.archives.gov`, `bidenwhitehouse.archives.gov`.
- **South Korea** — the Presidential Archives freeze each past Cheongwadae site under
  `webarchives.pa.go.kr/<Nth>/...` (e.g. `19th` = Moon Jae-in), with an English speeches board.
- **Brazil** — the Biblioteca da Presidência (`biblioteca.presidencia.gov.br/presidencia/ex-presidentes/…`)
  archives ex-presidents' speeches (FHC, Lula, Dilma, Temer, Bolsonaro).

Author these as ordinary live recipes (usually `renderer: static`, `query_param`/`path` pagination),
one per administration where the URL scheme differs — not as `wayback_extend`, which stays on the
*live* host.

## Filtering by the PAGE, not the URL (`keep_if`)

`listing.link_pattern` is a regex over the **URL**, and it should stay your first choice: it
costs nothing (the page is never fetched). But some sites categorise content **on the page
only** — every article is a bare numeric permalink like `/news/contents/details/12345`, shared
by the leader's speeches and by every ministry press release on the site. No URL regex can
separate those. `keep_if` is a predicate over the **fetched page**, applied after extraction
and before the row is written, so it works the same for `wayback`, `api`/`feed` and ordinary
listings:

```yaml
keep_if:
  # The article's own category element. Several selectors = alternatives (all are tried).
  selectors: ["div.panel-heading span.headtitle-2"]
  pattern: "ข่าวนายกรัฐมนตรี|คำกล่าวของนายกรัฐมนตรี"   # regex over their combined text
  # negate: true      # optional: DROP when it matches instead
```

This matters most for **`pagination: wayback`**, which never crawls a listing at all — it
enumerates CDX captures and treats each as a speech page — so an on-page category is the only
category signal an archive harvest has.

**Modes**

| Written as | Keeps a page when |
|---|---|
| `selectors` + `pattern` | the combined text of every matching element matches `pattern`. The usual shape. |
| `pattern` alone | the **whole document's** text matches (a PDF's extracted text when there's no DOM). Blunt — a passing mention of the leader counts. |
| `selectors` alone | any of them is present at all. |

**The trap: use the article's own category, not the site's nav.** A site-wide menu or footer
usually *lists every category on every page*, so `nav`/`.breadcrumb` often matches "PM
speeches" on a Ministry of Health press release and keeps the whole wire. Verify with a probe
that a page you want **dropped** is actually dropped — a `keep_if` that keeps everything is as
wrong as one that keeps nothing.

**Costs and failure modes**
- The page must be fetched before it can be judged, so a rejected page is a wasted fetch —
  bandwidth, not money, and far cheaper than letting the cleaner spend a per-speech GPT call
  to reject the same row.
- A selector that matches nothing means "no evidence" and **drops** the page. A mis-specified
  `keep_if` therefore empties a source *silently*, so `run` reports `filtered_out_this_run`
  (and shouts if it filtered out everything), and `probe` prints a `KEEP_IF` line with the
  kept/filtered counts. Probe before you run.
- Rejections are recorded in the state file's `filtered_urls` and never re-fetched (that's the
  point on a 4,000-capture archive). `--retry-failed` retries *failures*, not rejections — to
  re-open them after loosening a `keep_if`, delete that list from `data/state/<Country>.json`.
- **No DOM, no selectors:** for a PDF (`content_type: pdf`), or an `api`/`feed` source whose
  JSON carries the text so no page is fetched, a `selectors` predicate cannot be evaluated and
  is a **no-op** (the page is kept — silently rejecting a whole source is worse). Use the
  `pattern`-alone form to filter those.

## Pagers you can't synthesise (`type: next_link`)

Most pagers are *constructible*: you know page 2's URL because it is page 1's with a number
changed (`query_param`, `path`). Some are not — the URL carries a **signed or opaque token**:

- **TYPO3 `cHash`** (`?tx_news_pi1[currentPage]=2&cHash=8f3e…`) — an HMAC over the query params
  using the site's secret `encryptionKey`. You cannot compute it; requesting the param without a
  valid cHash returns **404**. This is common on European government sites.
- Cursor/continuation tokens, or a session id baked into the pager.

The tell: hand-editing the page number 404s or silently re-serves page 1. When that happens, the
only route is to **follow the site's own "next" link**, which is exactly what `next_link` does — it
fetches the listing, extracts links, reads `next_selector`'s `href`, and repeats over plain HTTP.

```yaml
pagination:
  type: next_link
  next_selector: "li.next a[data-nextlink]"   # the <a>, or a wrapper containing it
  max_pages: 300                               # safety cap; the chain self-terminates
```

It stops on: no next link, a next link pointing somewhere already visited (loop guard), `max_pages`,
or the probe's link cap. Unlike `query_param`/`path` it does **not** stop when a page yields no *new*
links — an interior page of duplicates shouldn't truncate the crawl; the absence of a next link is
the real terminator.

> **`next_link` vs `click`.** `click` is for JS sites where the next control changes the page *in
> place* with no URL change — it needs `renderer: js` and drives a real browser. `next_link` is for
> **static** sites where "next" is a server-rendered `<a href>`. Reach for `next_link` first: it is far
> faster (no browser) and it survives a site that *hides* its pager once its JS runs — Austria's
> `bundespraesident.at` does exactly that (the timeline script sets the paginator to `display:none`,
> and Playwright refuses to click a non-visible element, so `click` silently stops after page 1).
> See [`recipes/aut_bundespraesident.yml`](../recipes/aut_bundespraesident.yml).

## Several listing pages (`start_urls` + `type: none`), and how that differs from `url_list`

These two look similar and are easy to confuse:

| You have | Use |
|---|---|
| A known list of **speech** URLs | `pagination.type: url_list` + `pagination.url_list` — returned **verbatim** as the scrape targets. Not fetched as listings; `listing.link_pattern` is **not** applied. |
| A known list of **listing** pages | Put them all in `start_urls` with `pagination.type: none` — the engine fetches **each** one and extracts links from it. |

```yaml
# several listing pages -> start_urls + none
start_urls:
  - https://example.gov/speeches/2024
  - https://example.gov/speeches/2023
pagination:
  type: none
```

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

### POST endpoints, cross-host URLs, and list-index/quoted field paths

Three optional knobs (all default to the GET behavior above) extend `api` to SPA/gov
sites whose listing is a POST call, whose rows carry relative URLs to a *different* host,
or whose date sits at a list index or a spaced key:

* **`api.method: POST`** + **`api.body`** — send a POST with a fixed JSON body instead of
  a GET. Paginate by either (a) setting **`api.body_page_field`** (a dotted path into
  `body`) so the per-page offset — `start + page_idx*step` — is written *into the body*
  each request (for APIs paged inside the body, e.g. a Spring `pageRequest.page`), or (b)
  leaving `body_page_field` unset and giving `pagination.param`, which pages a POST by
  query string exactly like GET. Omit both for a single POST. The recipe's `body` is
  never mutated across pages.
* **`api.url_base`** — the base each row URL is `urljoin`ed against. Defaults to
  `start_urls[0]` (the API endpoint). Set it when the JSON host ≠ the site host so a
  relative row URL (e.g. `/en/pages/<slug>`) resolves to the **site**, not the API host.
  The *request* URL still uses `start_urls[0]`; only the row links use `url_base`.
* **List-index + quoted keys in every `*_field` path** — besides plain `a.b.c`, a segment
  may be a list index `a.b[0].c` or a quoted key holding spaces/dots
  `tags.metaData."Publish Date"[0].title`. Plain dotted paths (and a bare numeric segment
  like `a.results.0`, which stays the string **key** `"0"`) behave exactly as before —
  an index is only the bracket form `[0]`.

```yaml
# Kyrgyzstan president.kg — speeches ("Выступления") from a POST search API. The JSON
# also carries the full body, so the client-rendered article page is never fetched.
source_id: kgz_president
country: Kyrgyzstan
source_language: Russian
user_agent: "Mozilla/5.0 (…) Chrome/126.0.0.0 Safari/537.36"   # WAF blocks the bot UA
start_urls:
  - "https://president.kg/api/v1/news/search"
listing:
  link_pattern: '/ru/news/\d+'
pagination:
  type: api
  start: 0
  step: 1
  max_pages: 20
  api:
    method: POST
    body:                          # the exact JSON the SPA POSTs (captured from DevTools)
      filter: { active: true, categories: [31] }   # 31 = the speeches category
      pageRequest: { limit: 20, page: 0 }
      sorting: { sortBy: PUBLISHED_AT, sortDirection: DESC }
    body_page_field: pageRequest.page       # the offset is written here each page
    results_path: content
    url_field: id                            # row id -> joined against url_base
    url_base: "https://president.kg/ru/news/"
    title_field: titleRu
    date_field: publishedAt
    text_field: content.titleRu              # JSON carries the body -> skip the page fetch
title: { selectors: ["h1", "title"] }        # required by the schema; only fallbacks here
text:  { selectors: ["article", "main"] }
date:  { selectors: ["time", ".date"] }
position: president
date_languages: ["ru"]
```

> **Tip — capturing a POST body:** in DevTools → Network → Fetch/XHR, find the listing
> request, right-click → *Copy → Copy as cURL* (or read the "Request Payload"), and
> transcribe the JSON into `api.body`. Watch for required headers (an SPA API key like
> `x-client-id`, or an `Origin`/`Referer` the gateway enforces) — put those under
> `api.headers`. Note that api dates are parsed as standard ISO/RFC (no `date_languages`):
> if the API's date is localized `DD.MM.YYYY`, prefer taking the date off the fetched
> page (with `date_languages`) and treat the api `date_field` as a fallback.

### WordPress REST (`results_path: "."`)

WordPress powers a lot of government sites, and its REST API is usually open even when the
visible listing is a JavaScript SPA you cannot crawl. The tell: `/wp-json/wp/v2/posts`
returns JSON. Two things differ from the SharePoint shape above:

- **The response is a bare array at the root**, not an envelope, so there is no dotted path
  to give — use `results_path: "."`.
- Fields are nested under `rendered`: `title.rendered`, `content.rendered`.

Find the speech category id first (`/wp-json/wp/v2/categories?per_page=100` lists them with
counts), then:

```yaml
start_urls:
  - https://www.presidentti.fi/wp-json/wp/v2/posts?categories=21&per_page=100
pagination:
  type: api
  param: page          # WP pages with ?page=N; it 400s past the last page, which the
  start: 1             # engine treats as "stop here" (a logged warning, not a failure)
  step: 1
  max_pages: 10
  api:
    results_path: "."          # the response IS the array
    url_field: link
    title_field: title.rendered
    date_field: date           # ISO 8601; api dates skip date_languages by design
```

**Leave `text_field` unset** unless you have checked it: `content.rendered` is *HTML*, so
setting it stores markup as the speech body **and** skips the page fetch entirely. Leaving it
unset lets the engine fetch each `link` and extract clean text with your `text` selectors,
using the JSON only for url/title/date.

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

## PDF speech pages (`content_type: pdf`)

Some high-value archives serve speeches as **PDF files**, not HTML — e.g. Brazil's
Biblioteca da Presidência, the only source for Lula I–II (2003–2010). Set
`content_type: pdf` and the engine downloads each harvested URL's bytes and extracts the
text with a PDF library (pdfminer.six; install with `pip install '.[pdf]'`) instead of
BeautifulSoup, then maps the result into the same schema / `doc_id` / state as everything
else. This works over any pagination type, **including `wayback`** (the archived PDF bytes
are fetched and extracted).

Because a PDF has no DOM, there are no selectors to match. Two things change:

1. **`content_type`** — `auto` (default) treats a page as HTML unless the URL looks like a
   PDF (`.pdf` / `@@download`) or the response is `application/pdf`; **`pdf`** forces every
   harvested URL through the PDF extractor. Use `pdf` when the PDF URLs carry *no* `.pdf`
   hint (some Plone object ids drop the extension). A `pdf`-mode URL that unexpectedly
   returns HTML (a mixed listing, an error page) falls back to HTML parsing automatically.
2. **`url_regex`** — since there are no selectors, pull `title` / `date` / `speaker` off the
   **URL** with a per-field `url_regex` (the body always comes from the PDF; the title
   falls back to the PDF's first line). `url_regex` runs on the page URL and uses `group(1)`
   if it captures, else the whole match. For **dates**, named `(?P<year>)(?P<month>)(?P<day>)`
   groups are assembled directly into an ISO date — which sidesteps DD/MM ambiguity for
   numeric archive paths like `/2003/18-06-…`. (`url_regex` also works on HTML recipes, as a
   fallback when a selector misses — e.g. a date that only appears in the URL.)

`title`/`text`/`date` are still required *keys* in the YAML, but for a `pdf` recipe they may
be empty (`{}`) — the schema check is relaxed so a PDF source needs no HTML selectors.

```yaml
# Brazil — Biblioteca da Presidência (ex-presidents), Lula 2003–2010, via the archive.
source_id: bra_biblioteca_wayback
country: Brazil
source_language: Portuguese
content_type: pdf                    # download PDF bytes + extract text
start_urls:
  - biblioteca.presidencia.gov.br/presidencia/ex-presidentes/luiz-inacio-lula-da-silva/discursos
listing:
  link_pattern: '/\d{4}/[^/]+$'      # keep the bare PDF object; drop its /@@download twin
pagination:
  type: wayback
  wayback_filter:                    # keep only real PDF captures (drop text/html noise)
    - "mimetype:application/pdf"
    - "statuscode:200"
title: {}                            # no DOM: title falls back to the PDF's first line
text:  {}                            # body comes from the PDF
date:
  url_regex: '/(?P<year>\d{4})/(?P<day>\d{2})-(?P<month>\d{2})-'   # DD-MM-YYYY off the URL
speaker_default: Lula da Silva
position: president
date_languages: ["pt"]
```

> **`wayback_filter`** is a general CDX knob (not PDF-specific): a list of raw CDX
> `filter=` expressions ANDed together. `mimetype:application/pdf` is what makes a PDF
> wayback recipe clean — a bare prefix query otherwise returns thousands of `text/html`
> listing / redirect / `.pdf/view` captures alongside the actual PDF binaries.

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
| `content_type` | no | `auto` (default), `html`, or `pdf`. `pdf` downloads each speech URL's bytes and extracts text with a PDF library instead of BeautifulSoup (see "PDF speech pages"). `auto` treats a page as HTML unless the URL/response says PDF. |
| `verify_ssl` | no | Default `true`. Set `false` for sites with a broken/incomplete TLS cert chain (common on older gov sites) — symptom: a `CERTIFICATE_VERIFY_FAILED` error. |
| `user_agent` | no | Override the default honest bot `User-Agent` (used for the page fetch and the api/feed clients). Only needed for a WAF that hard-blocks the bot UA — symptom: `0 links` / empty pages from the bot UA but real content from a browser UA. Use sparingly; the honest UA is the default. |
| `listing.link_selector` | one of these | CSS selector for the `<a>` elements linking to speeches. |
| `listing.link_pattern` | one of these | Regex an href must match (e.g. `"/discursos/\\d+"`). Use with or instead of `link_selector`. |
| `keep_if.selectors` | one of these | CSS elements whose combined text `pattern` is tested against — use the **article's own** category element, not the site nav (which lists every category on every page). Omit to test the whole document's text. See "Filtering by the PAGE, not the URL". |
| `keep_if.pattern` | one of these | Regex deciding whether a fetched page becomes a row. Prefix `(?i)` for case-insensitive. Omit (with `selectors` set) to keep pages where any selector is merely present. |
| `keep_if.negate` | no | Default `false`. `true` inverts the verdict: DROP the page when it matches. |
| `pagination.type` | no | `query_param`, `path`, `click`, `next_link`, `url_list`, `sitemap`, `wayback`, `api`, `feed`, or `none` (default). |
| `pagination.param` | for query_param | Query parameter name (`start`, `page`). |
| `pagination.start` / `step` | no | First index/offset and the increment between pages (defaults `0` / `1`). |
| `pagination.path_format` | for path | Suffix template appended to `start_url`, with a `{n}` placeholder for the page index. Default (unset) appends `/{n}` (e.g. `/discursos/2`). Use it when the pager isn't a bare number — e.g. `path_format: "P{n}"` with `start: 0, step: 20` yields `…/speeches/P0`, `…/speeches/P20`, `…/speeches/P40` (president.ie). Supports format specs like `{n:03d}` for zero-padding. |
| `pagination.max_pages` | no | Safety cap. Omit to stop automatically when a page yields no new links. |
| `pagination.next_selector` | for click / next_link | CSS selector of the "next" control. May point at the `<a>` itself or a wrapper (e.g. `li.next`), in which case its first descendant `<a href>` is used. |
| `pagination.url_list` | for url_list | Explicit list of **speech-page URLs**. They are used **as-is**: the engine does *not* fetch them as listings, does *not* extract links from them, and does *not* apply `listing.link_pattern` to them. To enumerate several **listing** pages instead, put them all in `start_urls` and leave `pagination.type` as `none` — see "Several listing pages" below. |
| `pagination.sitemap_urls` | for sitemap | Sitemap `.xml` URL(s). The full URL list comes from the sitemap (a sitemap *index* is followed into its children), filtered by `listing.link_pattern`. Best for full history — see the tip below. |
| `pagination.wayback_limit` / `wayback_match_type` / `wayback_collapse` / `wayback_delay` / `wayback_from` / `wayback_to` | for wayback | CDX/query pacing knobs. `wayback_limit` caps captures per query; `wayback_delay` controls the pause before each archived fetch; the defaults are `prefix`/`urlkey`, `5s`, and no date bounds. |
| `pagination.wayback_filter` | no | A list of raw CDX `filter=` expressions (`field:regex`) ANDed together — e.g. `["mimetype:application/pdf", "statuscode:200"]` to keep only real PDF captures and drop a prefix query's text/html noise. |
| `wayback_extend` | no | Opt-in continuation of a **live** recipe into the Internet Archive after its crawl finishes (see "Auto-continuing a live recipe into the archive"). `true` reuses everything; a mapping supplies overrides. `false`/absent = off. Same-host only. |
| `wayback_extend.prefix` | no | CDX prefix to enumerate. Default = derived from `start_urls[0]` (host+path). Set it when speeches don't live under the listing path. |
| `wayback_extend.link_pattern` | no | Regex selecting archived speech URLs. Default = `listing.link_pattern`. |
| `wayback_extend.title` / `text` / `date` / `speaker` / `context` | no | Per-field selector-chain overrides for the (often differently structured) archived pages. Default = reuse the live recipe's selectors. |
| `wayback_extend.wayback_from` / `wayback_to` / `wayback_delay` / `wayback_limit` / `wayback_match_type` / `wayback_collapse` | no | Archive pacing/bounds, mirroring the `wayback` knobs. `wayback_to` (YYYYMMDD) overrides the automatic "earliest live date" floor; otherwise it's computed for you. |
| `pagination.api.results_path` | for api | Dotted path to the array of result rows in the JSON (e.g. `d.query.PrimaryQueryResult.RelevanceResults.Table.Rows.results`), **or `"."` when the response *is* the array** — a bare JSON list at the root, which is what WordPress's `/wp-json/wp/v2/posts` returns (see "WordPress REST" below). Paths may use list indices (`a.b[0].c`) and quoted keys with spaces/dots (`tags.metaData."Publish Date"[0].title`); plain `a.b.c` is unchanged. |
| `pagination.api.url_field` | for api | Dotted path to a row's speech URL — or, in cells mode, the cell **key** naming it (e.g. `Path`). |
| `pagination.api.title_field` / `date_field` / `text_field` / `speaker_field` | no | Same as `url_field` for the other fields. `text_field` lets the JSON carry the full body, skipping the per-speech page fetch. Dates are parsed as standard (ISO/RFC) formats — `date_languages` is **not** applied here. |
| `pagination.api.method` | no | `GET` (default) or `POST`. Use `POST` for endpoints whose listing is a POST JSON call (SPA/SharePoint CSOM). |
| `pagination.api.body` | for POST | The JSON body sent on each POST request (capture it from DevTools). Never mutated across pages. |
| `pagination.api.body_page_field` | no | Dotted path into `body` where the per-page offset (`start + page_idx*step`) is written each POST request (e.g. `pageRequest.page`). Omit to page a POST by query `param` instead (or for a single request). |
| `pagination.api.url_base` | no | Base URL that row URLs are `urljoin`ed against (defaults to `start_urls[0]`). Set it when the JSON host ≠ the site host, so relative row URLs (e.g. `/en/pages/<slug>`) resolve to the site, not the API host. |
| `pagination.api.cells_path` | no | SharePoint cells mode: dotted path within a row to its `{Key, Value}` cell array (e.g. `Cells.results`). When set, the `*_field` names match cell **keys** instead of being row paths. |
| `pagination.api.cell_key` / `cell_value` | no | Attribute names in a cell dict (defaults `Key` / `Value`). |
| `pagination.api.headers` | no | Per-request header overrides for the JSON call — e.g. `Accept: application/json;odata=nometadata` for SharePoint, or an SPA API key / `Origin` a gateway requires (`x-client-id`, `Origin`). Browser-like `User-Agent`/`Accept-Language` are sent by default. |
| `pagination.api.delay` | no | Courtesy pause (seconds) between API page requests (default `0`). |
| `pagination.feed.format` | no | `auto` (default), `rss`, or `atom`. |
| `pagination.feed.use_content` | no | Default `true` — populate `text` from the feed body (RSS `content:encoded`/`description`, Atom `content`/`summary`). Set `false` to force a per-speech page fetch. |
| `title` / `text` / `date` | yes | Each is `{ selectors: [...] }`, an ordered fallback chain. First match wins. |
| `speaker` / `context` | no | Same shape as above. |
| `<field>.attr` | no | Read this attribute instead of element text (e.g. `attr: datetime` on a `<time>` tag). |
| `<field>.regex` | no | Pull a substring out of the matched value (e.g. isolate a date from a label). |
| `<field>.url_regex` | no | Extract the field from the page **URL** when no selector matches (or when there's no DOM — PDFs). Uses `group(1)` if it captures, else the whole match. For `date`, named `(?P<year>)(?P<month>)(?P<day>)` groups assemble an unambiguous ISO date. |
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
