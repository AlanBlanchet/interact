#!/usr/bin/env python3
"""Local authenticated prompt catalog used by conversation integration tests."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _Handler(BaseHTTPRequestHandler):
    content: str
    digest: str
    revision: str
    body_revision: str
    token: str

    def do_GET(self) -> None:
        if self.headers.get("authorization") != f"Bearer {self.token}":
            self.send_error(401)
            return
        if self.path == "/v1/catalog":
            payload = {
                "entries": [{
                    "key": {"namespace": "interact", "slug": "system"},
                    "channel": "stable",
                    "revision": self.revision,
                    "digest": self.digest,
                    "lock_version": 1,
                }],
                "server_timestamp": datetime.now(UTC).isoformat(),
            }
        elif self.path == f"/v1/revisions/interact/system/{self.digest}":
            payload = {
                "key": {"namespace": "interact", "slug": "system"},
                "revision": self.body_revision,
                "digest": self.digest,
                "content": self.content,
                "source_commit": "synthetic",
                "created_at": datetime.now(UTC).isoformat(),
            }
        else:
            self.send_error(404)
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port-file", type=Path, required=True)
    parser.add_argument("--content", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--body-revision")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    _Handler.content = args.content
    _Handler.digest = hashlib.sha256(args.content.encode()).hexdigest()
    _Handler.revision = args.revision
    _Handler.body_revision = args.body_revision or args.revision
    _Handler.token = args.token
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    args.port_file.write_text(str(server.server_port))
    server.serve_forever()
