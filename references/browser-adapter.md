# Kolo browser adapter contract

The included `scripts/browser_adapter.mjs` controls Kolo's shared browser directly
through its configurable CDP endpoint. `verify_reservations.py` launches it once per
request. `OTA_PMS_COMMAND` may override it with another contract-compatible adapter.
The command receives one UTF-8 JSON object on stdin and returns one UTF-8 JSON object
on stdout. Non-zero exit, timeout, non-JSON output, or `{"ok": false}` is a bounded
adapter failure. Diagnostic stderr must not contain guest or credential data.

## Doctor request

```json
{"action":"doctor","base_url":"https://configured-pms.example/"}
```

Return:

```json
{"ok":true,"authenticated":true,"pms":"skytouch"}
```

The included adapter uses the active authenticated session when available. If the
PMS shows a password form, it reads `OTA_PMS_USERNAME` and `OTA_PMS_PASSWORD` from
Kolo's secret environment and follows the traditional-login continuation. It must
never return credentials.

## Search request

```json
{
  "action":"search_reservations",
  "base_url":"https://configured-pms.example/",
  "first_name":"Jane",
  "last_name":"Doe",
  "arrival_from":"1/1/2026",
  "arrival_to":"1/31/2026"
}
```

Return every matching reservation. A reservation object uses `account_number`,
`guest_name`, `arrival`, `departure`, `status`, and `folio_1`. Each folio item uses
`description`, `comments`, and `amount`; negative values are JSON numbers below zero.

```json
{
  "ok":true,
  "reservations":[{
    "account_number":"1000000000",
    "guest_name":"Jane Doe",
    "arrival":"2026-01-02",
    "departure":"2026-01-04",
    "status":"Checked Out",
    "folio_1":[
      {"description":"Room Charge","comments":"","amount":"100.00"},
      {"description":"Room Tax","comments":"","amount":"10.00"},
      {"description":"Visa Payment","comments":"","amount":"-110.00"}
    ]
  }]
}
```

The adapter owns PMS-specific navigation, including the configurable base URL,
traditional login/Okta continuation, `FindReservationInitialize.init`, form fields,
`lookUpProfileByAcctNo(true)`, `FindReservation.do`, `GuestFolio.do`, and Folio 1.
It must return only after it has read a stable result page.

