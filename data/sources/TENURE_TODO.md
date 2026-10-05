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
| `tenure_additions/latam_slv.csv` | 14 | 1994–2026 | [ ] pending (Calderón Sol 1994–99 — casapres.gob.sv reaches 1997; Bukele 2019–26) |
| `tenure_additions/latam_gtm.csv` | 10 | 2015–2026 | [ ] pending (Maldonado 2015–16, Giammattei 2020–24, Arévalo 2024–26) |
| `tenure_additions/latam_hnd.csv` | 14 | 2002–2026 | [ ] pending (Maduro 2002–06 — a HOLE in the key, not just a tail; Zelaya + Micheletti 2009; Hernández 2022; Castro 2022–26; Asfura 2026 ⚠ see F) |
| `tenure_additions/latam_nic.csv` | 5 | 2022–2026 | [ ] pending (Ortega 2022–26) |
| `tenure_additions/latam_dom.csv` | 7 | 2020–2026 | [ ] pending (Abinader 2020–26; the key has Medina through 2020) |
| `tenure_additions/latam_pan.csv` | 17 | 1998–2026 | [ ] pending (Pérez Balladares 1998–99 and Moscoso 1999–2004 — a HOLE before the key's 2004 start that pan_presidencia_old_wayback reaches; Cortizo 2019–24; Mulino 2024–26) |
| `tenure_additions/latam_pry.csv` | 13 | 2001–2026 | [ ] pending (González Macchi 2001–03 — before the key's 2003 start, reached by pry_presidencia_old_wayback; Abdo Benítez 2018–23; Peña 2023–26). The key's Paraguay `stateabb` is `PAR`, not PRY |
| `tenure_additions/latam_hti.csv` | 24 | 2009–2026 | [ ] pending (L8a, NEW country — the key had no Haiti rows: Préval 2009–11, Martelly 2011–16, Privert 2016–17, Moïse 2017–21; and PROVISIONALLY the heads of government since — Henry 2021–24, Conille 2024, Fils-Aimé 2024–26 ⚠ see F) |
| `tenure_additions/latam_sur.csv` | 20 | 2010–2026 | [ ] pending (L8a, NEW country: Venetiaan 2010, Bouterse 2010–20, Santokhi 2020–25, Jennifer Simons 2025–26 — confirmed from gov.sr's tags) |
| `tenure_additions/latam_brb.csv` | 12 | 2009–2026 | [ ] pending (L8a: Thompson 2009–10 and Stuart 2010 — before the key's 2011 start, reached by the GIS archive; Mottley 2018–26) |
| `tenure_additions/latam_cri.csv` | 11 | 2018–2026 | [ ] pending (L8a: Alvarado 2018–22, Chaves 2022–26, Laura Fernández 2026 — confirmed from presidencia.go.cr) |
| `tenure_additions/latam_cub.csv` | 63 | 1959–2026 | [ ] pending (L8a: Fidel 1959–2001 — cub_gobierno_wayback reaches his 1959 speeches; Raúl 2008–18; Díaz-Canel 2018–26) |
| `tenure_additions/afg_islamic_emirate*.csv` | 28 | 2021–2026 | [x] already in the key |

L7 (2026-09-30) added `latam_dom/pan/pry.csv`; every LatAm country now has an additions file.
Also known from L7, not written: the Dominican key starts in 2000 (Fernández 2000 + 2004–12,
Mejía 2000–04) — the Archive recipes reach 2007, so it covers them.

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
- [ ] **Nicaragua 1991–2001** — the key has Ortega 1979–90 then jumps to Bolaños 2002
  (Chamorro 1990–97, Alemán 1997–2002 missing). No L6 source reaches before 2002, so not needed yet.
- [ ] **El Salvador 1994–1998** — `slv_presidencia_old_wayback` has a 1998 capture of Calderón
  Sol's pages and a 1997–98 /noticias/ tree; rows written (see A).
- [ ] **LatAm L8 (planned 2026-10-04; L8a AUTHORED 2026-10-05 — Haiti, Suriname, Barbados,
  Costa Rica, Cuba now have additions files, see A; L8b/L8c not yet)** — what the chunk's sources
  will need:
  - **Haiti and Suriname: NO rows at all** (no recipes yet either). L8 writes `latam_hti.csv` /
    `latam_sur.csv` from scratch (COW 41 HAI / 115 SUR — verify).
  - **Barbados:** the key has 2011–2018 only (Stuart) → Mottley 2018–26.
  - **Cuba:** the key has 2002–2008 only → Raúl Castro 2008–18, Díaz-Canel 2018–26; and Fidel
    1959–2001 if `cuba.cu/gobierno/discursos` (1,161 Spanish speeches 1959–2008) is taken.
  - **Mexico 1994–1999** (Zedillo) if `zedillo.presidencia.gob.mx` is taken.
  - **Chile** 2022–26 (Boric, Kast); **Costa Rica** 2018–26 (Alvarado, Chaves, L. Fernández);
    **Argentina** 2019–26 (A. Fernández, Milei); **Uruguay** 2020–26 (Lacalle Pou, Orsi) — these
    four are also in C.
  - **Guyana: the key has 2016–2020 ONLY (5 rows)** → Jagdeo 1999–2011, Ramotar 2011–15,
    Granger 2015, Ali 2020–26 (op.gov.gy's Archive reaches 2003, GINA 2001).
  - **Jamaica** 2024–26 (Holness), and Patterson / Simpson Miller / Golding before 2009 if a JIS
    recipe reaches them. **Trinidad and Tobago** 2024–26 (Rowley, Young, Persad-Bissessar) and
    Manning 2004–10 (`tto_opm_gov_wayback` already reaches 2004; the key starts 2011).

## F. Judgement calls about WHO counts (researcher)

- [ ] **Acting / interim presidents:** Brazil's Temer as interim president May–Aug 2016
  (`bra_presidente_interino_wayback`); Venezuela's Delcy Rodríguez, "presidenta encargada" 2026
  (in `latam_ven.csv`); Bolivia's Vice-President García Linera as acting president (two
  transcripts in `bol_comunicacion_discursos_wayback`). One rule for all.
- [ ] **Short tenures:** Peru's Manuel Merino (5 days, Nov 2020) is in `latam_per.csv` —
  keep, or leave to the cleaner?
- [ ] **Nicaragua:** Rosario Murillo's co-presidency since the 2025 constitutional reform (L6).
  The state radio already calls her "Copresidenta" in 2022 (informal before the reform); 952 of
  `nic_radionicaragua`'s 1,025 speech-category posts are her daily addresses. Not in
  `latam_nic.csv` until you decide.
- [ ] **Honduras 2009:** both Manuel Zelaya (Jan–Jun) and Roberto Micheletti (de facto, Jun 2009 –
  Jan 2010) are in `latam_hnd.csv` — keep the de facto president? The key's existing Zelaya rows
  (2006–08) also have NA `stateabb`/`ccode` — fill them (HON / 91).
- [ ] **Honduras 2026: Nasry Asfura is NOT confirmed from a government site** (L6):
  presidencia.gob.hn is down (Cloudflare 1000, DNS) and its last Archive capture (2026-01-17) is
  Castro-era; the Asfura row in `latam_hnd.csv` rests on the planning brief's web search.
- [ ] **El Salvador Dec 2023 – May 2024:** Bukele took leave to run again; a presidential
  designate exercised the office (the site's posts stop naming Bukele Dec 2023 → Jun 2024 but
  never name the designate). `latam_slv.csv` keeps Bukele for 2023–24 — right?
- [ ] **Haiti 2021–2026 (L8):** no president since 7 July 2021. PM Ariel Henry 2021–24, then the
  Transitional Presidential Council (Apr 2024 – Feb 2026) alongside PMs Conille and Fils-Aimé
  *(web search — verify)*. Who is "the leader" for those years: the PM, the Council, both?
  **L8a (2026-10-05) wrote the PMs provisionally into `latam_hti.csv`** (Henry 2021–24, Conille
  2024, Fils-Aimé 2024–26) so the PM's office's material can be crosschecked; delete those rows
  if the answer is "the Council". Fils-Aimé is confirmed PM in Sept 2026 by primature.gouv.ht's
  own video feed. Note the sources: hti_primature is the PM's office, hti_communication_wayback
  is whole-government — Moïse's 2017–21 addresses come only through the latter.
- [ ] **Cuba (L8):** the President (Díaz-Canel) and, since Dec 2019, a Prime Minister (Manuel
  Marrero). And Fidel's *Reflexiones* columns (7,057 archived URLs) run 2007–2016, mostly after
  he left office in 2008 — a former leader's statements. **L8a (2026-10-05):** authored as
  `cub_gobierno_reflexiones_wayback` (497 Spanish columns), queued COMMENTED OUT in
  `queues/latam/latam_cri_cub.txt` until this is decided.
- [ ] **Ceremonial heads of state:** the "executive" corpus estimate excludes ceremonial heads
  and stays an upper bound until `is_ceremonial` is filled for every country.
