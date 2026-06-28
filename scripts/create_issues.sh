#!/usr/bin/env bash
# Seed the first batch of recipe issues. NOT run automatically.
#
# Prereqs:
#   - gh CLI installed and authenticated (`gh auth status`)
#   - run from the repo so gh targets d-schafer/LeaderSpeech (or pass --repo)
#
# Review before running. Each issue is one source = one recipe.
set -euo pipefail

REPO="d-schafer/LeaderSpeech"

gh issue create --repo "$REPO" \
  --title "[recipe] Ireland — president.ie speeches" \
  --label "recipe" \
  --body "Author a recipe for https://president.ie/en/media-library/speeches.
Drupal-style site: title/date aren't in obvious semantic containers and the body sits in a broad wrapper.
Needs a careful selector pass (and a check of whether it requires JS). See docs/recipes.md."

gh issue create --repo "$REPO" \
  --title "[recipe] Chile — Presidencia speeches" \
  --label "recipe,good first issue" \
  --body "Add a recipe for the Chilean presidency's speeches/press section. Likely static + query-param,
similar to Casa Rosada (recipes/arg_casarosada.yml is a good template). Spanish dates."

gh issue create --repo "$REPO" \
  --title "[recipe] Colombia — Presidencia speeches" \
  --label "recipe,good first issue" \
  --body "Add a recipe for the Colombian presidency's discursos. Spanish dates; check pagination style."

gh issue create --repo "$REPO" \
  --title "[recipe] Nigeria — statehouse.gov.ng speeches" \
  --label "recipe" \
  --body "Africa priority. Source: https://statehouse.gov.ng/category/speeches/ (from the RA Africa list).
WordPress-style category pagination. Covers Tinubu and predecessors."

echo "Done. Review the created issues on GitHub."
