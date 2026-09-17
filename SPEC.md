# SPEC — ota-commission-reconciliation (per-reservation verification)

## Goal

Verify each reservation line on a provided OTA statement PDF against the live PMS
(Choice Advantage / SkyTouch), **one reservation at a time**, by searching the guest
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

## Process — per line item

1. **Search by name** in Choice Advantage (`Find > Reservation`), reading back the
   reservation record.
2. **Compare all PDF fields EXCEPT commission** against the PMS reservation:
   guest name, check-in, check-out, booking #, result/status, amount.
3. **Always open the guest folio**:
   - read **folio 1 total charged**
   - detect any **"adjustment" line items** on folio 1
4. **Capture** the Choice Advantage account number.

## Output — simple PDF table

Columns (exactly these):

| Guest Name | Booking # (PDF) | Account # (Choice) | Total Charged (folio 1) | Notes |

- **Every name in the PDF becomes a row** — not-found, cancelled, and no-show included.
- **Notes column carries two things:**
  1. "adjustment" line items on folio 1, and
  2. any mismatch / discrepancy (wrong dates, amount differs, name not found in PMS).
- Simple table layout — no stat cards, no verdict sections, no color-coding.

## Live grounding (verified against a real Choice Advantage property)

Base URL: `https://www.choiceadvantage.com/choicehotels/`

### Login

Traditional login with a legacy username (`KUser.<code>`); password resolved from
config/secrets (never hardcoded). After submit an Okta interstitial
**"Migrate your account to Okta / Continue with Traditional Login"** appears — click the
**"Continue"** link to proceed.

### Reservation search by name

- Navigate to `FindReservationInitialize.init` → form `FindReservationSearchForm`.
- Set `searchLastName`, `searchFirstName`, `searchArrivalFromDate`, `searchArrivalToDate`
  (dates `M/D/YYYY`).
- Trigger `lookUpProfileByAcctNo(true)`.
- Result lands on `FindReservation.do` → "Reservation Information" showing:
  Account Number, Status, Arrival, Departure, Room Type, Room, Rate, Balance.

### Guest Folio

- "Guest Folio" action → `GuestFolio.do`.
- Folio 1 is the link labelled `1. Folio 1 - <balance>` (additional folios appear as
  `2. Folio 2`, …; incidentals folio labelled `INCI - <balance>`).
- Line-items table columns: `Item # · Date · Posting Date · Description · Comments · Amount`.
  The Amount cell carries class `folioAmount`; **positive = charge, parenthesised negative
  (e.g. `(180.43)`) = payment**. A `Balance` cell sits above the rows.
- **Total charged on Folio 1** = sum of positive `folioAmount` values (charges only,
  excluding payments). There is no printed "total charged" line — it must be summed.
- **"Adjustment"** = a line item whose `Description` contains "Adjustment" (the
  transaction type exists — "Post Adjustment" is an available folio action). These are
  the only rows that go into Notes under the "adjustment" heading.

### Worked example (synthetic)

Synthetic guest "Jane Doe" (account 1000000000): charges 161.10 + 16.11 + 3.22 + 170.00
+ 17.00 + 3.40 = **370.83**; payments (180.43) + (190.40); balance 0.00. The PDF listed a
departure of "8/2" while the PMS showed departure "8/1" — that date drift is exactly the
kind of discrepancy the skill flags into Notes.
