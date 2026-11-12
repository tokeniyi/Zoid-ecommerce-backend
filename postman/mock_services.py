"""Local stand-ins for the outside world (Paystack and S3), for end-to-end API tests.

Standard library only.

    python postman/mock_services.py [port]        # default 9100

It speaks just the three calls the backend's Paystack adapter makes, with the same
request and response shapes, so the real payment endpoints run for real:

    POST /transaction/initialize        start a payment, returns a checkout URL
    GET  /transaction/verify/{ref}      "pending" until paid, then "success"
    POST /transaction/{ref}/refund      refund a paid payment (all or part)

Real Paystack needs a customer to pay on its hosted page. Tests stand in for that
customer with two extra, clearly-marked routes:

    POST /__mock/pay/{ref}[?amount=<kobo>]   the customer pays (optionally the
                                             wrong amount, to test the safety check)
    POST /__mock/reset                       forget everything
    GET  /__mock/health                      liveness

Like Paystack it insists on ``Authorization: Bearer <secret key>``.

The same process also plays a minimal S3-compatible object store, so image uploads
run for real too: ``PUT /{bucket}/{key}`` keeps the bytes and ``GET /{bucket}/{key}``
serves them back with the stored ``Content-Type`` (so a test can fetch the URL the
API returns). It understands the ``aws-chunked`` framing recent boto versions use.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PAYMENTS: dict[str, dict] = {}
OBJECTS: dict[str, tuple[bytes, str]] = {}  # "bucket/key" -> (bytes, content type)
LOCK = threading.Lock()


def decode_aws_chunked(raw: bytes) -> bytes:
    """Strip S3's ``aws-chunked`` framing: hex-size lines, each followed by that many bytes."""
    out, pos = bytearray(), 0
    while pos < len(raw):
        end = raw.index(b"\r\n", pos)
        size = int(raw[pos:end].split(b";")[0], 16)
        pos = end + 2
        if size == 0:
            break
        out += raw[pos : pos + size]
        pos += size + 2
    return bytes(out)


class Handler(BaseHTTPRequestHandler):
    server_version = "MockServices/1.0"

    # ── plumbing ────────────────────────────────────────────────────
    def log_message(self, fmt: str, *args: object) -> None:  # quiet, one line per call
        sys.stderr.write(f"[mock-services] {self.command} {self.path} -> {self._status}\n")

    _status = 0

    def _send(self, status: int, body: dict) -> None:
        self._status = status
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
        self._status = status
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    def _authorised(self) -> bool:
        if not (self.headers.get("Authorization") or "").startswith("Bearer sk_"):
            self._send(401, {"status": False, "message": "Invalid key"})
            return False
        return True

    # ── routes ──────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/__mock/health":
            return self._send(
                200, {"status": True, "payments": len(PAYMENTS), "objects": len(OBJECTS)}
            )
        match = re.fullmatch(r"/transaction/verify/([^/]+)", path)
        if match:
            if not self._authorised():
                return None
            with LOCK:
                payment = PAYMENTS.get(match.group(1))
            if payment is None:
                message = "Transaction reference not found"
                return self._send(404, {"status": False, "message": message})
            return self._send(200, {
                "status": True, "message": "Verification successful",
                "data": {
                    "status": "success" if payment["paid"] else "pending",
                    "reference": payment["reference"],
                    "amount": payment["paid_amount"] if payment["paid"] else payment["amount"],
                    "currency": payment["currency"],
                    "gateway_reference": f"MOCK-{payment['reference']}",
                },
            })
        stored = OBJECTS.get(path.lstrip("/"))
        if stored is not None:
            return self._send_bytes(200, *stored)
        return self._send(404, {"status": False, "message": "Not found"})

    def do_PUT(self) -> None:  # noqa: N802
        """S3 PutObject: keep the bytes under ``bucket/key``."""
        path = urlparse(self.path).path.lstrip("/")
        if "/" not in path:
            return self._send(400, {"status": False, "message": "No key"})
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        sha = self.headers.get("x-amz-content-sha256", "")
        encoding = self.headers.get("Content-Encoding", "")
        if sha.startswith("STREAMING") or "aws-chunked" in encoding:
            raw = decode_aws_chunked(raw)
        with LOCK:
            OBJECTS[path] = (raw, self.headers.get("Content-Type", "application/octet-stream"))
        self._status = 200
        self.send_response(200)
        self.send_header("ETag", '"mock-etag"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return None

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        path = url.path
        if path == "/__mock/reset":
            with LOCK:
                PAYMENTS.clear()
                OBJECTS.clear()
            return self._send(200, {"status": True})
        paid = re.fullmatch(r"/__mock/pay/([^/]+)", path)
        if paid:
            with LOCK:
                payment = PAYMENTS.get(paid.group(1))
                if payment is None:
                    return self._send(404, {"status": False, "message": "Unknown reference"})
                override = parse_qs(url.query).get("amount")
                payment["paid"] = True
                payment["paid_amount"] = int(override[0]) if override else payment["amount"]
            return self._send(200, {"status": True, "paid_amount": payment["paid_amount"]})

        if not self._authorised():
            return None
        body = self._json()
        if path == "/transaction/initialize":
            reference, amount = body.get("reference"), body.get("amount")
            if not reference or not isinstance(amount, int) or amount <= 0 or not body.get("email"):
                return self._send(400, {"status": False, "message": "Invalid request payload"})
            with LOCK:
                PAYMENTS[reference] = {
                    "reference": reference, "amount": amount, "paid_amount": amount,
                    "currency": body.get("currency", "NGN"), "paid": False, "refunded": 0,
                }
            return self._send(200, {
                "status": True, "message": "Authorization URL created",
                "data": {
                    "authorization_url": f"https://checkout.mock-paystack.test/{reference}",
                    "access_code": f"AC_{reference[-8:]}", "reference": reference,
                },
            })
        refund = re.fullmatch(r"/transaction/([^/]+)/refund", path)
        if refund:
            with LOCK:
                payment = PAYMENTS.get(refund.group(1))
                if payment is None or not payment["paid"]:
                    return self._send(400, {"status": False, "message": "Transaction not paid"})
                amount = body.get("amount") or payment["paid_amount"] - payment["refunded"]
                payment["refunded"] += amount
            return self._send(200, {
                "status": True, "message": "Refund has been queued for processing",
                "data": {"status": "processed", "amount": amount, "id": 4242},
            })
        return self._send(404, {"status": False, "message": "Not found"})


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[mock-services] listening on http://127.0.0.1:{port}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
