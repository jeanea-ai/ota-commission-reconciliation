# SkyTouch browser adapter contract

The included `scripts/browser_adapter.mjs` controls only the exact browser target
returned by the official PMS Setup SkyTouch handoff. It accepts only HTTPS pages on
`www.skytouchhos.com` or `skytouchhos.com` beneath `/pms/`. It never performs login
and never receives credentials.

`verify_reservations.py` sends one UTF-8 JSON request on stdin and expects one JSON
response on stdout. Non-zero exit, timeout, non-JSON output, or `{"ok": false}` is
a bounded adapter failure.

## Readiness request

```json
{
  "action": "doctor",
  "property_code": "1833",
  "target_id": "verified-browser-target"
}
```

The adapter reconnects to that exact target, rechecks the SkyTouch origin, requires
an authenticated Logout control and exactly one matching `<code> - <name>` property
label, then confirms the reservation search form is available.

## Search request

```json
{
  "action": "search_reservations",
  "property_code": "1833",
  "target_id": "verified-browser-target",
  "first_name": "Jane",
  "last_name": "Doe",
  "arrival_from": "1/1/2026",
  "arrival_to": "1/31/2026"
}
```

The response contains every matching reservation. Reservation objects use
`account_number`, `guest_name`, `arrival`, `departure`, `status`, and `folio_1`.
Folio items use `description`, `comments`, and signed `amount`.

```json
{
  "ok": true,
  "reservations": [{
    "account_number": "1000000000",
    "guest_name": "Jane Doe",
    "arrival": "2026-01-02",
    "departure": "2026-01-04",
    "status": "Checked Out",
    "folio_1": [
      {"description": "Room Charge", "comments": "", "amount": "100.00"},
      {"description": "Room Tax", "comments": "", "amount": "10.00"},
      {"description": "Visa Payment", "comments": "", "amount": "-110.00"}
    ]
  }]
}
```

The current reservation-search and Folio 1 selectors are qualification candidates
based on the supplied workflow specification. The first authorized SkyTouch manual
run must confirm them. An unfamiliar page fails closed and produces no financial
result.

