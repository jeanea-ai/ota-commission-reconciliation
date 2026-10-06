#!/usr/bin/env python3
"""Parse Expedia or Booking.com statement PDFs/CSVs into normalized JSON."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path


DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y")
MONEY_RE = re.compile(r"^\(?\s*[$€£]?\s*[-+]?\d[\d,]*(?:\.\d{1,2})?\s*\)?$")
DATE_RE = re.compile(r"\b(?:\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})|\d{4}-\d{2}-\d{2})\b")


def parse_date(value: str) -> dt.date:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unsupported date: {value!r}")


def money(value: str) -> str:
    raw = value.strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("() ")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Unsupported amount: {value!r}") from exc
    if negative:
        amount = -amount
    return f"{amount.quantize(Decimal('0.01')):.2f}"


def detect_ota(text: str) -> str:
    lower = text.lower()
    if "booking.com" in lower or "booking number" in lower:
        return "Booking.com"
    if "expedia" in lower or "booknumber" in lower:
        return "Expedia"
    return "Unknown"


def normalize_row(raw: dict[str, str], row_number: int, ota_hint: str = "") -> dict[str, object]:
    keys = {re.sub(r"[^a-z0-9]", "", k.lower()): (v or "").strip() for k, v in raw.items()}
    def pick(*names: str) -> str:
        return next((keys.get(re.sub(r"[^a-z0-9]", "", n.lower()), "") for n in names if keys.get(re.sub(r"[^a-z0-9]", "", n.lower()), "")), "")
    booking = pick("Booking #", "BookNumber", "Booking number", "Reservation number", "Reservation ID")
    guest = pick("Guest Name", "GuestName", "Guest")
    checkin = parse_date(pick("Check-in", "CheckIn", "Arrival", "Arrival date"))
    checkout = parse_date(pick("Check-out", "CheckOut", "Departure", "Departure date"))
    amount = money(pick("Booking amount", "OriginalAmountUSD", "Original amount", "Reservation amount", "Amount"))
    commission_raw = pick("Commission amount", "CommissionAmountUSD", "Commission")
    return {
        "source_row": row_number,
        "ota": pick("OTA") or ota_hint or "Unknown",
        "booking_number": booking,
        "guest_name": guest,
        "check_in": checkin.isoformat(),
        "check_out": checkout.isoformat(),
        "status": pick("Status", "Result") or "Unknown",
        "original_amount": amount,
        "commission_amount": money(commission_raw) if commission_raw else "",
        "payment_type": pick("Payment type"),
    }


def parse_csv_text(text: str, ota_hint: str = "") -> list[dict[str, object]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("CSV has no header")
    rows = []
    errors = []
    for number, raw in enumerate(reader, 1):
        if not any((v or "").strip() for v in raw.values()):
            continue
        try:
            rows.append(normalize_row(raw, number, ota_hint))
        except ValueError as exc:
            errors.append(f"row {number}: {exc}")
    if errors:
        raise ValueError("Unable to parse statement rows: " + "; ".join(errors[:10]))
    if not rows:
        raise ValueError("No statement rows found")
    return rows


def table_text_to_csv(text: str) -> str:
    """Convert common fixed-width OTA tables to the canonical CSV shape.

    This deliberately refuses ambiguous lines instead of guessing. Statements with
    an unrecognized layout should be exported to the documented CSV format.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Booking #", "Guest Name", "Check-in", "Check-out", "Booking amount", "Commission amount", "Status", "Payment type", "OTA"])
    ota = detect_ota(text)
    found = 0
    for line in text.splitlines():
        dates = list(DATE_RE.finditer(line))
        if len(dates) < 2:
            continue
        before = line[:dates[0].start()].strip()
        after = line[dates[1].end():].strip()
        prefix = re.match(r"^(\S+)\s+(.+?)$", before)
        if not prefix:
            continue
        tokens = after.split()
        money_indexes = [i for i, token in enumerate(tokens) if MONEY_RE.match(token)]
        if len(money_indexes) < 1:
            continue
        first_money = money_indexes[0]
        second_money = money_indexes[1] if len(money_indexes) > 1 else None
        status = " ".join(tokens[:first_money]).strip() or "Unknown"
        amount = tokens[first_money]
        commission = tokens[second_money] if second_money is not None else ""
        writer.writerow([prefix.group(1), prefix.group(2), dates[0].group(), dates[1].group(), amount, commission, status, "", ota])
        found += 1
    if not found:
        raise ValueError("No recognizable Expedia or Booking.com rows found; export the statement to the supported CSV format")
    return output.getvalue()


def extract_pdf(path: Path, pdftotext: str) -> str:
    with tempfile.TemporaryDirectory(prefix="ota-parse-") as tmp:
        target = Path(tmp) / "statement.txt"
        run = subprocess.run([pdftotext, "-layout", str(path), str(target)], capture_output=True, text=True, timeout=120)
        if run.returncode != 0:
            raise RuntimeError(f"pdftotext failed: {run.stderr.strip()}")
        return target.read_text(encoding="utf-8", errors="replace")


def package(rows: list[dict[str, object]], source: Path) -> dict[str, object]:
    statement_id = hashlib.sha256(source.read_bytes()).hexdigest()
    arrivals = [parse_date(str(row["check_in"])) for row in rows]
    departures = [parse_date(str(row["check_out"])) for row in rows]
    return {
        "schema_version": 1,
        "statement_id": statement_id,
        "source_name": source.name,
        "statement_start": min(arrivals).isoformat(),
        "statement_end": max(departures).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pdftotext", default="pdftotext")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input does not exist: {args.input}")
    if args.input.suffix.lower() == ".csv":
        text = args.input.read_text(encoding="utf-8-sig")
        rows = parse_csv_text(text)
    elif args.input.suffix.lower() == ".pdf":
        extracted = extract_pdf(args.input, args.pdftotext)
        rows = parse_csv_text(table_text_to_csv(extracted), detect_ota(extracted))
    else:
        parser.error("input must be .pdf or .csv")
    data = package(rows, args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "rows": len(rows), "statement_id": data["statement_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

