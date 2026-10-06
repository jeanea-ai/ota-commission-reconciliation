#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

request = json.load(sys.stdin)
if request["action"] == "doctor":
    print(json.dumps({"ok": True, "authenticated": True, "pms": "fixture"}))
    raise SystemExit(0)
data = json.loads(Path(os.environ["OTA_FIXTURE_RESPONSES"]).read_text(encoding="utf-8"))
print(json.dumps({"ok": True, "reservations": data.get(request["last_name"], [])}))

