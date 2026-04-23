from __future__ import annotations

import json
import mimetypes
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

from repo_harness_lab.config.settings import Settings
from repo_harness_lab.runtime.portal_live import (
    PortalLiveEntryConfig,
    build_live_entry_payload,
    build_live_page_state,
    preview_live_portal_submission,
    render_live_portal_html,
    run_live_portal_submission,
)
from repo_harness_lab.shared.ids import new_id

_PORTAL_ASYNC_POLL_AFTER_MS = 1500
_PORTAL_ASYNC_JOB_LIMIT = 64


@dataclass(slots=True)
class _PortalAsyncRunJob:
    job_id: str
    submission: dict[str, object]
    status: str = "pending"
    current_phase: str = "queued"
    status_text: str = "\u4efb\u52a1\u5df2\u63d0\u4ea4\uff0c\u6b63\u5728\u6392\u961f ..."
    result: dict[str, object] | None = None
    error: str | None = None


class _PortalAsyncRunStore:
    def __init__(self, *, settings: Settings, live_entry: PortalLiveEntryConfig) -> None:
        self._settings = settings
        self._live_entry = live_entry
        self._jobs: dict[str, _PortalAsyncRunJob] = {}
        self._lock = threading.Lock()

    def submit(self, submission: dict[str, object]) -> dict[str, object]:
        job_id = new_id("portal-job")
        job = _PortalAsyncRunJob(job_id=job_id, submission=dict(submission))
        with self._lock:
            self._jobs[job_id] = job
            accepted_payload = self._payload_for_job(job)
            self._trim_jobs_locked()
        worker = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        worker.start()
        return accepted_payload

    def get(self, job_id: str) -> dict[str, object]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return self._payload_for_job(job)

    def _run_job(self, job_id: str) -> None:
        submission: dict[str, object]
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.current_phase = "prepare"
            job.status_text = "\u6b63\u5728\u540e\u53f0\u51c6\u5907\u4efb\u52a1 ..."
            submission = dict(job.submission)
        try:
            result = run_live_portal_submission(
                settings=self._settings,
                live_entry=self._live_entry,
                submission=submission,
                progress_callback=lambda phase, message: self._update_job_progress(
                    job_id,
                    current_phase=phase,
                    status_text=message,
                ),
            )
        except Exception as exc:  # pragma: no cover - exercised through status payloads
            with self._lock:
                failed_job = self._jobs.get(job_id)
                if failed_job is None:
                    return
                failed_job.status = "failed"
                failed_job.current_phase = "failed"
                failed_job.status_text = "\u540e\u53f0\u8fd0\u884c\u5931\u8d25\uff0c\u8bf7\u67e5\u770b\u9519\u8bef\u4fe1\u606f\u3002"
                failed_job.error = str(exc)
            return
        with self._lock:
            succeeded_job = self._jobs.get(job_id)
            if succeeded_job is None:
                return
            succeeded_job.status = "succeeded"
            succeeded_job.current_phase = str(result.get("current_phase") or "completed")
            succeeded_job.status_text = str(result.get("status_text") or "\u8fd0\u884c\u5df2\u5b8c\u6210\u3002")
            succeeded_job.result = result

    def _payload_for_job(self, job: _PortalAsyncRunJob) -> dict[str, object]:
        base_payload: dict[str, object] = {
            "job_id": job.job_id,
            "job_status": job.status,
            "current_phase": job.current_phase,
            "poll_after_ms": _PORTAL_ASYNC_POLL_AFTER_MS,
        }
        if job.status in {"pending", "running"}:
            return {
                "ok": True,
                **base_payload,
                "done": False,
                "status_text": job.status_text,
            }
        if job.status == "failed":
            return {
                "ok": False,
                **base_payload,
                "done": True,
                "status_text": job.status_text,
                "error": job.error or "portal run failed",
            }
        payload = {
            "ok": True,
            **base_payload,
            "done": True,
        }
        if job.result:
            payload.update(job.result)
        return payload

    def _update_job_progress(self, job_id: str, *, current_phase: str, status_text: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in {"failed", "succeeded"}:
                return
            job.status = "running"
            job.current_phase = current_phase
            job.status_text = status_text

    def _trim_jobs_locked(self) -> None:
        overflow = len(self._jobs) - _PORTAL_ASYNC_JOB_LIMIT
        if overflow <= 0:
            return
        removable_job_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in {"succeeded", "failed"}
        ]
        for job_id in removable_job_ids[:overflow]:
            self._jobs.pop(job_id, None)


def build_portal_http_server(
    *,
    settings: Settings,
    live_entry: PortalLiveEntryConfig,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    async_job_store = _PortalAsyncRunStore(settings=settings, live_entry=live_entry)

    class PortalRequestHandler(BaseHTTPRequestHandler):
        server_version = "RepoHarnessPortal/1.0"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            path = parsed.path or "/"
            if path in {"/", "/harness-portal.html"}:
                state = build_live_page_state(settings=settings, live_entry=live_entry)
                self._send_html(render_live_portal_html(state))
                return
            if path == "/api/config":
                payload = {"ok": True, **build_live_entry_payload(live_entry)}
                self._send_json(payload)
                return
            if path == "/api/run-demo-status":
                job_id = str(parse_qs(parsed.query).get("job_id", [""])[0]).strip()
                if not job_id:
                    self._send_json({"ok": False, "error": "missing job_id"}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    payload = async_job_store.get(job_id)
                except KeyError:
                    self._send_json({"ok": False, "error": "job not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                status = HTTPStatus.ACCEPTED if payload.get("done") is False else HTTPStatus.OK
                self._send_json(payload, status=status)
                return
            self._serve_static(path)

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path or "/"
            if path not in {"/api/run-demo", "/api/run-demo-async", "/api/preview-demo"}:
                self._send_json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                payload = json.loads(raw_body.decode("utf8") or "{}")
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "invalid json body"}, status=HTTPStatus.BAD_REQUEST)
                return

            if path == "/api/run-demo-async":
                result = async_job_store.submit(payload)
                self._send_json(result, status=HTTPStatus.ACCEPTED)
                return

            try:
                if path == "/api/preview-demo":
                    result = preview_live_portal_submission(
                        live_entry=live_entry,
                        submission=payload,
                        settings=settings,
                    )
                else:
                    result = run_live_portal_submission(
                        settings=settings,
                        live_entry=live_entry,
                        submission=payload,
                    )
            except ValueError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            except FileNotFoundError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                return
            except RuntimeError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            except Exception as exc:  # pragma: no cover - defensive outer guard for server responses
                self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            self._send_json(result)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _serve_static(self, request_path: str) -> None:
            if request_path.startswith("/runs/"):
                relative_path = request_path.removeprefix("/runs/")
                file_path = _resolve_static_path(settings.paths.runs_dir, relative_path)
            else:
                relative_path = request_path.removeprefix("/")
                file_path = _resolve_static_path(settings.paths.reports_dir, relative_path)
            if file_path is None:
                self._send_json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            media_type, _ = mimetypes.guess_type(str(file_path))
            body = file_path.read_bytes()
            self._send_bytes(body, media_type or "application/octet-stream")

        def _send_html(self, markup: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(markup.encode("utf8"), "text/html; charset=utf-8", status=status)

        def _send_json(self, payload: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf8")
            self._send_bytes(body, "application/json; charset=utf-8", status=status)

        def _send_bytes(self, body: bytes, media_type: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(int(status))
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), PortalRequestHandler)
    server.daemon_threads = True
    return server


def _resolve_static_path(root: Path, request_path: str) -> Path | None:
    normalized = _normalized_relative_path(request_path)
    if normalized is None:
        return None
    root_resolved = root.resolve()
    candidate = (root_resolved / normalized).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _normalized_relative_path(request_path: str) -> Path | None:
    raw_path = request_path.strip().replace("\\", "/")
    if not raw_path:
        return None
    parts = [part for part in PurePosixPath(raw_path).parts if part not in {"", "/"}]
    if not parts:
        return None
    if any(part in {".", ".."} for part in parts):
        return None
    return Path(*parts)
