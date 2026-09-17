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
   **Resume-safe** using a stable statement-and-source-row identity. Guest + booking #
   is not sufficient because duplicate rows are valid input.

3. **`build_report.py`** — results → simple PDF table (headless Chromium print-to-pdf).

4. **`SKILL.md`** — document the per-reservation verification design.

## Contract (per line item)

For EACH line in the OTA input (**every name — no dropping**, including not-found,
cancelled, and no-show):

1. Parse the complete input first. Use the earliest PDF check-in as the statement
   start date and the latest PDF check-out as the statement end date. Use that
   inclusive date range for every PMS guest-name search.
2. Search by guest name and read every matching reservation.
3. Resolve the result without guessing:
   - no match: mark `Needs attention` and note `Guest not found`;
   - one match: continue;
   - multiple matching name/date reservations: mark `Needs attention`, list every
     candidate Choice Advantage account number in Notes, leave Total Charged empty,
     and do not select or combine reservations.
4. For one resolved reservation, read account number, PMS status, arrival, departure,
   room type, room, and rate.
5. Open Folio 1 and calculate the comparable room total: room charges + associated
   taxes + signed room-charge adjustments. Exclude deposits/payments, refunds, and
   unrelated adjustments. An adjustment that cannot be classified confidently makes
   the row `Needs attention` rather than being guessed.
6. Compare guest name, check-in, check-out, mapped result/status, and OTA original
   amount. Report every absolute amount difference of $0.01 or more. Commission is
   not compared. Carry the OTA booking number from the PDF without looking for or
   validating it in Choice Advantage.
7. Emit a row: Guest Name | Booking # | Account # | Total Charged | Notes.

**Notes column = (a) "adjustment" line items on Folio 1, (b) any mismatch or
discrepancy, and (c) required review conditions or processing failures.** Examples
include wrong dates, amount differences, guest not found, multiple candidate account
numbers, unfamiliar status, and an uncertain room adjustment.

For cancelled / no-show / not-found names, still emit a row; Total Charged and/or
Account # may be empty.

Use only an explicit, tested mapping for OTA/PMS status equivalence. During live
testing, record the Choice Advantage labels actually observed. An unfamiliar status
must produce `Status needs review` in Notes rather than an inferred match.

Preserve duplicate input rows. Each source row must reach one durable terminal result
even when its guest name and booking number duplicate another row.

## Resume and failure contract

- Save each fully completed row atomically in private persistent skill storage.
- On restart, skip only the exact completed source-row identities; never skip a row
  merely because its guest and booking number were seen before.
- If one reservation fails but safe processing can continue, emit its row with the
  failure in Notes and process the remaining rows.
- If the run cannot continue, stop after the latest fully completed row, persist
  progress, generate and deliver the five-column partial PDF, and notify the Kolo user
  with the cause and stopping point. A later run resumes from the next source row.
- Do not retry an uncertain browser action as though it definitely failed; re-read
  current state before repeating it.

## Browser automation guidance

- Use Kolo's available shared-browser control mechanism. In the reference environment,
  CDP target discovery is `http://127.0.0.1:18800/json`; keep the endpoint configurable
  rather than baking it into reconciliation logic.
- Follow `SPEC.md` → "Live grounding" for exact URLs, form field names, the search
  trigger (`lookUpProfileByAcctNo(true)`), the folio URL (`GuestFolio.do`), and the
  folio table's `folioAmount` / `Description` semantics.
- Date fields use `M/D/YYYY`.
- Use an active authenticated session when available. Otherwise perform Kolo's
  configured traditional-login flow and Okta "Continue" step automatically. Never
  ask the user to log in. Read credentials from config/secrets; never hardcode or log
  secrets.

## Constraints

- **Stdlib-only Python 3** (PEP 668 "externally managed"; no venv, no pip). For PDF
  text extraction use `pdftotext` (poppler) + regex; do not depend on `pypdf`.
  Browser control may use the browser interface already supplied by the Kolo runtime;
  do not introduce a new pip-installed automation dependency.
- The final artifact is the PDF only. Working JSON/CSV and checkpoints are private,
  minimize guest information in diagnostic logs, and never include credentials.
- Name the delivered report from the hotel code and statement month. If the statement
  spans months, use the inclusive first-to-last month range.
- Do not publish, tag, install, or push anything. Produce local files only.

## Acceptance test (small proof)

Before a full statement is trusted, run `verify_reservations.py` against one property
on a small approved subset that, when available, covers:

1. one ordinary single-reservation match;
2. one guest not found; and
3. one guest with multiple matching reservations.

Also test a duplicate source row, a one-cent amount difference, an unfamiliar status,
a room-charge adjustment, and resume after an injected interruption using fixtures.
Then run `build_report.py` and verify that both complete and partial reports contain
exactly the five required columns. Report the files created, result counts, observed
PMS status labels, resume result, and sample PDF path.
