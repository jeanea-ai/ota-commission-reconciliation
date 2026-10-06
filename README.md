# OTA Commission Reconciliation

Kolo skill for reconciling Expedia and Booking.com statement rows against
ChoiceADVANTAGE or SkyTouch. The PMS products share the same workflow; each property
supplies its own base URL through configuration.

The skill parses the statement, searches every guest, reads Folio 1, compares room
charges and associated taxes, preserves ambiguous and missing reservations for
review, checkpoints completed rows, and produces a five-column PDF.

## Package

- `SKILL.md` - Kolo entrypoint and operating contract.
- `scripts/parse_ota.py` - Expedia/Booking.com PDF and CSV parser.
- `scripts/browser_adapter.mjs` - authenticated shared-browser automation over CDP.
- `scripts/verify_reservations.py` - matching, Folio 1 calculation, comparison, and checkpoints.
- `scripts/build_report.py` - five-column PDF report generator.
- `references/browser-adapter.md` - browser protocol and configuration.
- `tests/` - deterministic fixtures and unit/integration coverage.
- `SPEC.md` - authoritative business requirements and verified PMS screen details.

## Runtime configuration

Set the property base URL as `OTA_PMS_BASE_URL`. The included adapter uses
`OTA_CDP_ENDPOINT`, defaulting to `http://127.0.0.1:18800`. Kolo should provide
`OTA_PMS_USERNAME` and `OTA_PMS_PASSWORD` as secrets when the shared browser does not
already have an authenticated session. See `SKILL.md` for execution commands.

## Local checks

```text
python -m unittest discover -s tests -v
python scripts/verify_reservations.py --readiness
```

Live PMS behavior must be confirmed manually against an authorized property before
the skill is trusted for production reconciliation.
