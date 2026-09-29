#!/usr/bin/env python3
"""End-to-end smoke test of the running product through its public address (Docker CI job, or any deployment).

    python tools/ci/docker_smoke.py --base-url http://localhost:8080 --package smoke.zip [--timeout 900]

Stdlib only. Steps: home page, API health, login as the demo inspector, upload limits, a body larger than nginx's
default 1 MiB reaching the API, upload of the package, polling the process until READY, the protocol, and a page image
of an uploaded file through the proxy. Exit 0 = everything passed, 1 = a check failed (the reason is printed).
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Smoke:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.csrf: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        timeout: float = 60,
    ) -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(self.base + path, data=body, method=method)
        if content_type:
            req.add_header("Content-Type", content_type)
        if self.csrf and method not in ("GET", "HEAD"):
            req.add_header("X-CSRF-Token", self.csrf)
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read()

    def json(self, method: str, path: str, payload: Any | None = None, **kw: Any) -> tuple[int, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        status, headers, raw = self.request(
            method, path, body=body, content_type="application/json" if body else None, **kw
        )
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, {
                "_raw": raw[:300].decode("utf-8", "replace"),
                "_content_type": headers.get("content-type"),
            }


def multipart(parts: list[tuple[str, str | None, bytes]]) -> tuple[bytes, str]:
    boundary = "----smoke" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, filename, data in parts:
        disposition = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        chunks.append(f"--{boundary}\r\nContent-Disposition: {disposition}\r\n".encode())
        if filename:
            chunks.append(b"Content-Type: application/octet-stream\r\n")
        chunks.append(b"\r\n" + data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    print(f"ok    {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--package", required=True, help="zip with the folders пд/ and рд/")
    parser.add_argument("--login", default="inspector")
    parser.add_argument("--password", default="Demo-Inspector-2026")
    parser.add_argument(
        "--skip-web", action="store_true", help="the base URL is the API itself (no static site)"
    )
    parser.add_argument(
        "--timeout", type=int, default=900, help="seconds to wait for the process to become READY"
    )
    args = parser.parse_args()
    smoke = Smoke(args.base_url)

    if not args.skip_web:
        status, headers, raw = smoke.request("GET", "/")
        check(status == 200 and b'id="root"' in raw, "web: GET / serves the single-page application")
        status, _, _ = smoke.request("GET", "/some/client/route")
        check(status == 200, "web: unknown paths fall back to index.html")

    status, health = smoke.json("GET", "/api/v1/health")
    check(
        status == 200 and health.get("status") == "ok", f"api: /api/v1/health through the proxy -> {health}"
    )

    status, me = smoke.json("GET", "/api/v1/auth/me")
    check(status == 401, "api: a request without a session is refused (auth is on)")

    status, login = smoke.json("POST", "/api/v1/auth/login", {"login": args.login, "password": args.password})
    check(status == 200 and login.get("csrf_token"), f"api: login as {args.login}")
    smoke.csrf = login["csrf_token"]
    status, me = smoke.json("GET", "/api/v1/auth/me")
    check(status == 200 and me.get("user", {}).get("login") == args.login, "api: the session cookie works")

    status, limits = smoke.json("GET", "/api/v1/documents/upload/limits")
    check(status == 200 and limits.get("max_file_bytes") == 500 * 1024 * 1024, f"api: upload limits {limits}")

    # A 2 MiB body must reach the API (nginx defaults to 1 MiB): the API refuses the content, not nginx.
    body, ctype = multipart([("files", "pad.txt", b"x" * (2 * 1024 * 1024))])
    status, headers, raw = smoke.request("POST", "/api/v1/documents/upload", body=body, content_type=ctype)
    check(
        status in (400, 415, 422) and "problem+json" in headers.get("content-type", ""),
        f"proxy: a 2 MiB body reaches the API (got {status}, {headers.get('content-type')})",
    )

    with open(args.package, "rb") as fh:
        package = fh.read()
    body, ctype = multipart(
        [
            ("files", "smoke.zip", package),
            ("object_name", None, b"Docker smoke"),
            ("address", None, "г. Тюмень, ул. Тестовая, д. 5".encode()),
        ]
    )
    status, headers, raw = smoke.request(
        "POST", "/api/v1/documents/upload", body=body, content_type=ctype, timeout=300
    )
    check(status == 202, f"upload: package accepted (HTTP {status}) {raw[:200].decode('utf-8', 'replace')}")
    upload = json.loads(raw)
    pid = upload["process_id"]
    print(
        f"      process {pid}, object {upload['object_id']}, queue {upload['queue']}, rejected {upload['rejected']}"
    )
    check(bool(upload["accepted"]), "upload: at least one file accepted")

    deadline = time.monotonic() + args.timeout
    last = ""
    detail: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, detail = smoke.json("GET", f"/api/v1/processes/{pid}")
        if status != 200:
            fail(f"process: status endpoint answered HTTP {status}")
        state = f"{detail['status']} stage={detail.get('stage')} progress={detail.get('progress')}"
        if state != last:
            print(f"      {time.strftime('%H:%M:%S')} {state}")
            last = state
        if detail["status"] in ("READY", "FAILED"):
            break
        time.sleep(5)
    if detail.get("status") != "READY":
        for entry in detail.get("log", [])[-25:]:
            print(f"      log[{entry['level']}] {entry['message']}", file=sys.stderr)
        fail(f"process did not become READY (status {detail.get('status')}, error {detail.get('error')})")
    check(True, f"process: READY, {detail['files_total']} files, {detail['pages_total']} pages")

    stages = {f.get("stage") for f in detail["files"] if f.get("status") == "DONE"}
    check(
        {"PD", "RD"} <= stages,
        f"process: stages recognised from the folder names ({sorted(s for s in stages if s)})",
    )

    vpid = detail.get("verification_process_id")
    check(
        bool(vpid) and bool(detail.get("protocol")),
        f"process: protocol registered (verification process {vpid})",
    )
    status, protocol = smoke.json("GET", f"/api/v1/processes/{vpid}/protocol")
    check(
        status == 200 and isinstance(protocol, dict) and protocol,
        f"api: GET /processes/{vpid}/protocol -> {status}",
    )
    print(f"      protocol keys: {sorted(protocol)[:8]}")

    pdf = next(
        f for f in detail["files"] if f.get("file_id") and f.get("status") == "DONE" and f.get("pages")
    )
    status, headers, raw = smoke.request("GET", f"/api/v1/files/{pdf['file_id']}/pages/1/image", timeout=120)
    check(
        status == 200
        and headers.get("content-type", "").startswith("image/png")
        and raw.startswith(PNG_SIGNATURE),
        f"ml-api through api and nginx: page 1 of {pdf['name']} is image/png ({len(raw)} bytes)",
    )
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
