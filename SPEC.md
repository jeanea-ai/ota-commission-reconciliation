# SPEC — ota-commission-reconciliation (per-reservation verification)

## Goal

Verify each reservation line on a provided OTA statement PDF against **SkyTouch PMS**,
**one reservation at a time**, by searching the guest
name and reading the reservation + guest folio. Not a bulk CSV join; no Hotel Journal
Detail dependency.

## Input — OTA statement PDF

Parsed into line items. Each line carries (from the PDF):
- Guest name
- Booking # (the Expedia/OTA booking number)
- Check-in date
- Check-out date
- Result (Stayed / Canceled)
- Original amount
- Commission amount

The PDF is a text-layer Expedia statement with columns like:
`BookNumber · GuestName · CheckIn · CheckOut · Result · OriginalAmountUSD · CommissionAmountUSD`.

Before searching the PMS, parse the complete statement and derive:
- **Statement start date** = the earliest check-in/arrival date in the PDF.
- **Statement end date** = the latest check-out/departure date in the PDF.

Use that inclusive statement-wide date range for every guest-name search. The OTA
booking number is authoritative from the PDF; do not search for or validate the OTA
booking number in SkyTouch.

## Process — per line item

1. **Search by name** in SkyTouch (`Find > Reservation`) using the
   statement-wide date range, reading back every matching reservation record.
2. **Resolve the search result conservatively**:
   - one matching reservation: continue with that reservation;
   - no matching reservation: emit the row as `Needs attention` with the note
     `Guest not found`;
   - multiple reservations with the same matching name/date criteria: do not choose
     one, do not combine totals, and do not open one arbitrarily. Emit the row as
     `Needs attention` and list every candidate SkyTouch account number in
     Notes so the user can determine the correct reservation manually.
3. **Compare the PDF fields supported by the PMS** against the selected reservation:
   guest name, check-in, check-out, result/status, and original amount. Commission is
   never compared. The OTA booking number is carried from the PDF to the report and
   is not compared with a PMS field.
4. **Always open the guest folio** for a single resolved reservation:
   - calculate the **folio 1 comparable room total** defined below;
   - detect any **"adjustment" line items** on folio 1.
5. **Capture** the SkyTouch account number.

### Folio 1 amount used for comparison

Compare the OTA original amount with room charges and their associated taxes on
Folio 1 only.

- Include room charges.
- Include taxes associated with those room charges.
- Include signed room-charge adjustments when calculating how much the guest was
  charged (credits reduce the total; debits increase it).
- Exclude payments/deposits, refunds, and adjustments unrelated to room charges.
- If an adjustment cannot be classified confidently as room-related or unrelated,
  do not guess: flag the row `Needs attention` and describe the uncertain line in
  Notes.
- Report every absolute difference of **$0.01 or more**.

The report's `Total Charged` value is this calculated Folio 1 comparable room total,
not the folio balance and not the sum of every positive transaction.

### Status comparison

Maintain an explicit, tested mapping between OTA status values and the actual SkyTouch
status labels observed during live verification. Until a PMS status has
been mapped, do not guess that it is equivalent: mark the row `Needs attention` and
add `Status needs review` to Notes.

## Output — simple PDF table

Columns (exactly these):

| Guest Name | Booking # (PDF) | Account # (SkyTouch) | Total Charged (folio 1) | Notes |

- **Every name in the PDF becomes a row** — not-found, cancelled, and no-show included.
- Preserve duplicate source rows, including repeated guest names and booking numbers.
- **Notes column carries two things:**
  1. "adjustment" line items on folio 1, and
  2. any mismatch / discrepancy (wrong dates, amount differs, name not found in PMS).
- Review conditions such as multiple matches, an unknown status, or an uncertain
  room adjustment also go in Notes; do not add report columns.
- Simple table layout — no stat cards, no verdict sections, no color-coding.
- Deliver only the PDF. Name it from the hotel code and statement month. If a
  statement spans months, use the inclusive first-to-last month range.

## Progress, interruption, and privacy

- Give every source line a stable identity that includes the statement identity and
  source row position. Do not use guest name plus booking number as the sole key.
- Save a row only after it is fully processed, using durable, atomic progress writes.
- A failure on one reservation becomes a completed report row with an actionable
  explanation when the remaining rows can be processed safely.
- If the browser session, login flow, PMS, or run itself cannot continue, stop after
  the latest fully completed row, save progress, generate and deliver the partial PDF,
  and notify the Kolo user what happened and where processing stopped. A later run
  resumes without duplicating completed source rows.
- Use an existing authenticated session when available. If it is absent, follow the
  obtain an exact verified SkyTouch browser handoff from the official PMS Setup
  package. PMS Setup alone owns credentials and login. This skill must never request,
  read, store, or log credentials.
- The PDF may contain the full guest name, OTA booking number, and SkyTouch
  account number required for reconciliation. Keep checkpoints private and minimize
  guest information in technical logs.

## SkyTouch grounding and qualification boundary

Approved base URL: `https://www.skytouchhos.com/pms/`

### Login and property identity

The official `mf-hotel-pms-setup 3.5.0` package performs SkyTouch direct login with
no MFA, verifies the exact `<code> - <hotel name>` property label, and returns a
`skytouch-session-v1` handoff containing the exact browser target ID. This skill
reconnects only to that target and independently rechecks the SkyTouch origin and
property code. ChoiceADVANTAGE and Okta paths are out of scope.

### Reservation search by name

- Candidate route: `/pms/FindReservationInitialize.init` and form
  `FindReservationSearchForm`.
- Set `searchLastName`, `searchFirstName`, `searchArrivalFromDate`, `searchArrivalToDate`
  (dates `M/D/YYYY`).
- Trigger `lookUpProfileByAcctNo(true)`.
- Candidate result route: `/pms/FindReservation.do` and "Reservation Information":
  Account Number, Status, Arrival, Departure, Room Type, Room, Rate, Balance.

### Guest Folio

- Candidate "Guest Folio" action: `/pms/GuestFolio.do`.
- Folio 1 is the link labelled `1. Folio 1 - <balance>` (additional folios appear as
  `2. Folio 2`, …; incidentals folio labelled `INCI - <balance>`).
- Line-items table columns: `Item # · Date · Posting Date · Description · Comments · Amount`.
  The Amount cell carries class `folioAmount`; **positive = charge, parenthesised negative
  (e.g. `(180.43)`) = payment**. A `Balance` cell sits above the rows.
- **Comparable room total on Folio 1** is calculated from room charges, associated
  taxes, and signed room-charge adjustments as defined above. There is no printed
  comparable-total line; it must be classified and summed from the transactions.
- **"Adjustment"** = a line item whose `Description` contains "Adjustment" (the
  transaction type exists — "Post Adjustment" is an available folio action). These are
  the only rows that go into Notes under the "adjustment" heading.

The reservation-search and folio routes/selectors above require confirmation during
the first authorized SkyTouch manual run. An unfamiliar route, form, property label,
or table structure fails closed rather than falling back to ChoiceADVANTAGE behavior.

### Worked example (synthetic)

Synthetic guest "Jane Doe" (account 1000000000): charges 161.10 + 16.11 + 3.22 + 170.00
+ 17.00 + 3.40 = **370.83**; payments (180.43) + (190.40); balance 0.00. The PDF listed a
departure of "8/2" while the PMS showed departure "8/1" — that date drift is exactly the
kind of discrepancy the skill flags into Notes.
