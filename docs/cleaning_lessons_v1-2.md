# Cleaning lessons from the LeaderSpeech v1.2 build (2026-09-29)

**Purpose.** This is input for improving `leaderspeech.clean_structure_metadata` and the scrapers.
In September 2026, 20,133 scraped rows were run through the cleaner (`--input` mode, gpt-4.1-mini)
to add speeches to the full corpus. The cleaner was then followed by extra checks in a separate
build. This document lists every problem those extra checks caught. For each one it gives the
count, example rows, where in this repo the gap is, and a concrete fix.

## Where the evidence lives

Records folder: `C:\Users\dgs177\Dropbox (Personal)\academic_work\text_llm\repo_leaderspeech_archive\full_added_v1-2\`

| File | What it holds |
|---|---|
| `gpt_screened*.parquet` | Cleaner ledgers, 4 rounds. Every output column, keyed by `doc_id = "V12S" + scrape_row`. |
| `gate_log.parquet` | The v1.2 accept/reject decision and reason for every screened row. |
| `voice_cache.jsonl` / `bundle_cache.jsonl` / `bundle_verify_cache.jsonl` | Extra GPT judgements. |
| `text_clean_changes.csv` | Every text/title edit, with rule and before/after. |
| `additions_drops.csv` | Why accepted rows were dropped later. |
| `review_examples_substantive.xlsx` | Example rows for each document_type × is_substantive × confidence, and each voice × share band. |
| `candidates_pool.parquet` | Eligible scrape rows with `scrape_row` = row index in `LeaderSpeech_scraped.parquet` (716,358 rows). |

Build scripts, which show what was done instead: `text_llm\repo_leaderspeech_archive\_audit\v1-2\`, in particular:
- `v12_common.py`: name matching, voice prompt, display-name map;
- `04-accept.py`: the stricter gate;
- `05-gpt_bundles_types.py`: the extra GPT calls;
- `06-clean_dedupe_trim.py`: text cleaning and dedupe.

**Scale of the problem.**
- The cleaner accepted **17,855** of 20,133 rows (`clean_status == accepted`).
- The v1.2 gate kept **7,446** of them (42%).
- After bundle, courtesy and duplicate checks, **5,831** were added.
- Most of the difference is policy: the cleaner keeps official statements and ceremonial heads, which v1.2 excluded. But several items below are outright errors.

---

## Errors (the cleaner got it wrong)

### E1. The wrong person is accepted when they share a surname with a leader in office
- **What happened.** The cleaner accepted these as the sitting leader:
  - First Lady Michelle Obama: 84 rows, e.g. `V12S635089`, `V12S635170` ("Remarks by the First Lady…");
  - Kateryna Yushchenko: 10 rows;
  - Fatima Maada Bio, Wafaa Sleiman, Anna Komorowska and others.
- **Why.**
  - `tenure.py:_surname_match` (lines 65–75) returns True when two names share ANY token longer than 2 characters, so "Michelle Obama" matches "Barack Obama".
  - `gate.py:decide` line 56 then SKIPS the leader-type check when `tenure_match == "exact"`. This happens even though the model itself typed these speakers `speaker_type = "other"`.
- **Fix.**
  1. In `_surname_match`, when both names contain given names, require them to be compatible. v1.2's `v12_common.given_compatible` does this: similarity ≥ 0.75, or the same first two letters with similarity ≥ 0.6, plus a nickname table (Frank ~ Josaia/Voreqe, Joe ~ Joseph, Bob ~ Robert, Bill ~ William). Test cases that must return **no match**:
     - Michelle/Barack Obama
     - Lech/Jarosław Kaczyński
     - Gurbanguly/Serdar Berdimuhamedov
     - Konstantinos/Kyriakos Mitsotakis
     - Andreas/Georgios Papandreou
     - Hillary/Bill Clinton
  2. Test cases that must return **match**:
     - George/Georgios Papandreou
     - Joseph R./Joe Biden
     - Josaia Voreqe/Frank Bainimarama
     - Aleksandr/Alexander Lukashenko
     - Volodymyr Zelenskyy/Zelensky
     - Nursultan Nazarbaev/Nazarbayev
     - Viktor Yuschenko/Yushchenko
     - (the last three need a fuzzy surname match, ratio ≥ 0.85)
  3. Strip titles before matching: "President Putin" and "Prime Minister Modi" must match (`TITLE_WORDS` in `v12_common.py`).
  4. In `decide`, do NOT let an exact tenure match override `speaker_type in {"other", "other_minister", "foreign_visitor"}`.

### E2. Leaders are accepted when speaking in a different office in the same year
- **What happened.** Kgalema Motlanthe was President until May 2009, then Deputy President. His Deputy-President speeches from Aug–Dec 2009 were accepted as the leader's (19 rows, e.g. `V12S674946`, `V12S672698`, `V12S674983`).
- **Why.** The tenure key is by calendar year, so any 2009 speech matches. The model's `position` said "Deputy President" and `speaker_type` said `both`.
- **Fix.**
  - Reject when the extracted `position` matches `\b(deputy|vice|former|ex-)`.
  - Longer term: add start/end dates to the tenure key and match on the speech date.

### E3. News reports about the leader are labelled `speech` / `1_speech`
- **What happened.** Among the 7,446 rows v1.2 accepted as speech or interview, a separate GPT voice check found:

  | voice | rows |
  |---|---:|
  | transcript | 4,663 |
  | mixed | 1,341 |
  | report | 1,442 |

- **Examples.**
  - `V12S006858`, `V12S006938`, `V12S006882` (Afghan presidency, "President Ghani: …" articles). The cleaner's own `clean_reasoning` calls them "a direct report of…", yet `inclusion_tier = 1_speech`.
  - Estonian government "Prime Minister Ansip said on the Reporteritund programme…".
  - Polish PAP wire stories.
- **Report-heavy sources** (share of accepted rows that are reports):

  | source | report share |
  |---|---:|
  | `ken_president_news` | 0.70 |
  | `slb_solomons` | 0.66 |
  | `sle_statehouse_wayback` | 0.52 |
  | `irn_president_english_wayback` | 0.50 |
  | `deu_bundeskanzler_english_wayback` | 0.50 |
  | `blr_belarusby_english_wayback` (BelTA) | 0.45 |
  | `ukr_president_english_wayback` | 0.45 |
  | `esp_lamoncloa_english_wayback` | 0.38 |
  | `kaz_akorda_english_wayback` | 0.38 |

- **Why.**
  - `extract.py` line 80 defines `is_first_person` as "the leader's own words are present (… quoted or reported)", so any quote gives "yes".
  - The `document_type` definitions (lines 73–78) have no category for "a third party's article about a speech".
- **Fix.**
  - Add two fields to the extraction schema:
    - `voice`: transcript | mixed | report;
    - `leader_words_share`: 0–100.
  - The prompt that worked, 20/20 agreement with a human reading on the calibration set, is `VOICE_SYSTEM` in `text_llm\...\_audit\v1-2\v12_common.py`. Copy it into `extract.py`.
  - Record `voice` as a label, not a gate. The author's decision: reports that paraphrase the leader are acceptable if substantive.
  - Use it to let users filter, and to prefer transcripts when choosing among candidates.

### E4. Non-English text in the English `text` column
- **What happened.** 194 rows have `detected_language != "en"`:
  - `dnk_stm_english_wayback`: 61 rows, Danish bodies under English titles (e.g. `V12S172706`, `V12S172728`);
  - `lao_kpl_english`: 27;
  - `mlt_president_wayback`: 21 (Maltese);
  - `mdv_presidencymaldives`: 16;
  - `irl_president_wayback`: 15 (Irish).
- **Fix (scraper side).** Run a language detector (lingua or fasttext) at scrape time. Route non-English bodies to `text_originlanguage`.

### E5. Date errors survive
- **What happened.** Every row sent had a site date, so `date_precision = "scraped"` for all 20,133, and the final date never differed from the scraped one. Yet 848 rows were flagged `date_disagreement_flag = True`.
- **Example.** `V12S034209` (Armenia) is dated 2021-03-31, but the title is about the ArmHighTech-**2022** exhibition.
- **Fix.**
  - When `date_disagreement_flag` is True and the text/title contains an explicit year that differs from the site date by ≥ 1, prefer the model's date, or at least surface these for review.
  - Log how often the model's date and the site's date disagree, per source. Bulk-upload dates (the same date on hundreds of pages) are a known source pattern.

---

## Policy choices the cleaner leaves to the user (make them explicit config)

### P1. Ceremonial heads of state are kept
- **What happened.** 2,328 accepted rows have `is_ceremonial == True` (flag only).
- **Whole sites belong to a ceremonial head or royal house.** These are the zero-yield sources in v1.2 (rows sent → rows kept):

  | source | sent | kept |
  |---|---:|---:|
  | `irl_president_wayback` | 980 | 0 |
  | `irl_president` | 122 | 0 |
  | `arm_president_wayback` | 651 | 0 |
  | `nld_royalhouse_wayback` | 298 | 0 |
  | `mkd_pretsedatel_english_wayback` | 241 | 0 |
  | `swe_kungahuset_english_wayback` | 192 | 0 |
  | `lva_president_english_wayback` | 153 | 0 |
  | `deu_bundespraesident_english_wayback` | 135 | 0 |
  | `mlt_president_wayback` | 104 | 0 |
  | `ind_presidentofindia_krn_wayback` | 99 | 0 |
  | `svn_up_rs_wayback` | 94 | 0 |
  | `bel_monarchie_wayback` | 47 | 0 |

- **Fix.**
  - Add a recipe-level field such as `office: head_of_state_ceremonial | head_of_state_executive | head_of_government | royal_house`, so a user can include or exclude whole sources without GPT calls.
  - Add a config switch, e.g. `exclude_ceremonial: true`, that rejects on `is_ceremonial`.

### P2. `official_statement` is kept by default
- **What happened.** 7,828 screened rows were typed `official_statement`. Of these, 6,560 are `is_substantive = yes`. Examples: "President Ghani Meets Azerbaijan President" (`V12S006930`), "President Ghani: I Am Determined to…" (`V12S006874`).
- **Top countries:**

  | country | rows |
  |---|---:|
  | Canada | 624 |
  | Ukraine | 416 |
  | Turkmenistan | 349 |
  | Seychelles | 326 |
  | Lithuania | 293 |
  | Armenia | 286 |
  | Estonia | 245 |

- **Two problems inside this category.** Seen in `text_llm\repo_leaderspeech_archive\full_added_v1-2\review_official_statements.xlsx`, which has examples of every is_substantive × is_first_person × executive-in-office variety:
  1. **Some real speeches are typed as statements.** Example: "Government statement by the Federal Chancellor in the Bundestag", a speech to parliament.
  2. **Site homepages and newsletter pages land here.** Examples: "Official web-site of President of Azerbaijan Republic", "Subscribe e-Newsletter", "www.president.gov.lk". Titles like these should be rejected before any GPT call.
- **Varieties among all 14,537 screened statements** (the last two rows overlap by 3%):

  | variety | share |
  |---|---:|
  | substantive + first person + executive in office | 42% |
  | substantive + third person + executive | 27% |
  | not substantive (greetings, condolences) | 13% |
  | not the executive (ceremonial heads, ministers) | 21% |

- **What v1.2 did.** It excluded them, keeping speeches and interviews only. That is the right default for a *speech* corpus, but these rows carry position information.
- **Fix.** Keep them in the cleaned store (as now) and document `inclusion_tier` filtering in the README.

### P3. `is_substantive` is a category, not a score
- **The question.** "Does the document convey a substantive expression of the leader's position…", with answers yes / no / unsure (`extract.py` lines 82–86). The author asked for probabilities; none exist.
- **Counts across all 20,133 rows:**

  | document_type | yes | no |
  |---|---:|---:|
  | speech | 10,497 | 209 |
  | interview | 748 | 19 |
  | official_statement | 6,560 | 1,267 |

  "unsure" is almost never used (5 rows).
- **Fix, if graded filtering is wanted.**
  - Request `logprobs` for the `is_substantive` token and store the probability; or
  - ask for a 0–100 `substance_score`.
- `clean_confidence` is the model's confidence in the whole answer, not in `is_substantive`.

---

## Text-quality problems (fix at scrape time where possible)

### T1. Site furniture at the start and end of texts
Furniture was stripped from 3,601 texts. The most common strings, all verbatim from `text_clean_changes.csv`:

| String (lines joined with " / ") | Where | Rows |
|---|---|---:|
| `]]>` | end of `aus_pmtranscripts` (a CDATA leftover); also `PRIME MINISTER / ]]>` and `ends / ]]>` | 323 |
| `Events / Text version` | Kremlin | 229 |
| `\| \| \|\|\|\|\| / \| \| / \| All rights reserved. \|` | `ukr_president` footer | 159 |
| `Opinions & Interviews / print version / make home page / add to bookmarks / all Opinions & Interviews` | BelTA | 133 |
| `Read about / the rules for downloading photos / . / Download photo` | `pol_president` head | 101 |
| `Speeches / Prev / Next / tweet`, `Communications Bureau / Latest News / Speeches / <date> / Hits: 924 / Print / Email` | `gha_presidency_wayback` | |
| `Press release / Arhiiv`, `Press Releases (EN)` | `est_valitsus_english` | |
| `Κοινοποίηση / Facebook / Twitter / webteam` | `grc_primeminister_english_wayback` | |
| `Speech / No, I refuse / Yes, I accept` | cookie banner | |
| `Idioma / Castellano / Català / … / Cookies policy / Accept / Reject` | `esp_lamoncloa` | |
| `suomi / Lue artikkeli suomeksi / svenska / Läs artikeln på svenska / English` | `fin_presidentti` | |
| `Name: / * / Email:` | comment forms | |
| `home / » / news room / » / speeches / …` | `gbr` breadcrumb | |

Other common lines: `Share`, `Comment`, `⤢`, `Related`, `Newsroom`, `copy link`, `CHECK AGAINST DELIVERY`, `Press Office / of the President of Georgia`.

**Whole-menu wrappers.** Some sites wrap every article in the full site menu, above and below it. Examples:
- gov.ro (`rou_guvern_english_wayback`): about 35 lines, including the long sentence "The Government is the public authority of executive power...". This is up to 54% of a page's words, and 268 such pages had passed the first cleaning.
- The edge rule cannot catch these, because of its 30% limit and because the menu lines look like sentences.

The v1.2 fix (`06-clean_dedupe_trim.py`, step 2b):
- A line counts as site boilerplate if it occurs in at least 60% of that site's texts (sites with at least 20 texts).
- It is removed anywhere in the text, but only within a run of at least 3 such lines, or when it is a single line of 12+ words. Short common speech lines such as "Thank you." are never touched.
- 2,300 texts were changed; the median removal was 3% of words.
- Other sites it cleaned: Kremlin, `hun_miniszterelnok`, `sle_statehouse`, `sgp_pmo`, `uga_statehouse`, `guy_motp`, `bel_premier` (cookie notice) and `dnk_stm` (share bar).

**Stripped by the v1.2 block rule.** The Kremlin tail: `Publication status / Published in sections: / News / , / Transcripts / Publication date: / December 31, 2021, 23:55 / Direct link: / en.kremlin.ru/d/67514`.

**Fix.**
- Preferred, in each recipe: exclude these elements with CSS selectors.
- Fallback, in the cleaner: edge stripping per source. Remove leading/trailing lines that either match a navigation regex, or are short (≤ 8 words, no final punctuation) and appear in ≥ 25% of that source's texts. Cap the removal at 30% of the words. Also treat a head line that repeats the page title as furniture.
- **Pitfall found.** The frequency rule stripped the Arabic invocation "بسم الله الرحمن الرحيم" that opens Khamenei's speeches (110 rows) as if it were furniture. Exempt non-Latin-script lines, or keep a per-source allow-list.

### T2. Stacked pages / bundles
- **What happened.**
  - The first-pass bundle prompt (`classify_bundles_gpt.py` style) flagged 915 of 7,446 accepted rows (12%).
  - The grounded verify prompt (the model must quote each speech body's opening words) confirmed only 100.
  - The quotes were found in the text, spanning ≥ 30% of it, for only 84.
- **False positives** were single speeches wrapped in site furniture:

  | source | false positives |
  |---|---:|
  | `irn_khamenei_english_wayback` | 130 |
  | `ukr_president_english_wayback` | 123 |
  | `gha_presidency_wayback` | 109 |
  | `sgp_pmo_wayback` | 102 |
  | `blr_belarusby_english_wayback` | 60 |

- **True bundles** were mostly joint press conferences with several leaders' statements, e.g. `V12S024425` (Vučić + Rama + Zaev), and a few index pages.
- **Fix.** Use only the grounded verify prompt (`verify_bundles_gpt.py` SYSTEM) plus the openings-in-text check (`build_bundles_all.py:ground`, MIN_SPREAD 0.30). Strip furniture BEFORE the bundle check.

### T3. Duplicates across and within sources
- **What happened.**
  - 234 additions were exact or near duplicates, meaning ≥ 50% of sampled 8-word runs were shared with a longer text from the same country:

    | source | duplicates |
    |---|---:|
    | `ukr_president_english_wayback` | 46 |
    | `gha_presidency_wayback` | 40 |
    | `can_pmo_eng_wayback` | 27 |
    | `pol_president_english_wayback` | 21 |
    | `rwa_kagame_wayback` | 13 |
    | `pol_president` | 11 |

  - Two scrapes of the same site were a recurring pair: `pol_president` and `pol_president_english_wayback`.
  - The existing corpus had 22 Turnbull speeches scraped from both pm.gov.au and pmtranscripts. They became identical once footers were removed.
  - URL matching alone found only 13,108 of 24,664 scrape rows already in the corpus; 8-word-run containment found 24,639.
- **Fix.** Add a cross-source dedupe step:
  - use 8-word-run containment, per country, after furniture stripping;
  - record `duplicate_of` instead of deleting;
  - prefer the source with the best text.

### T4. Missing space after full stops ("word.The")
- **What happened.** The existing corpus had 8,475 of these in 1,190 rows; the new additions only 99 rows. The cause is HTML block elements joined without a separator at scrape time.
- **Fix.**
  - In text extraction, join block-level elements (`p`, `div`, `li`, `br`, `h*`) with "\n".
  - Repair regex: `([a-z]{2,})\.([A-Z][a-z])` → `\1. \2`, skipping tokens that look like URLs or domains.

### T5. Titles
- 990 titles contain newlines. Many repeat twice: "Press conference by … 7 March 2023\nPress conference by … 7 March 2023".
- Some are generic ("Speeches" on the Ghana site).
- 747 titles were tidied (among additions).
- **Fix.** Collapse whitespace, dedupe repeated halves, and pick a better title selector where the title is generic.

### T6. All-caps OCR transcripts
- **Where.** `aus_pmtranscripts`, 1980s Hawke era (e.g. "SPEECH BY THE PRIME MINISTER, THE HON R. J. HAWKE A. C. M. P.").
- **What was done.** Sentence-cased line by line with `truecase` (lowercase → `truecase.get_true_case` → tidy spacing), as `_audit/truecase_helper.py` does.
- **Remaining OCR debris:**
  - fax headers ("TEL: 12. Jan. 94 12: 30 No. 006 P. 02");
  - "E& OE PROOF COPY";
  - hard line wraps mid-sentence;
  - "T0" for "TO".

### T7. Junk or low-value sources (drop before any GPT call)

| source | problem |
|---|---|
| `mdv_presidencymaldives_wayback` | 21,564 rows, median 2 words, 17,367 undated |
| `mda_gov_english_wayback` | 6,966 rows, none dated, none name a leader |
| `bgr_government_english_wayback` | median 24 words |
| `zaf_gov` | mostly ministers; only ~2,700 name the President |
| `tkm_turkmenistan_news`, `lao_kpl_english` | third-person news |

---

## Tenure-key problems that hurt matching (see also `docs/leader_tenure.md`)

1. **Stale copy.** `data/sources/leader_tenure_final.csv` in this repo has 3,214 lines. The current key has ~9,800 rows. Point `clean_config.yml:tenure_file` at the current key.
2. **Name forms.**
   - REIGN gives bare surnames ("Hawke", "Keating", "Karmal").
   - V-Dem gives full formal names ("William Kipchirchir Samoei Arap Ruto", "Mikhail Uladzimiravich Myasnikovich").
   - The model returns everyday forms. A display-name map was needed (`NAME_DISPLAY` in `v12_common.py`).
3. **Ceremonial flag defaults to FALSE** for V-Dem-sourced rows. V-Dem's `v2ex_hosw` is 0 for Poland, Romania, Croatia, Lithuania and Ukraine, so a hand list of semi-presidential executives was needed.
4. **Father/son conflation.** Greece 1990–93 was attributed to Kyriakos rather than Konstantinos Mitsotakis. Also check Papandreou, Aliyev, Berdimuhamedov and Kenyatta.
5. **2022–2024 gaps.** REIGN caps at 2021 and V-Dem v14 ends in 2023, so 2024 handovers were hand-entered. Jeremiah Manele (Solomon Islands, May 2024) was initially missed.
6. **Leaders missing because their surname is spelled differently:** Zelenskyy/Zelensky, Berdimuhamedov/-w, Frank/Josaia Voreqe Bainimarama, George/Georgios Papandreou, Joe/Joseph R. Biden.

## Code to port from the v1.2 build

All of this is working code in
`C:\Users\dgs177\Dropbox (Personal)\academic_work\text_llm\repo_leaderspeech_archive\_audit\v1-2\`,
below abbreviated as `v1-2/`. Line numbers are as of 2026-09-30.

| What | Where | Notes / gotchas |
|---|---|---|
| Edge furniture stripping | `v1-2/06-clean_dedupe_trim.py` 100–140 (`NAV`, `freq`, `is_title_line`, `strip_furniture`) | See the list below. |
| Menu-block stripping | same file, 142–180 (`strip_blocks`, `BLOCK_MIN_RUN = 3`, `LONG_LINE = 12`) | See the list below. |
| Character-level cleaning | same file, 182–235 (`clean_text`, `clean_title`) | Mojibake repair via ftfy on suspect tokens only (`MOJI_TOKEN`); zero-width characters; separator runs; stray HTML tags; trailing copyright footer (`FOOTER`, last line only); "word.The" → "word. The" (`GAP`, skips URLs/domains). Titles: collapse whitespace, drop a repeated second half. |
| All-caps transcripts | same file, 236–254 (`recase`) | Line by line: lowercase → `truecase.get_true_case` → `truecase_helper.tidy_spacing`. Needs `pip install truecase` and `nltk.download('punkt_tab')`. |
| Near-duplicate detection | same file, 255–280 | 8-word runs per country, longest text first, a duplicate at ≥ 50% of ~60 sampled runs. The same idea with 20% (02a, 02e) checks "already in corpus". |
| Stricter accept gate | `v1-2/04-accept.py` 51–110 | Rejects `speaker_type` other/minister/foreign even with an exact tenure match; deputy/vice/former positions; model-recovered dates more than 7 days after the capture date (site dates are exempt: khamenei.ir sits one day past capture). |
| Name matching | `v1-2/v12_common.py` 117–170 (`TITLE_WORDS`, `NICKNAMES`, `given_compatible`, `name_score`) | Test cases are listed under E1 above. |
| Voice prompt | `v1-2/v12_common.py` 82–115 (`VOICE_SYSTEM`, `voice_prompt`) | transcript / mixed / report + `leader_words_share`. |
| Undated pages | `v1-2/02e-select_undated.py` | Prefilters against the corpus BEFORE any GPT call; half of the good undated pages were already in the corpus. The cleaner's date pre-pass then dated about 85%. |

**Edge furniture stripping** (100–140).
- A navigation regex, plus per-site frequent lines: ≥ 25% of the site's texts, ≤ 8 words, no final punctuation.
- A head line repeating the title is also treated as furniture.
- Capped at 30% of the words.
- **The frequency rule needs a whole site's texts at once.** Put it where the cleaner processes a source, not row by row.
- Exempt non-Latin script: it stripped the Bismillah that opens Khamenei's speeches until that exemption was added.

**Menu-block stripping** (142–180).
- A line is boilerplate if it is in ≥ 60% of a site's texts (sites with ≥ 20 texts).
- It is removed anywhere, but only in runs of ≥ 3 such lines or as a single line of ≥ 12 words, so "Thank you." inside speeches survives.
- Median removal was 3% of words; maximum 54% (gov.ro).

**Lessons from how these were found.**
1. **Clean BEFORE the GPT screen, not after.** The screen sees only the first 500 words (`max_words`). On gov.ro the menu took most of those words, and on other sites navigation and footers made the bundle check fire falsely (T2). Furniture stripping belongs in the scraper, or first in the cleaner.
2. **Log every edit with a rule name and the removed text** (`text_clean_changes.csv`: `doc_id`, `rule`, `before`, `after`). Grouping that log by `before` string is how both false positives were found: the Bismillah (110 identical removals) and the menu the edge rule missed.
3. **Spot-check random finished rows, not just the logs.** The gov.ro menu problem (268 pages) was found by reading 10 random undated additions. It had passed every automated check, including GPT's "speech" verdict, because the speech was inside the menu.
4. **Size before spending.** Count candidates for free (cheap filters + corpus containment), then run a ~200–300-row GPT probe per new source type before a full run. The short-text and undated probes each cost under $1 and changed the plan.

## Tooling notes
- **Always parquet.** `store.write_source_atomic` (line 116) writes parquet whatever the extension. It also leaves a full-size `.bak` next to each output, which doubles Dropbox usage for large ledgers.
- **Missing `dateparser`.** `dateparser` is not installed in `C:\Projects\openai_new_MSU`, so non-English month parsing (`datetext.py`) is silently skipped.
- **No cost logging.** Nothing logs tokens or cost. Store `response.usage` per row in the ledger. The ~20k-row run cost roughly $40 across all calls (estimate).
- **Truncated input.** The model sees only the first 500 words (`max_words`), so bundles, footers and later speakers are invisible to it.
- **Throughput.** About 100 rows per 10 s at 25 concurrent requests, with no errors in 20,133 calls. One verify call hit `max_tokens` (JSON cut off); use ≥ 800 for prompts that return quoted lists.

## Suggested order of work
1. E1 + E2: name matching and the gate's handling of exact matches. These are correctness bugs, and the code is small.
2. E3: add `voice` / `leader_words_share` to the schema.
3. P1: add a recipe-level `office` field, plus an `exclude_ceremonial` switch.
4. T1 / T4 / T5: scraper-side text extraction (block joins, CSS exclusions, titles), with cleaner-side edge stripping as a fallback.
5. T3: cross-source dedupe.
6. Point `tenure_file` at the current key; add aliases and display names.
7. E4, E5, T2, P3: language routing, date disagreements, the grounded bundle check, and optionally a substance score.
