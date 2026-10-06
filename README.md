# SkyTouch OTA Commission Reconciliation

Kolo marketplace skill for reconciling exported Expedia and Booking.com statement
rows against SkyTouch reservations and Folio 1. It is SkyTouch-only and does not
support ChoiceADVANTAGE.

Authentication and property identity come from the official
`mf-hotel-pms-setup 3.5.0` SkyTouch handoff. This package never handles credentials.
It parses the statement, searches every guest, calculates comparable room charges,
preserves ambiguous and missing reservations, checkpoints completed rows, and
produces a five-column PDF.

## Package

- `SKILL.md` - Kolo entrypoint and operating contract.
- `scripts/pms_setup_bridge.py` - official SkyTouch session handoff.
- `scripts/parse_ota.py` - Expedia/Booking.com PDF and CSV parser.
- `scripts/browser_adapter.mjs` - exact-target SkyTouch browser automation.
- `scripts/verify_reservations.py` - matching, Folio 1 calculation, and checkpoints.
- `scripts/build_report.py` - five-column PDF report generator.
- `tests/` - deterministic fixtures and contract coverage.
- `SPEC.md` - authoritative business requirements.

## Local checks

```text
python3 -m unittest discover -s tests -v
python3 scripts/verify_reservations.py --hotel HOTELCODE --readiness
```

The readiness command requires the official PMS Setup marketplace build and a
configured SkyTouch property. Live PMS behavior must be qualified manually before
production use.
