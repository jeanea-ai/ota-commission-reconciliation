#!/usr/bin/env python3
"""Build the five-column OTA reconciliation PDF with headless Chromium."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def browser_path(explicit: str = "") -> str:
    candidates = [explicit, os.getenv("CHROME_BIN", ""), shutil.which("chromium") or "", shutil.which("google-chrome") or "",
                  shutil.which("chrome") or "", shutil.which("msedge") or "",
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    return next((p for p in candidates if p and Path(p).is_file()), "")


def month_label(start: str, end: str) -> str:
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    a, b = first.strftime("%Y-%m"), last.strftime("%Y-%m")
    return a if a == b else f"{a}_to_{b}"


def render_html(data: dict[str, object]) -> str:
    rows = []
    for row in data["rows"]:
        notes = "; ".join(str(n) for n in row.get("notes", []))
        values = [row.get("guest_name", ""), row.get("booking_number", ""), row.get("account_number", ""), row.get("total_charged", ""), notes]
        rows.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in values) + "</tr>")
    partial = " - PARTIAL" if not data.get("complete") else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: landscape; margin: 12mm; }} body {{ font-family: Arial, sans-serif; font-size: 9pt; color:#111; }}
h1 {{ font-size:15pt; margin:0 0 4mm; }} table {{ width:100%; border-collapse:collapse; table-layout:fixed; }}
thead {{ display:table-header-group; }} th,td {{ border:1px solid #777; padding:5px; text-align:left; vertical-align:top; overflow-wrap:anywhere; }}
th {{ background:#eee; }} th:nth-child(1){{width:18%}} th:nth-child(2){{width:14%}} th:nth-child(3){{width:12%}} th:nth-child(4){{width:12%}} th:nth-child(5){{width:44%}}
</style></head><body><h1>OTA Reconciliation - {html.escape(str(data['hotel']))}{partial}</h1>
<table><thead><tr><th>Guest Name</th><th>Booking #</th><th>Account #</th><th>Total Charged</th><th>Notes</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--browser", default="")
    parser.add_argument("--keep-html", action="store_true")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-partial" if not data.get("complete") else ""
    stem = f"{data['hotel']}-{month_label(data['statement_start'], data['statement_end'])}{suffix}"
    html_path = (args.output_dir / f"{stem}.html").resolve()
    pdf_path = (args.output_dir / f"{stem}.pdf").resolve()
    html_path.write_text(render_html(data), encoding="utf-8")
    browser = browser_path(args.browser)
    if not browser:
        raise RuntimeError("Chromium browser not found; set CHROME_BIN or pass --browser")
    with tempfile.TemporaryDirectory(prefix="ota-report-profile-") as profile:
        run = subprocess.run([browser, "--headless=new", "--disable-gpu", "--disable-software-rasterizer",
                              "--disable-extensions", "--no-first-run", f"--user-data-dir={profile}",
                              "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                             capture_output=True, text=True, timeout=120)
    if run.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError(f"Chromium PDF generation failed: {run.stderr.strip()}")
    if not args.keep_html:
        html_path.unlink(missing_ok=True)
    print(json.dumps({"output": str(pdf_path), "rows": len(data["rows"]), "complete": bool(data.get("complete"))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

