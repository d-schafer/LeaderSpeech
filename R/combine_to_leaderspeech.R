# combine_to_leaderspeech.R
#
# The single Python -> R handoff. The Python text_scraper writes cleaned, per-country
# CSVs under data/scraped/<Country>/<source_id>.csv. This script binds them into one
# table, standardizes speaker names, validates speakers against the leader-tenure key,
# and writes the compressed, analysis-ready data/LeaderSpeech.RData.
#
# Everything upstream of this (fetching, extraction, translation, metadata) is Python.
# This stays in R because the name-standardization and tenure-validation assets already
# live here and because .RData is a compact, R-native format for downstream analysis.
#
# Run: Rscript R/combine_to_leaderspeech.R

suppressPackageStartupMessages({
  library(tidyverse)
  library(here)
})

scraped_dir <- here("data", "scraped")
out_file    <- here("data", "LeaderSpeech.RData")

# The standardized schema (must match leaderspeech/text_scraper/run.py SCHEMA_COLUMNS).
schema_cols <- c(
  "doc_id", "country", "ISO3N", "speaker", "position",
  "context", "context_originlanguage",
  "title", "title_originlanguage",
  "text", "text_originlanguage",
  "date", "source", "source_language", "dataset"
)

# 1) Read and bind every per-country CSV. ------------------------------------
csvs <- list.files(scraped_dir, pattern = "\\.csv$", recursive = TRUE, full.names = TRUE)
csvs <- csvs[!grepl("_errors\\.csv$", csvs)]
if (length(csvs) == 0) stop("No scraped CSVs found under ", scraped_dir)

LeaderSpeech <- csvs |>
  map(\(f) read_csv(f, col_types = cols(.default = "c"))) |>
  list_rbind() |>
  # tolerate sources that don't emit every optional column
  { \(df) { df[setdiff(schema_cols, names(df))] <- NA_character_; df } }() |>
  select(all_of(schema_cols)) |>
  mutate(
    date  = suppressWarnings(as.Date(date)),
    ISO3N = suppressWarnings(as.integer(ISO3N))
  ) |>
  filter(!(is.na(text) & is.na(text_originlanguage)))

# 2) Standardize speaker names. ----------------------------------------------
# TODO: source the project's fixNames() (see _examples_code/key_fixNames.R) and apply it.
#   Always condition on country (and sometimes year) — bare surnames collide across countries.
# source(here("R", "key_fixNames.R"))
# LeaderSpeech <- fixNames(LeaderSpeech, "speaker", lubridate::year(LeaderSpeech$date))

# 3) Validate speakers against the leader-tenure key. ------------------------
# TODO: load leader_tenure_final and flag rows where the named speaker does not plausibly
#   hold office in that country on that date; use it to fill speaker where it is missing.
# tenure <- get(load(here("data", "leader_tenure_final.RData")))

# 4) Assign the global ISI_id and save. --------------------------------------
LeaderSpeech <- LeaderSpeech |>
  mutate(ISI_id = paste0("ISI_", row_number())) |>
  relocate(ISI_id)

save(LeaderSpeech, file = out_file)
message("Wrote ", nrow(LeaderSpeech), " speeches to ", out_file)
