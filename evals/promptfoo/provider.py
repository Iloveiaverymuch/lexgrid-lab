"""promptfoo provider for the lexgrid REST API (stdlib only, so any python3 can run it).

Test vars: endpoint (search | ask), key (API key or empty), jurisdictions ("EU,FR"), mode, k.
Returns the HTTP status and the JSON body, so assertions can test refusals (401/403) as well as results.
The base URL comes from LEXGRID_URL (default http://127.0.0.1:8000).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    v = context.get("vars", {})
    endpoint = v.get("endpoint", "search")
    body: dict[str, Any] = {"question": prompt} if endpoint == "ask" else {"query": prompt}
    if endpoint == "search":
        body["mode"] = v.get("mode", "hybrid_rrf_rerank")
        body["k"] = int(v.get("k", 10))
    # A comma-separated string ("EU,FR,DE"): promptfoo would expand a list var into one test per element.
    if v.get("jurisdictions"):
        body["jurisdictions"] = [j.strip() for j in str(v["jurisdictions"]).split(",") if j.strip()]
    headers = {"Content-Type": "application/json"}
    if v.get("key"):
        headers["X-API-Key"] = v["key"]
    url = os.environ.get("LEXGRID_URL", "http://127.0.0.1:8000").rstrip("/") + "/" + endpoint
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as err:  # 401/403 are results to assert on, not provider errors
        status, raw = err.code, err.read()
    except urllib.error.URLError as err:
        return {"error": f"lexgrid API not reachable at {url}: {err.reason}"}
    try:
        payload = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        payload = {"raw": raw.decode(errors="replace")}
    return {"output": {"status": status, "body": payload}}
