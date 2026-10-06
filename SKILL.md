---
name: ota-commission-reconciliation
version: 0.7.0
description: Reconcile Expedia and Booking.com statement PDFs against SkyTouch reservations and Folio 1, producing a five-column PDF report. Use only for SkyTouch properties; do not use for ChoiceADVANTAGE or another PMS.
requires: [mf-hotel-pms-setup]
tags: [hotel, skytouch, expedia, booking.com, ota, reconciliation, pdf]
author: Kolo Hotels
---

# SkyTouch OTA commission reconciliation

Run this skill on demand for a property already configured as `pms.vendor:
skytouch` by the official `mf-hotel-pms-setup` 3.5.0 marketplace package.
This skill does not support ChoiceADVANTAGE and must never attach to a Choice tab.

The deterministic commands own statement parsing, arithmetic, checkpointing,
matching outcomes, and report generation. No model calculates money or chooses an
ambiguous reservation.

## Authentication boundary

`scripts/pms_setup_bridge.py` invokes PMS Setup's `tools/skytouch_login.py
--handoff`. PMS Setup owns credentials, direct no-MFA login, property verification,
and the exact authenticated browser target. This skill receives only the
`skytouch-session-v1` handoff, then rechecks the SkyTouch origin and property label.

Never request, read, copy, or store a password. Never use a ChoiceADVANTAGE or Okta
credential path. Refuse local-only or version-mismatched PMS Setup packages.

## Run

1. Parse an exported Expedia or Booking.com statement:

   `python3 scripts/parse_ota.py statement.pdf --output parsed.json`

2. Verify every source row against SkyTouch:

   `python3 scripts/verify_reservations.py parsed.json --hotel HOTELCODE --output results.json`

3. Build the complete or partial report:

   `python3 scripts/build_report.py results.json --output-dir reports`

Return only the generated PDF. Working JSON, HTML, checkpoints, and diagnostics
remain private.

## Required behavior

- Preserve every input row, including duplicates, cancellations, and no-shows.
- Use the statement's earliest arrival through latest departure for every search.
- Never choose among multiple plausible reservations. List candidate SkyTouch
  account numbers in Notes and continue.
- Carry the OTA booking number from the statement; do not seek it in SkyTouch.
- Compare the OTA amount only with Folio 1 room charges, related taxes, and signed
  room-related adjustments. Exclude deposits, payments, refunds, and unrelated
  adjustments. Flag uncertain classifications.
- Report differences of one cent or more.
- Checkpoint only complete rows, atomically. Resume by stable statement/source-row
  identity, not guest name or booking number.
- After bounded safe recovery, turn a run-blocking failure into one plain-language
  owner question with a recommended next step. Do not send progress chatter.

## Readiness and release gate

Run `python3 scripts/verify_reservations.py --hotel HOTELCODE --readiness`. It must
prove an official PMS Setup 3.5.0 package, a verified SkyTouch handoff, the exact
SkyTouch property, and the reservation search form without processing a statement.

Before publication, run `python3 -m unittest discover -s tests -v`, the Kolo static
audit, source-manifest verification, and a secret scan. Live SkyTouch selectors,
retry, resume, and partial-report behavior remain a manual qualification gate.

