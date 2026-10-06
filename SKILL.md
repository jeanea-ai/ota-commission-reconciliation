---
name: ota-commission-reconciliation
version: 0.1.0
description: Reconcile Expedia and Booking.com statement PDFs against ChoiceADVANTAGE or SkyTouch reservations and Folio 1, producing a five-column PDF report. Use when a Kolo user requests OTA commission or reservation reconciliation for these PMS variants.
---

# OTA commission reconciliation

Run this skill only on demand. The Python commands own parsing, arithmetic,
checkpointing, matching outcomes, and report generation; do not reproduce those
steps conversationally or use a model to calculate money.

## Required configuration

- `OTA_PMS_COMMAND`: optional executable override for the included authenticated
  shared-browser adapter. See `references/browser-adapter.md`.
- `OTA_PMS_BASE_URL`: the property's ChoiceADVANTAGE or SkyTouch base URL. URLs
  are configuration, not reconciliation logic.
- `OTA_CDP_ENDPOINT`: optional Kolo shared-browser discovery endpoint. Defaults to
  `http://127.0.0.1:18800`.
- `OTA_STATUS_MAP`: optional path to a reviewed JSON status map. Unknown status
  pairs are always flagged for review.
- `OTA_STATE_DIR`: optional private checkpoint directory. Defaults to
  `.state/ota-commission-reconciliation` beneath the current working directory.

Credentials belong to Kolo's secret configuration. When the shared session is
signed out, the adapter reads `OTA_PMS_USERNAME` and `OTA_PMS_PASSWORD` from that
secret environment and completes traditional login automatically. Never request,
print, or store them in skill files.

## Run

1. Parse the supplied Expedia or Booking.com PDF:

   `python scripts/parse_ota.py statement.pdf --output parsed.json`

2. Verify every source row against the PMS:

   `python scripts/verify_reservations.py parsed.json --hotel HOTELCODE --output results.json`

3. Build the final or partial report:

   `python scripts/build_report.py results.json --output-dir reports`

Return only the generated PDF to the user. Working JSON, HTML, checkpoints, and
diagnostics remain private.

## Non-negotiable behavior

- Preserve every input row, including duplicates, cancellations, and no-shows.
- Use the full statement's earliest arrival through latest departure for every
  name search.
- Never choose among multiple plausible reservations. List all candidate account
  numbers in Notes and continue.
- Carry the OTA booking number from the statement; do not seek it in the PMS.
- Compare the OTA amount only with Folio 1 room charges, related taxes, and signed
  room-related adjustments. Exclude deposits, payments, refunds, and unrelated
  adjustments. Flag uncertain classifications.
- Report differences of one cent or more.
- Checkpoint only complete rows, atomically. Resume by stable statement/source-row
  identity, not guest name or booking number.
- After bounded safe recovery, turn a run-blocking failure into one plain-language
  Kolo question with a recommended next step. Do not emit progress chatter.

## Validation and recovery

Run `python -m unittest discover -s tests -v` before packaging. The readiness
command `python scripts/verify_reservations.py --readiness` validates the browser adapter
without changing PMS data. Browser operations are read-only, but an uncertain navigation
must be reconciled by reading current state before replay.

