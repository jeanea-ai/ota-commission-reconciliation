#!/usr/bin/env python3
"""Verify parsed OTA rows against a read-only PMS browser adapter."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path


CENT = Decimal("0.01")
PAYMENT_WORDS = ("payment", "deposit", "refund", "visa", "mastercard", "amex", "cash", "check")
ROOM_WORDS = ("room", "lodging", "accommodation", "nightly")
TAX_WORDS = ("tax", "occupancy", "sales tax", "lodging tax", "tourism")


class AdapterError(RuntimeError):
    pass


def default_adapter_command() -> str:
    script = Path(__file__).resolve().parent / "browser_adapter.mjs"
    return json.dumps([os.getenv("NODE_BIN", "node"), str(script)])


def atomic_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def invoke(command: str, request: dict[str, object], timeout: int) -> dict[str, object]:
    if not command:
        raise AdapterError("OTA_PMS_COMMAND is not configured")
    try:
        argv = json.loads(command) if command.lstrip().startswith("[") else shlex.split(command, posix=True)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AdapterError("OTA_PMS_COMMAND is not a valid command or JSON argument array") from exc
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) for part in argv):
        raise AdapterError("OTA_PMS_COMMAND must resolve to a non-empty argument list")
    run = subprocess.run(argv, input=json.dumps(request), text=True,
                         capture_output=True, timeout=timeout)
    try:
        response = json.loads(run.stdout)
    except json.JSONDecodeError as exc:
        if run.returncode != 0:
            raise AdapterError(f"browser adapter exited with code {run.returncode}") from exc
        raise AdapterError("browser adapter returned invalid JSON") from exc
    if run.returncode != 0:
        raise AdapterError(str(response.get("error") or f"browser adapter exited with code {run.returncode}"))
    if not response.get("ok"):
        raise AdapterError(str(response.get("error") or "browser adapter reported failure"))
    return response


def split_name(name: str) -> tuple[str, str]:
    clean = " ".join(name.replace(",", " ").split())
    parts = clean.split()
    if len(parts) < 2:
        return "", clean
    return " ".join(parts[:-1]), parts[-1]


def as_money(value: object) -> Decimal:
    raw = str(value).strip().replace(",", "").replace("$", "")
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("() ")
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid folio amount {value!r}") from exc
    return -result if negative else result


def classify_folio(items: list[dict[str, object]]) -> tuple[Decimal, list[str], list[str]]:
    total = Decimal("0")
    adjustments: list[str] = []
    uncertain: list[str] = []
    for item in items:
        description = str(item.get("description", "")).strip()
        comments = str(item.get("comments", "")).strip()
        combined = f"{description} {comments}".lower()
        amount = as_money(item.get("amount", "0"))
        is_adjustment = "adjustment" in combined
        if is_adjustment:
            adjustments.append(f"{description}: {amount:.2f}")
            if any(word in combined for word in ROOM_WORDS + TAX_WORDS):
                total += amount
            elif any(word in combined for word in PAYMENT_WORDS):
                continue
            else:
                uncertain.append(f"Uncertain room adjustment: {description} {amount:.2f}")
        elif any(word in combined for word in PAYMENT_WORDS):
            continue
        elif amount >= 0 and any(word in combined for word in ROOM_WORDS + TAX_WORDS):
            total += amount
    return total.quantize(CENT), adjustments, uncertain


def load_status_map(path: str) -> dict[str, set[str]]:
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(k).casefold(): {str(v).casefold() for v in values} for k, values in raw.items()}


def equivalent_status(ota_status: str, pms_status: str, mapping: dict[str, set[str]]) -> bool | None:
    allowed = mapping.get(ota_status.casefold())
    if allowed is None:
        return None
    return pms_status.casefold() in allowed


def stable_id(statement_id: str, row: dict[str, object]) -> str:
    material = f"{statement_id}:{row['source_row']}".encode()
    return hashlib.sha256(material).hexdigest()[:24]


def fmt_search_date(value: str) -> str:
    date = dt.date.fromisoformat(value)
    return f"{date.month}/{date.day}/{date.year}"


def normalized_date(value: object) -> str:
    raw = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return raw


def verify_row(row: dict[str, object], data: dict[str, object], response: dict[str, object], status_map: dict[str, set[str]]) -> dict[str, object]:
    reservations = response.get("reservations", [])
    result = {"source_row": row["source_row"], "row_id": stable_id(str(data["statement_id"]), row),
              "guest_name": row["guest_name"], "booking_number": row["booking_number"],
              "account_number": "", "total_charged": "", "notes": [], "needs_attention": False}
    if not reservations:
        result["needs_attention"] = True
        result["notes"].append("Guest not found")
        return result
    if len(reservations) > 1:
        accounts = [str(r.get("account_number", "")).strip() for r in reservations]
        result["needs_attention"] = True
        result["notes"].append("Manual review required - multiple matching reservations. Candidate account numbers: " + ", ".join(a for a in accounts if a))
        return result
    reservation = reservations[0]
    result["account_number"] = str(reservation.get("account_number", ""))
    if str(reservation.get("guest_name", "")).casefold().strip() != str(row["guest_name"]).casefold().strip():
        result["notes"].append(f"Guest name differs: PMS shows {reservation.get('guest_name', '')}")
    for label, source_key, pms_key in (("Arrival", "check_in", "arrival"), ("Departure", "check_out", "departure")):
        if normalized_date(row[source_key]) != normalized_date(reservation.get(pms_key, "")):
            result["notes"].append(f"{label} differs: statement {row[source_key]}, PMS {reservation.get(pms_key, '')}")
    status_ok = equivalent_status(str(row["status"]), str(reservation.get("status", "")), status_map)
    if status_ok is None:
        result["notes"].append(f"Status needs review: statement {row['status']}, PMS {reservation.get('status', '')}")
    elif not status_ok:
        result["notes"].append(f"Status differs: statement {row['status']}, PMS {reservation.get('status', '')}")
    total, adjustments, uncertain = classify_folio(list(reservation.get("folio_1", [])))
    result["total_charged"] = f"{total:.2f}"
    if adjustments:
        result["notes"].append("Adjustments - " + "; ".join(adjustments))
    result["notes"].extend(uncertain)
    difference = abs(total - Decimal(str(row["original_amount"])))
    if difference >= CENT:
        result["notes"].append(f"Amount differs by {difference:.2f}: statement {row['original_amount']}, PMS {total:.2f}")
    result["needs_attention"] = bool(result["notes"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("--hotel")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--command", default=os.getenv("OTA_PMS_COMMAND", default_adapter_command()))
    parser.add_argument("--base-url", default=os.getenv("OTA_PMS_BASE_URL", ""))
    parser.add_argument("--status-map", default=os.getenv("OTA_STATUS_MAP", ""))
    parser.add_argument("--state-dir", type=Path, default=Path(os.getenv("OTA_STATE_DIR", ".state/ota-commission-reconciliation")))
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--doctor", "--readiness", dest="doctor", action="store_true")
    args = parser.parse_args()
    if args.doctor:
        try:
            response = invoke(args.command, {"action": "doctor", "base_url": args.base_url}, args.timeout)
            print(json.dumps({"ready": bool(response.get("authenticated")), "pms": response.get("pms", "unknown")}))
            return 0 if response.get("authenticated") else 2
        except (AdapterError, subprocess.TimeoutExpired) as exc:
            print(json.dumps({"ready": False, "error": str(exc)}))
            return 2
    if not args.input or not args.output or not args.hotel:
        parser.error("input, --hotel, and --output are required unless --doctor is used")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    state_path = args.state_dir / f"{args.hotel}-{data['statement_id']}.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"schema_version": 1, "hotel": args.hotel, "statement_id": data["statement_id"], "results": {}}
    status_map = load_status_map(args.status_map)
    blocking_error = ""
    for row in data["rows"]:
        row_id = stable_id(str(data["statement_id"]), row)
        if row_id in state["results"]:
            continue
        first, last = split_name(str(row["guest_name"]))
        request = {"action": "search_reservations", "base_url": args.base_url, "first_name": first, "last_name": last,
                   "arrival_from": fmt_search_date(str(data["statement_start"])), "arrival_to": fmt_search_date(str(data["statement_end"]))}
        try:
            response = invoke(args.command, request, args.timeout)
            result = verify_row(row, data, response, status_map)
        except (AdapterError, subprocess.TimeoutExpired) as exc:
            blocking_error = str(exc)
            break
        except (ValueError, KeyError, TypeError) as exc:
            result = {"source_row": row["source_row"], "row_id": row_id, "guest_name": row["guest_name"],
                      "booking_number": row["booking_number"], "account_number": "", "total_charged": "",
                      "notes": [f"Processing failure: {exc}"], "needs_attention": True}
        state["results"][row_id] = result
        atomic_json(state_path, state)
    ordered = [state["results"][stable_id(str(data["statement_id"]), row)] for row in data["rows"] if stable_id(str(data["statement_id"]), row) in state["results"]]
    output = {"schema_version": 1, "hotel": args.hotel, "statement_id": data["statement_id"],
              "statement_start": data["statement_start"], "statement_end": data["statement_end"],
              "complete": len(ordered) == len(data["rows"]), "source_row_count": len(data["rows"]),
              "completed_row_count": len(ordered), "blocking_error": blocking_error, "rows": ordered}
    atomic_json(args.output, output)
    print(json.dumps({"output": str(args.output), "completed": len(ordered), "total": len(data["rows"]), "complete": output["complete"], "blocked": bool(blocking_error)}))
    return 0 if output["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

