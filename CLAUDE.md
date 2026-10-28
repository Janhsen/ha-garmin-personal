# Working rules for Claude – ha-garmin-personal

Public Home Assistant custom integration (HACS), domain `garmin_personal`, for the official Garmin Connect Personal API. Everything in this repository is public.

## Public-repo rule (always)
- Never write personal data into files, commits, issues, test data or API samples: no real names, no places or addresses, no employer, no phone numbers, e-mail addresses, Garmin IDs, tokens or API keys. Use invented examples (Alex, Sam).
- Do not describe the owner's private setup (devices worn, dashboards, family, work). Keep text technical.
- Before every push: search the diff and the changed files for such terms and read the result. Real API responses must be anonymised before they go into `docs/` or `tests/`.

## Layout
- `custom_components/garmin_personal/`: `api.py` (client), `coordinator.py`, `sensor.py`, `values.py` (value extraction), `history.py` and `intraday.py` (series, hourly statistics), `stats_writer.py`, `services.py`, `config_flow.py`, `repairs.py`, `diagnostics.py`.
- `strings.json` and `translations/{en,de}.json` are **generated** by `scripts/gen_translations.py` (run from the repo root). Do not edit them by hand; the `test_i18n_*` tests check consistency.
- `scripts/api_fields.py`: checks for new Garmin fields; `docs/api-fields/` and `docs/garmin-personal-swagger.json` are the references.
- `BACKLOG.md`: ideas and open points; move items to `CHANGELOG.md` when released.

## Rules for the code
- Nothing is calculated or invented: what Garmin does not deliver stays empty (`unknown`). The only exception is the calculated expiry date of the API key (documented in the README).
- The API key is stored only in Home Assistant, never logged, never in diagnostics.
- Sensors keep the last known value where the README says so; history entities are separate from live sensors and are append-only (only new points are written, nothing already written is overwritten).
- Do not rename entities or keys without a migration; users' history must survive updates.

## Commands
- Lint: `ruff check .` (pinned `ruff==0.16.9`, same as CI).
- Tests: one process per file, because each file installs its own Home Assistant stubs: `for t in tests/test_*.py; do python3 -I "$t" || exit 1; done`
- CI also runs `hassfest` and the HACS action (`.github/workflows/validate.yml`).

## Release
- Raising `version` in `custom_components/garmin_personal/manifest.json` on `main` triggers the Release workflow: lint, tests and hassfest, then a ZIP asset and a GitHub release. The release notes are taken from the matching `## X.Y.Z` section of `CHANGELOG.md`, so write that section first.
- Docs in English (`README.md`), German version in `README.de.md`; keep both in step.
- Force-push to this repository is allowed (maintainer decision), but ask before using it.
- Ask the maintainer whether a change goes to a branch or directly to `main`.
