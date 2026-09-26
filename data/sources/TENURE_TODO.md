# Leader-tenure key — known gaps (to-do)

Started 2026-09-26. One place to collect what `leader_tenure_final.csv` (this folder; one row
per leader-year) is known to be missing, so recipe sessions append here instead of scattering
notes. **Add a line when you find a gap; tick it when it is folded into the key.**

How gaps get closed:
- **Hand-written rows** go in `tenure_additions/<name>.csv` (the key's own columns:
  `speaker,ISO3N,country,year,matchDF,COWcode,stateabb,ccode,is_ceremonial`; copy the codes and
  the exact `country` string from the country's existing rows). The researcher folds them in.
- **Speakers found in cleaned data** go through the propose-then-approve tool
  (`python -m leaderspeech.leader_tenure.run --diagnostic`, free; see `docs/leader_tenure.md`).
- Measured 2026-09-26: the key has 3,213 rows, 123 countries, years 1979–2026.

## A. Hand-written additions waiting to be folded in

| file | rows | years | status |
|---|---|---|---|
| `tenure_additions/latam_bra.csv` | 132 | 1902–2026 | [ ] pending (Rodrigues Alves … FHC 1st term; Bolsonaro 2022–23, Lula 2023–26) |
| `tenure_additions/latam_col.csv` | 11 | 2018–2026 | [ ] pending (Duque, Petro, De La Espriella) |
| `tenure_additions/latam_ven.csv` | 6 | 2022–2026 | [ ] pending (Maduro 2022–26, Delcy Rodríguez acting 2026) |
| `tenure_additions/latam_per.csv` | 16 | 2018–2026 | [ ] pending (Vizcarra … Keiko Fujimori) |
| `tenure_additions/latam_ecu.csv` | 7 | 2021–2026 | [ ] pending (Lasso, D. Noboa) |
| `tenure_additions/latam_bol.csv` | 10 | 2019–2026 | [ ] pending (Áñez, Arce, Rodrigo Paz) |
| `tenure_additions/afg_islamic_emirate*.csv` | 28 | 2021–2026 | [x] already in the key |

Coming: the LatAm push's L6–L7 will add `latam_slv/gtm/hnd/nic/pan/dom/pry.csv`.

## B. Countries the cleaner cannot join to the key at all

The cleaner's tenure crosscheck compares the RAW country string (`tenure.match_speaker`), so a
recipe string that differs from the key's never matches — and some countries have no rows.
Measured against every recipe on 2026-09-26 (recipes in brackets):

- [ ] **No rows in the key:** Egypt (2), Nigeria (2), Pakistan (1), South Korea
  (`Korea, Republic of`, 2 — the key has only North Korea).
- [ ] **String mismatch** (recipe → key): `Iran, Islamic Republic of` → `Iran` (4),
  `Russian Federation` → `Russia` (1), `Tanzania, United Republic of` → `Tanzania` (1),
  `Viet Nam` → `Vietnam` (1), `Lao People's Democratic Republic` → `Laos` (2),
  `Türkiye` → `Turkey` (1), `United States` → `United States of America` (10),
  `Gambia` → `The Gambia` (2).
- Recommended fix (free, then `clean_structure_metadata.run --regate`): join on `ISO3N`, which
  both the key and every scraped row carry — no alias map to maintain. It does not fix the four
  countries with no rows.

## C. The key stops before 2024 for 84 of the 98 countries that have recipes

Any speech after a country's last key year cannot be crosschecked. Worst first
(last year in the key → countries; count of recipes in brackets where > 3):

- [ ] **2006–2009:** Bangladesh 2006, Cuba 2008, Maldives 2008, Mongolia 2009
- [ ] **2016–2017:** Uzbekistan 2016, Kyrgyzstan 2017
- [ ] **2018:** Botswana, Colombia (7), Costa Rica, Ethiopia, Peru (4) — *Colombia, Peru: see A*
- [ ] **2019:** Argentina, Bolivia (4) — *Bolivia: see A*
- [ ] **2020:** Belgium (5), Burundi, Guyana, Japan, Malaysia, Uruguay, Vanuatu
- [ ] **2021:** Azerbaijan, Brazil (11), Chile, Cyprus, Ecuador (5), Georgia, Ghana (8),
  Indonesia, Kenya, Madagascar, Philippines, Rwanda, Seychelles, Sierra Leone, Slovenia (7),
  Somalia, Sudan, Turkmenistan, Uganda, Ukraine, Venezuela (5), Zimbabwe — *Brazil, Ecuador,
  Venezuela: see A*
- [ ] **2022:** Bhutan, Bulgaria (4), Finland (5), Latvia, Luxembourg, New Zealand, Sri Lanka,
  Thailand (4), Timor-Leste
- [ ] **2023:** Albania (5), Armenia, Australia (4), Austria, Canada, Czechia (5), Denmark (4),
  Estonia (6), Fiji (4), Germany (4), Greece, Hungary (14), Iceland (4), India (8), Ireland,
  Israel, Italy (4), Jamaica, Kazakhstan (4), Kuwait (5), Lebanon, Lithuania, Malta, Myanmar,
  Netherlands, North Macedonia, Norway, Singapore (6), Solomon Islands, Spain, Sweden (5),
  Trinidad and Tobago, United Kingdom

A systematic extension to 2026 for every country is probably cheaper than doing these one by
one.

## D. Scraped data older than the key's first year

Earliest plausible date in the scrape index vs the key's first year (2026-09-26). Some of these
are real history the corpus now reaches; some are misdated rows (Colombia's 1948 is a known body
date on a 2025 speech). **Check the scraped rows first, then add the leaders.**

- [ ] Afghanistan scraped from 1970 (key 2015) · Australia 1940 (1996) · Belarus 1994 (1998) ·
  Burundi 2005 (2016) · Colombia 1948 (1998, misdate) · Croatia 1934 (1992) · Czechia 1990 (1993) ·
  Estonia 1993 (1996) · Ethiopia 2015 (2017) · Fiji 1933 (2009) · Germany 1985 (2003) ·
  Ghana 1901 (2007) · Guyana 2015 (2016) · India 1947 (1996) · Ireland 1908 (1990) ·
  Kuwait 1990 (2001) · Luxembourg 2008 (2021) · Madagascar 2019 (2021) · Maldives 1978 (2000) ·
  Morocco 2012 (2013) · Netherlands 1999 (2002) · North Macedonia 2004 (2005) · Norway 1941 (2001) ·
  Philippines 1936 (1998) · Sierra Leone 1944 (2008) · Singapore 1970 (1997) ·
  Solomon Islands 2019 (2020) · Spain 1975 (1996) · Sudan 2015 (2019) · Sweden 1994 (2002) ·
  Trinidad and Tobago 2004 (2011) · Ukraine 2005 (2009) · Vanuatu 1975 (2017) · Zimbabwe 2016 (2017)

## E. Deep-history sources that need older rows (known from recipes)

- [ ] **Peru 1821–2000** — `per_congreso_mensajes_wayback` (534 presidential messages to
  Congress, 1821–2015; ~150 fall 1900–2000, the rest 19th-century). The key starts Peru at 2001.
  Precedent: Brazil 1902–1998 was written by hand (`latam_bra.csv`).
- [ ] **Brazil 1902–1998** — written (see A), not yet folded.
- [ ] **Ecuador 2000–2006** — covered; nothing needed (the old `.gov.ec` recipe starts 2002).

## F. Judgement calls about WHO counts (researcher)

- [ ] **Acting / interim presidents:** Brazil's Temer as interim president May–Aug 2016
  (`bra_presidente_interino_wayback`); Venezuela's Delcy Rodríguez, "presidenta encargada" 2026
  (in `latam_ven.csv`); Bolivia's Vice-President García Linera as acting president (two
  transcripts in `bol_comunicacion_discursos_wayback`). One rule for all.
- [ ] **Short tenures:** Peru's Manuel Merino (5 days, Nov 2020) is in `latam_per.csv` —
  keep, or leave to the cleaner?
- [ ] **Nicaragua:** Rosario Murillo's co-presidency since the 2025 constitutional reform (L6).
- [ ] **Ceremonial heads of state:** the "executive" corpus estimate excludes ceremonial heads
  and stays an upper bound until `is_ceremonial` is filled for every country.
