# OTA Commission Reconciliation — Specification Package

This repository is a **specification + build brief** for implementing the
`ota-commission-reconciliation` skill. It is intentionally code-free: the
expected outcome is that a coding agent (e.g. OpenAI Codex) reads the spec and
brief and writes the implementation from them.

> **Privacy note:** real guest names, account numbers, and booking numbers have
> been replaced with synthetic examples throughout. No guest PII is present.

## What this skill does

Verify every reservation line on an OTA (Expedia / Booking.com) statement PDF
against the live **Choice Advantage / SkyTouch** PMS, **one reservation at a
time**, by searching the guest's name and reading that reservation's guest
folio. It confirms the numbers on the PDF are accurate and reports a clean
summary table.

## Documents

| File | Purpose |
|---|---|
| [`SPEC.md`](SPEC.md) | The design: goal, process, output, and the **live-verified** grounding of the Choice Advantage search + folio screens (exact URLs, form field names, DOM structure, transaction semantics). |
| [`TASK_BRIEF.md`](TASK_BRIEF.md) | The concrete build contract for the coding agent: files to create, functional requirements, constraints, and the acceptance test. |

## The one-line contract

> Search each guest from the PDF by name in the PMS, open folio 1, read the
> total charged and any "adjustment" lines, compare all PDF fields except
> commission, and emit a simple 5-column PDF table:
> **Guest Name · Booking # · Account # · Total Charged · Notes**.
