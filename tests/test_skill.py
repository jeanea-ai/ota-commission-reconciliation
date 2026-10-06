import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import parse_ota
import verify_reservations as verify
import build_report


class SkillTests(unittest.TestCase):
    def test_csv_preserves_duplicates_and_range(self):
        text = "Booking #,Guest Name,Check-in,Check-out,Booking amount,Commission amount,Status,Payment type,OTA\n1,Jane Doe,1/2/2026,1/4/2026,110.00,16.50,Stayed,VCC,Expedia\n1,Jane Doe,1/2/2026,1/4/2026,110.00,16.50,Stayed,VCC,Expedia\n"
        rows = parse_ota.parse_csv_text(text)
        self.assertEqual(2, len(rows))
        self.assertEqual([1, 2], [r["source_row"] for r in rows])

    def test_folio_calculation(self):
        total, adjustments, uncertain = verify.classify_folio([
            {"description": "Room Charge", "amount": "100.00"},
            {"description": "Room Tax", "amount": "10.00"},
            {"description": "Visa Payment", "amount": "-110.00"},
            {"description": "Room Adjustment", "amount": "-1.00"},
        ])
        self.assertEqual("109.00", f"{total:.2f}")
        self.assertEqual(1, len(adjustments))
        self.assertFalse(uncertain)

    def test_pms_dates_are_normalized(self):
        self.assertEqual("2026-01-02", verify.normalized_date("1/2/2026"))
        self.assertEqual("2026-01-02", verify.normalized_date("2026-01-02"))

    def test_one_cent_and_unknown_status(self):
        row = {"source_row": 1, "guest_name": "Jane Doe", "booking_number": "B1", "check_in": "2026-01-02", "check_out": "2026-01-04", "status": "Stayed", "original_amount": "110.01"}
        data = {"statement_id": "abc"}
        response = {"reservations": [{"account_number": "1", "guest_name": "Jane Doe", "arrival": "2026-01-02", "departure": "2026-01-04", "status": "Mystery", "folio_1": [{"description": "Room Charge", "amount": "100"}, {"description": "Room Tax", "amount": "10"}]}]}
        result = verify.verify_row(row, data, response, {})
        notes = " ".join(result["notes"])
        self.assertIn("Status needs review", notes)
        self.assertIn("0.01", notes)

    def test_multiple_matches(self):
        row = {"source_row": 1, "guest_name": "Jane Doe", "booking_number": "B1"}
        result = verify.verify_row(row, {"statement_id": "abc"}, {"reservations": [{"account_number": "1"}, {"account_number": "2"}]}, {})
        self.assertIn("1, 2", result["notes"][0])
        self.assertEqual("", result["total_charged"])

    def test_report_has_exact_headers(self):
        data = {"hotel": "ABC", "complete": True, "rows": [{"guest_name": "Jane", "booking_number": "B", "account_number": "A", "total_charged": "1.00", "notes": []}]}
        page = build_report.render_html(data)
        for header in ("Guest Name", "Booking #", "Account #", "Total Charged", "Notes"):
            self.assertEqual(1, page.count(f">{header}<"))

    def test_resume_preserves_duplicate_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            parsed = {"schema_version": 1, "statement_id": "same", "statement_start": "2026-01-02", "statement_end": "2026-01-04", "rows": []}
            for number in (1, 2):
                parsed["rows"].append({"source_row": number, "ota": "Expedia", "booking_number": "B1", "guest_name": "Jane Doe", "check_in": "2026-01-02", "check_out": "2026-01-04", "status": "Stayed", "original_amount": "110.00", "commission_amount": "", "payment_type": ""})
            source = folder / "parsed.json"; source.write_text(json.dumps(parsed), encoding="utf-8")
            fixture = folder / "fixture.json"; fixture.write_text(json.dumps({"Doe": [{"account_number": "A1", "guest_name": "Jane Doe", "arrival": "2026-01-02", "departure": "2026-01-04", "status": "Checked Out", "folio_1": [{"description": "Room Charge", "amount": "100"}, {"description": "Room Tax", "amount": "10"}]}]}), encoding="utf-8")
            statuses = folder / "statuses.json"; statuses.write_text(json.dumps({"Stayed": ["Checked Out"]}), encoding="utf-8")
            output = folder / "results.json"
            env = os.environ.copy(); env["OTA_FIXTURE_RESPONSES"] = str(fixture)
            command = f'"{sys.executable}" "{ROOT / "tests" / "fixture_adapter.py"}"'
            args = [sys.executable, str(ROOT / "scripts" / "verify_reservations.py"), str(source), "--hotel", "ABC", "--output", str(output), "--state-dir", str(folder / "state"), "--status-map", str(statuses), "--command", command]
            first = subprocess.run(args, env=env, capture_output=True, text=True)
            self.assertEqual(0, first.returncode, first.stderr)
            second = subprocess.run(args, env=env, capture_output=True, text=True)
            self.assertEqual(0, second.returncode, second.stderr)
            results = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(2, len(results["rows"]))
            self.assertNotEqual(results["rows"][0]["row_id"], results["rows"][1]["row_id"])


if __name__ == "__main__":
    unittest.main()

