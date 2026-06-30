#!/usr/bin/env Rscript
# Final deliverable producer for the LeaderSpeech dataset.
#
# Reads the intermediate merged Parquet written by the Python merge step
# (`python -m leaderspeech.clean_structure_metadata.merge`), applies the authoritative
# leader-name standardization key (`_examples_code/key_fixNames.R`), and writes the
# FINAL deliverable in three name-consistent formats:
#   data/LeaderSpeech.parquet   (canonical, zstd)
#   data/LeaderSpeech.RData     (R-native; loads an object named `leaderspeech`)
#   data/LeaderSpeech.csv.gz    (universal-access export)
#
# Run from the repo root:  Rscript scripts/export_leaderspeech.R
# The R `arrow` package is required (read/write Parquet).

suppressWarnings(suppressMessages({
  if (!requireNamespace("arrow", quietly = TRUE)) {
    stop("The R 'arrow' package is required: install.packages('arrow')")
  }
  library(arrow)
}))

args <- commandArgs(trailingOnly = TRUE)
in_path   <- if (length(args) >= 1) args[[1]] else "data/_build/LeaderSpeech_merged.parquet"
out_dir   <- if (length(args) >= 2) args[[2]] else "data"
key_path  <- "../../_examples_code/key_fixNames.R"   # parent research workspace

if (!file.exists(in_path)) {
  stop(sprintf("intermediate not found: %s\nRun `python -m leaderspeech.clean_structure_metadata.merge` first.", in_path))
}

message(sprintf("Reading %s ...", in_path))
df <- as.data.frame(arrow::read_parquet(in_path), stringsAsFactors = FALSE)
message(sprintf("  %d speeches, %d columns", nrow(df), ncol(df)))

# --- apply authoritative name standardization (researcher's living key) ---
if (file.exists(key_path)) {
  source(key_path)                                  # defines fixNames(dataframe, speaker, year)
  if (!"year" %in% names(df)) {
    df$year <- suppressWarnings(as.integer(substr(as.character(df$date), 1, 4)))
    added_year <- TRUE
  } else {
    added_year <- FALSE
  }
  message("Applying fixNames() ...")
  df <- fixNames(df)                                # rules key on $speaker/$country/$year
  if (added_year) df$year <- NULL
} else {
  warning(sprintf("name key not found at %s — writing WITHOUT fixNames standardization", key_path))
}

dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

# --- 1) Parquet (canonical, zstd) ---
pq <- file.path(out_dir, "LeaderSpeech.parquet")
arrow::write_parquet(df, pq, compression = "zstd")
message(sprintf("Wrote %s", pq))

# --- 2) RData (loads an object named `leaderspeech`) ---
rdata <- file.path(out_dir, "LeaderSpeech.RData")
leaderspeech <- df
save(leaderspeech, file = rdata)
message(sprintf("Wrote %s", rdata))

# --- 3) csv.gz (optional universal-access export) ---
tryCatch({
  gz <- file.path(out_dir, "LeaderSpeech.csv.gz")
  con <- gzfile(gz, "w", encoding = "UTF-8")
  utils::write.csv(df, con, row.names = FALSE, fileEncoding = "UTF-8")
  close(con)
  message(sprintf("Wrote %s", gz))
}, error = function(e) warning(sprintf("csv.gz export skipped: %s", conditionMessage(e))))

message(sprintf("Done — %d speeches in the final LeaderSpeech dataset.", nrow(df)))
