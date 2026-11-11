"""Fail unless the Postman collection exercises every operation the API publishes.

    python postman/check_coverage.py http://localhost:8000/openapi.json [collection-dir]

Reads the live OpenAPI document and the generated collection, and matches each
(method, path) of the former against the requests of the latter, treating
``{{variables}}`` in the collection and ``{parameters}`` in OpenAPI as wildcards.
A new endpoint with no request in the collection therefore fails the run, which
is what keeps the suite from quietly going stale.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
METHODS = ("get", "post", "put", "patch", "delete")


def collection_requests(items: list[dict]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for item in items:
        if "item" in item:
            found += collection_requests(item["item"])
            continue
        request = item["request"]
        url = request["url"] if isinstance(request["url"], str) else request["url"]["raw"]
        # Drop the host part: either {{baseUrl}} or an identity's own address.
        path = re.sub(r"^(\{\{\w+\}\}|https?://[^/]+)", "", url).split("?", 1)[0]
        found.append((request["method"].upper(), path))
    return found


def template_matches(template: str, path: str) -> bool:
    pattern = "^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(template)) + "$"
    concrete = re.sub(r"\{\{[^}]+\}\}", "X", path)
    return re.match(pattern, concrete) is not None


def main() -> int:
    spec = json.load(urllib.request.urlopen(sys.argv[1]))
    folder = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE
    collection = json.loads((folder / "zoid-backend.postman_collection.json").read_text("utf-8"))
    requests = collection_requests(collection["item"])
    operations = sorted(
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in METHODS
    )

    missing = [
        (method, path) for method, path in operations
        if not any(m == method and template_matches(path, p) for m, p in requests)
    ]
    print(f"{len(operations)} API operations, {len(requests)} requests in the collection")
    if missing:
        print("NOT COVERED by any request:")
        for method, path in missing:
            print(f"  {method:6} {path}")
        return 1
    print("every operation is exercised")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
