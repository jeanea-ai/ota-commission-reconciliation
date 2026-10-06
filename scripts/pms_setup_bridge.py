#!/usr/bin/env python3
"""Obtain one exact verified SkyTouch browser handoff from PMS Setup."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


REQUIRED_SETUP_VERSION = "3.5.0"
AUTH_CONTRACT = "skytouch-session-v1"


class SetupBridgeError(RuntimeError):
    pass


def setup_root(explicit: str = "") -> Path:
    candidates = [
        explicit,
        os.getenv("PMS_SETUP_SKILL_DIR", ""),
        str(Path(__file__).resolve().parents[2] / "mf-hotel-pms-setup"),
    ]
    for candidate in candidates:
        if candidate and (Path(candidate) / "tools" / "skytouch_login.py").is_file():
            return Path(candidate).resolve()
    raise SetupBridgeError(
        "Install the official mf-hotel-pms-setup 3.5.0 marketplace package "
        "alongside this skill, or set PMS_SETUP_SKILL_DIR to that package."
    )


def read_build(root: Path) -> dict[str, object]:
    path = root / "BUILD.json"
    if not path.is_file():
        raise SetupBridgeError("PMS Setup BUILD.json is missing")
    try:
        build = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupBridgeError("PMS Setup BUILD.json is unreadable") from exc
    version = str(build.get("version", ""))
    serialized = json.dumps(build).casefold()
    if version != REQUIRED_SETUP_VERSION:
        raise SetupBridgeError(
            f"PMS Setup {REQUIRED_SETUP_VERSION} is required; installed files report {version or 'no version'}"
        )
    if "local" in version.casefold() or "do not install on a pod" in serialized:
        raise SetupBridgeError("PMS Setup is a local-only build; install the official marketplace release")
    return build


def handoff(code: str, *, root_value: str = "", cdp_url: str = "") -> dict[str, object]:
    root = setup_root(root_value)
    read_build(root)
    command = [sys.executable, str(root / "tools" / "skytouch_login.py"), "--code", code, "--handoff"]
    if cdp_url:
        command.extend(["--cdp-url", cdp_url])
    run = subprocess.run(command, capture_output=True, text=True, timeout=90)
    try:
        result = json.loads(run.stdout)
    except json.JSONDecodeError as exc:
        raise SetupBridgeError("PMS Setup returned an unreadable SkyTouch handoff") from exc
    if run.returncode != 0 or result.get("status") == "BLOCKED":
        raise SetupBridgeError(str(result.get("action") or "PMS Setup could not verify SkyTouch access"))
    if result.get("auth_contract") != AUTH_CONTRACT:
        raise SetupBridgeError("PMS Setup returned an unsupported authentication contract")
    if str(result.get("setup_version")) != REQUIRED_SETUP_VERSION:
        raise SetupBridgeError("PMS Setup handoff version does not match its official package")
    if str(result.get("property_code", "")).upper() != code.upper():
        raise SetupBridgeError("PMS Setup returned a different property")
    target_id = str(result.get("target_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", target_id):
        raise SetupBridgeError("PMS Setup did not return a valid SkyTouch browser target")
    return {"property_code": code.upper(), "target_id": target_id, "setup_version": REQUIRED_SETUP_VERSION}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", required=True)
    parser.add_argument("--pms-setup-root", default="")
    parser.add_argument("--cdp-url", default=os.getenv("KOLO_BROWSER_CDP_URL", ""))
    args = parser.parse_args()
    try:
        print(json.dumps({"status": "ready", **handoff(args.code, root_value=args.pms_setup_root, cdp_url=args.cdp_url)}))
        return 0
    except SetupBridgeError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

