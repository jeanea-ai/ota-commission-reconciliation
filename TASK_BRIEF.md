# TASK BRIEF — implement the ota-commission-reconciliation skill

Read `SPEC.md` first — it is the authoritative design and includes the
**live-verified** grounding of the PMS search + folio screens. This brief is the
build contract.

## What to build

Implement a CLI tool that verifies each OTA statement line against a live Choice
Advantage PMS, one reservation at a time by name search, reading the guest folio,
and emits a simple PDF report. Replace the previous bulk-CSV-join /
hotel-journal-detail approach entirely.

## Deliverable files

A single tool directory (an `ota-commission-reconciliation/` skill) containing:

1. **`parse_ota.py`** — parse the OTA statement PDF into line items
   (guest, booking #, check-in, check-out, result, amount, commission).
   Must also accept an already-parsed CSV as an alternate input.
   The CSV input shape (header): `Booking #, Guest Name, Check-in, Check-out,
   Booking amount, Commission amount, Status, Payment type, OTA`.

2. **`verify_reservations.py`** — the per-reservation browser loop (see "Contract").
   `--hotel <CODE>`, input from `parse_ota` output or CSV. Emits results JSON/CSV.
   **Resume-safe** (skip already-processed rows keyed by guest + booking #).

3. **`build_report.py`** — results → simple PDF table (headless Chromium print-to-pdf).

4. **`SKILL.md`** — document the per-reservation verification design.

## Contract (per line item)

For EACH line in the OTA input (**every name — no dropping**, including not-found,
cancelled, and no-show):

1. Search the guest by name in the PMS (arrival window from the line's check-in date).
2. Read: account number, PMS status, arrival, departure, room type, room, rate.
3. Open folio 1; read total charged + detect "adjustment" line items.
4. Compare PDF fields vs PMS — **all fields EXCEPT commission** (name, check-in,
   check-out, booking #, result/status, amount). Any mismatch goes to Notes.
5. Emit a row: Guest Name | Booking # | Account # | Total Charged | Notes.

**Notes column = (a) "adjustment" line items on folio 1, AND (b) any mismatch/discrepancy**
(wrong dates, amount differs, name not found, status differs, etc.). Nothing else.

For cancelled / no-show / not-found names, still emit a row; Total Charged and/or
Account # may be empty.

## Browser automation guidance

- Drive the shared browser over **CDP**. In the reference environment this is
  `ws://127.0.0.1:18800` (browser target discovery at `http://127.0.0.1:18800/json`).
- Follow `SPEC.md` → "Live grounding" for exact URLs, form field names, the search
  trigger (`lookUpProfileByAcctNo(true)`), the folio URL (`GuestFolio.do`), and the
  folio table's `folioAmount` / `Description` semantics.
- Date fields use `M/D/YYYY`.
- Handle login gracefully: the browser may already be logged in, or may need the
  traditional login + Okta "Continue" interstitial bypass. Read credentials from
  config/secrets — never hardcode, never log secrets.

## Constraints

- **Stdlib-only Python 3** (PEP 668 "externally managed"; no venv, no pip). For PDF
  text extraction use `pdftotext` (poppler) + regex; do not depend on `pypdf`.
- Do not publish, tag, install, or push anything. Produce local files only.

## Acceptance test (small proof)

Run `verify_reservations.py` against a single property on a **small subset** (e.g. the
first 3 guests) to prove the loop + folio read works, then `build_report.py` for a
sample PDF. Report: the files created, the match/not-found counts, and the sample PDF
path.
