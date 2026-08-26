#!/usr/bin/env python3
"""Local web server for AssureCSV.

The application deliberately uses the Python standard library so a reviewer can
run it in a controlled environment without a JavaScript build chain.
"""

from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import unquote, urlparse

from csv_reviewer import review_package
from csv_reviewer.feedback import FeedbackStore
from csv_reviewer.ingest import parse_request_files
from csv_reviewer.review_store import (
    ReviewCompletionError,
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewStore,
)


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
SAMPLE_ROOT = ROOT / "sample_package"
MAX_REQUEST_BYTES = 32 * 1024 * 1024
FEEDBACK_STORE = FeedbackStore(ROOT / "data" / "reviewer_feedback.json")
REVIEW_STORE = ReviewStore(ROOT / "data" / "reviews")


class AssureCSVHandler(BaseHTTPRequestHandler):
    server_version = "AssureCSV/0.3"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    def _headers(self, status: HTTPStatus, content_type: str, length: int | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _static(self, relative_path: str) -> None:
        relative_path = unquote(relative_path).lstrip("/") or "index.html"
        target = (STATIC_ROOT / relative_path).resolve()
        if STATIC_ROOT.resolve() not in target.parents and target != STATIC_ROOT.resolve():
            self._json({"error": "Invalid path."}, HTTPStatus.BAD_REQUEST)
            return
        if not target.is_file():
            target = STATIC_ROOT / "index.html"
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._headers(HTTPStatus.OK, content_type, len(data))
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json({"status": "ok", "service": "AssureCSV", "version": "0.3.0"})
            return
        if path == "/api/sample":
            files = [
                {"name": item.name, "content": item.read_text(encoding="utf-8"), "encoding": "text"}
                for item in sorted(SAMPLE_ROOT.iterdir())
                if item.is_file() and not item.name.startswith(".")
            ]
            self._json({"package_name": "NovaQMS 2.4 validation package", "files": files})
            return
        if path == "/api/feedback":
            records = FEEDBACK_STORE.load()
            self._json({"count": len(records), "records": records})
            return
        if path == "/api/reviews/latest":
            self._json({"review": REVIEW_STORE.latest()})
            return
        if path.startswith("/api/reviews/"):
            review_id = unquote(path.removeprefix("/api/reviews/")).strip("/")
            try:
                self._json(REVIEW_STORE.load(review_id))
            except ReviewNotFoundError as exc:
                self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        self._static(path)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        path = urlparse(self.path).path
        parts = [unquote(part) for part in path.split("/") if part]
        decision_route = len(parts) == 5 and parts[:2] == ["api", "reviews"] and parts[3] == "findings"
        complete_route = len(parts) == 4 and parts[:2] == ["api", "reviews"] and parts[3] == "complete"
        export_route = len(parts) == 4 and parts[:2] == ["api", "reviews"] and parts[3] == "exports"
        if path not in {"/api/review", "/api/feedback"} and not decision_route and not complete_route and not export_route:
            self._json({"error": "Endpoint not found."}, HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json({"error": "Invalid Content-Length header."}, HTTPStatus.BAD_REQUEST)
            return
        if content_length <= 0:
            self._json({"error": "The request body is empty."}, HTTPStatus.BAD_REQUEST)
            return
        request_limit = MAX_REQUEST_BYTES if path == "/api/review" else 1024 * 1024
        if content_length > request_limit:
            self._json(
                {"error": "The request exceeds the permitted local-review limit."},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        try:
            payload = json.loads(self.rfile.read(content_length))
            if path == "/api/feedback":
                record = FEEDBACK_STORE.add(payload)
                self._json({"status": "recorded", "record": record}, HTTPStatus.CREATED)
            elif decision_route:
                report, finding = REVIEW_STORE.decide(parts[2], parts[4], payload)
                self._record_learning_feedback(report, finding, payload)
                self._json({"status": "saved", "report": report, "finding": finding})
            elif complete_route:
                report = REVIEW_STORE.complete(parts[2], payload)
                self._json({"status": "completed", "report": report})
            elif export_route:
                REVIEW_STORE.record_export(
                    parts[2],
                    str(payload.get("export_type") or "Review export"),
                    str(payload.get("reviewer") or ""),
                )
                self._json({"status": "recorded"}, HTTPStatus.CREATED)
            else:
                documents = parse_request_files(payload)
                result = review_package(
                    documents,
                    str(payload.get("package_name") or "Untitled validation package"),
                    FEEDBACK_STORE.load(),
                )
                self._json(REVIEW_STORE.create(result))
        except ReviewConflictError as exc:
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except ReviewCompletionError as exc:
            self._json({"error": str(exc), "blockers": exc.blockers}, HTTPStatus.CONFLICT)
        except ReviewNotFoundError as exc:
            self._json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - last-resort HTTP boundary
            self.log_error("Review failed: %r", exc)
            self._json(
                {"error": "The review could not be completed. Check the server log for details."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _record_learning_feedback(
        self,
        report: dict[str, object],
        finding: dict[str, object],
        payload: dict[str, object],
    ) -> None:
        """Retain useful Accept/Reject/Modify examples without risking the saved decision."""

        disposition = str(payload.get("disposition") or "")
        mapping = {
            "Accepted": "Accept",
            "Rejected": "Reject",
            "Modified": "Accept with Modification",
        }
        if disposition not in mapping:
            return
        try:
            FEEDBACK_STORE.add(
                {
                    "review_id": report.get("review_id"),
                    "finding": finding,
                    "reviewer_decision": mapping[disposition],
                    "reviewer_rationale": payload.get("reviewer_comment"),
                    "reviewer_name_role": payload.get("reviewer"),
                    "preferred_wording": payload.get("modified_recommendation"),
                    "final_resolution": disposition,
                }
            )
        except ValueError:
            # The authoritative disposition is already safely stored. A
            # learning record is optional and must not invalidate that action.
            return


def main() -> None:
    host = "127.0.0.1"
    port = 8765
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            raise SystemExit("Usage: python3 app.py [port]") from None
    server = ThreadingHTTPServer((host, port), AssureCSVHandler)
    print(f"AssureCSV is available at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping AssureCSV.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
