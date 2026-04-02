from __future__ import annotations

import argparse
import re
from pathlib import Path

from repo_harness_lab.cli.commands.common import load_runtime_context, print_error, print_json, resolve_report_path, write_uplift_dashboard
from repo_harness_lab.domain.trace_models import EventType, RunStage
from repo_harness_lab.reporting.html import HtmlReporter
from repo_harness_lab.runtime.portal_live import PortalLiveEntryConfig, default_portal_live_entry_config
from repo_harness_lab.runtime.portal_server import build_portal_http_server


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    list_runs = subparsers.add_parser("list-runs", help="List stored run summaries")
    list_runs.add_argument("--limit", type=int, default=20)
    list_runs.set_defaults(handler=handle_list_runs)

    show_run = subparsers.add_parser("show-run", help="Load and print a stored run summary")
    show_run.add_argument("run_id")
    show_run.set_defaults(handler=handle_show_run)

    show_events = subparsers.add_parser("show-events", help="Load and print stored trace events")
    show_events.add_argument("run_id")
    show_events.add_argument("--limit", type=int)
    show_events.add_argument("--event-type", choices=[item.value for item in EventType])
    show_events.add_argument("--stage", choices=[item.value for item in RunStage])
    show_events.set_defaults(handler=handle_show_events)

    show_verifier = subparsers.add_parser("show-verifier-results", help="Load and print stored verifier results")
    show_verifier.add_argument("run_id")
    show_verifier.set_defaults(handler=handle_show_verifier_results)

    compare_runs = subparsers.add_parser("compare-runs", help="Compare two stored runs")
    compare_runs.add_argument("left_run_id")
    compare_runs.add_argument("right_run_id")
    compare_runs.add_argument("--format", choices=("json", "html"), default="json")
    compare_runs.set_defaults(handler=handle_compare_runs)

    render_report = subparsers.add_parser("render-report", help="Render a report for a stored run")
    render_report.add_argument("run_id")
    render_report.add_argument("--format", choices=("markdown", "html"), default="markdown")
    render_report.add_argument("--write", action="store_true", help="Write the rendered markdown report back to runtime/runs/<run_id>/report.md")
    render_report.set_defaults(handler=handle_render_report)

    render_dashboard = subparsers.add_parser("render-dashboard", help="Render an HTML dashboard for recent runs")
    render_dashboard.add_argument("--limit", type=int, default=20)
    render_dashboard.set_defaults(handler=handle_render_dashboard)

    render_uplift_dashboard = subparsers.add_parser("render-uplift-dashboard", help="Render an HTML dashboard for harness uplift across stored eval reports")
    render_uplift_dashboard.add_argument("--limit", type=int, default=20)
    render_uplift_dashboard.set_defaults(handler=handle_render_uplift_dashboard)

    render_portal = subparsers.add_parser("render-portal", help="Render an HTML workflow portal for runs, evals and comparisons")
    render_portal.add_argument("--limit", type=int, default=20)
    render_portal.add_argument("--live-portal-url")
    render_portal.add_argument("--live-portal-command")
    render_portal.set_defaults(handler=handle_render_portal)

    serve_portal = subparsers.add_parser("serve-portal", help="Serve a live same-model harness portal")
    serve_portal.add_argument("--host", default="127.0.0.1")
    serve_portal.add_argument("--port", type=int, default=8765)
    serve_portal.add_argument("--provider", default="qwen")
    serve_portal.add_argument("--model", default="qwen-plus")
    serve_portal.add_argument("--agent-name")
    serve_portal.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    serve_portal.add_argument("--base-url")
    serve_portal.add_argument("--system-prompt")
    serve_portal.add_argument("--template")
    serve_portal.add_argument("--label-prefix")
    serve_portal.add_argument("--public-base-url")
    serve_portal.add_argument("--hosted-mode", action="store_true")
    serve_portal.set_defaults(handler=handle_serve_portal)


def handle_list_runs(args: argparse.Namespace) -> int:
    _, store, _, _ = load_runtime_context()
    summaries = store.list_runs(limit=args.limit)
    print_json(summaries)
    return 0


def handle_show_run(args: argparse.Namespace) -> int:
    _, _, record_store, _ = load_runtime_context()
    if not record_store.has_run(args.run_id):
        return print_error(f"run not found: {args.run_id}")

    summary = record_store.load_run_record(args.run_id).summary
    print_json(summary)
    return 0


def handle_show_events(args: argparse.Namespace) -> int:
    _, _, record_store, _ = load_runtime_context()
    if not record_store.has_run(args.run_id):
        return print_error(f"run not found: {args.run_id}")

    events = record_store.load_events(
        args.run_id,
        limit=args.limit,
        event_type=args.event_type,
        stage=args.stage,
    )
    print_json(events)
    return 0


def handle_show_verifier_results(args: argparse.Namespace) -> int:
    _, _, record_store, _ = load_runtime_context()
    if not record_store.has_run(args.run_id):
        return print_error(f"run not found: {args.run_id}")

    verifier_result = record_store.load_verifier_result(args.run_id)
    if verifier_result is None:
        return print_error(f"verifier results not found: {args.run_id}")

    print_json(verifier_result)
    return 0


def handle_compare_runs(args: argparse.Namespace) -> int:
    settings, _, record_store, _ = load_runtime_context()
    if not record_store.has_run(args.left_run_id):
        return print_error(f"run not found: {args.left_run_id}")
    if not record_store.has_run(args.right_run_id):
        return print_error(f"run not found: {args.right_run_id}")

    if args.format == "html":
        bundle = record_store.load_run_comparison(args.left_run_id, args.right_run_id)
        compare_path = Path(settings.paths.reports_dir) / _compare_filename(args.left_run_id, args.right_run_id)
        compare_path.write_text(HtmlReporter().render_run_comparison(bundle), encoding="utf8")
        print_json({"ok": True, "format": "html", "path": compare_path})
        return 0

    comparison = record_store.compare_runs(args.left_run_id, args.right_run_id)
    print_json(comparison)
    return 0


def handle_render_report(args: argparse.Namespace) -> int:
    _, store, record_store, reporter = load_runtime_context()
    if not record_store.has_run(args.run_id):
        return print_error(f"run not found: {args.run_id}")

    record = record_store.load_run_record(args.run_id)
    if args.format == "html":
        html_report = HtmlReporter().render_run_record(record)
        report_path = store.html_report_path(args.run_id)
        report_path.write_text(html_report, encoding="utf8")
        print_json({"ok": True, "format": "html", "run_id": args.run_id, "path": report_path})
        return 0

    report = reporter.render_run_record(record)
    if args.write:
        report_path = resolve_report_path(store, args.run_id)
        report_path.write_text(report, encoding="utf8")
    print(report)
    return 0


def handle_render_dashboard(args: argparse.Namespace) -> int:
    settings, store, _, _ = load_runtime_context()
    summaries = store.list_runs(limit=args.limit)
    dashboard_path = Path(settings.paths.reports_dir) / "runs-dashboard.html"
    dashboard_html = HtmlReporter().render_runs_dashboard(summaries, title="最近运行")
    dashboard_path.write_text(dashboard_html, encoding="utf8")
    print_json({"ok": True, "path": dashboard_path, "run_count": len(summaries)})
    return 0


def handle_render_uplift_dashboard(args: argparse.Namespace) -> int:
    settings, _, record_store, _ = load_runtime_context()
    dashboard_path, eval_report_count = write_uplift_dashboard(settings, record_store, limit=args.limit)
    print_json({"ok": True, "path": dashboard_path, "eval_report_count": eval_report_count})
    return 0


def handle_render_portal(args: argparse.Namespace) -> int:
    settings, store, record_store, _ = load_runtime_context()
    reporter = HtmlReporter(run_record_loader=record_store.load_run_record)
    summaries = store.list_runs(limit=args.limit)

    dashboard_path = Path(settings.paths.reports_dir) / "runs-dashboard.html"
    dashboard_path.write_text(reporter.render_runs_dashboard(summaries, title="最近运行"), encoding="utf8")
    uplift_dashboard_path, _ = write_uplift_dashboard(settings, record_store, limit=max(args.limit, 20))

    report_artifacts = record_store.list_report_artifacts(limit=max(args.limit * 4, 20))
    eval_report_records = record_store.list_eval_report_records(limit=max(args.limit * 4, 20))
    portal_path = Path(settings.paths.reports_dir) / "harness-portal.html"
    portal_path.write_text(
        reporter.render_portal(
            runs=summaries,
            report_artifacts=report_artifacts,
            eval_reports=eval_report_records,
            title="\u540c\u6a21\u578b Harness \u95e8\u6237",
            runtime_root=settings.paths.runtime_root,
            runs_dir=settings.paths.runs_dir,
            reports_dir=settings.paths.reports_dir,
            live_portal_url=args.live_portal_url,
            live_portal_command=args.live_portal_command,
        ),
        encoding="utf8",
    )
    print_json(
        {
            "ok": True,
            "path": portal_path,
            "dashboard_path": dashboard_path,
            "uplift_dashboard_path": uplift_dashboard_path,
            "run_count": len(summaries),
            "report_count": len(report_artifacts),
        }
    )
    return 0


def handle_serve_portal(args: argparse.Namespace) -> int:
    settings, _, _, _ = load_runtime_context()
    live_entry = _build_live_entry_config(settings, args)
    server = build_portal_http_server(
        settings=settings,
        live_entry=live_entry,
        host=args.host,
        port=args.port,
    )
    display_host = _display_host(args.host)
    actual_port = int(server.server_address[1])
    local_base_url = f"http://{display_host}:{actual_port}"
    public_base_url = _normalize_public_base_url(args.public_base_url)
    advertised_base_url = public_base_url or local_base_url
    print_json(
        {
            "ok": True,
            "host": args.host,
            "port": actual_port,
            "local_url": _root_url(local_base_url),
            "local_portal_url": _portal_url(local_base_url),
            "url": _root_url(advertised_base_url),
            "portal_url": _portal_url(advertised_base_url),
            "public_base_url": public_base_url,
            "hosted_mode": not live_entry.allow_custom_local_repo_paths,
            "template": str(live_entry.intake_source_path),
            "provider": live_entry.provider,
            "model": live_entry.model,
        }
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _build_live_entry_config(settings, args: argparse.Namespace) -> PortalLiveEntryConfig:
    default_entry = default_portal_live_entry_config(
        settings,
        template=args.template,
        provider=args.provider,
        model=args.model,
        api_key_env=args.api_key_env,
        agent_name=args.agent_name,
        base_url=args.base_url,
        system_prompt=args.system_prompt,
        label_prefix=args.label_prefix,
    )
    template_path = Path(args.template).resolve() if args.template else default_entry.intake_source_path
    hosted_mode = bool(args.hosted_mode or _normalize_public_base_url(args.public_base_url))
    return PortalLiveEntryConfig(
        template_id=template_path.stem.removesuffix("_task_intake"),
        intake_source_path=template_path,
        provider=args.provider,
        model=args.model,
        api_key_env=args.api_key_env,
        agent_name=args.agent_name,
        base_url=args.base_url,
        system_prompt=args.system_prompt,
        label_prefix=args.label_prefix,
        allow_custom_local_repo_paths=not hosted_mode,
    )


def _display_host(host: str) -> str:
    if host in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return host


def _normalize_public_base_url(value: str | None) -> str | None:
    normalized = str(value or "").strip().rstrip("/")
    return normalized or None


def _root_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/"


def _portal_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/harness-portal.html"


def _compare_filename(left_run_id: str, right_run_id: str) -> str:
    left = _safe_file_stem(left_run_id)
    right = _safe_file_stem(right_run_id)
    return f"compare-{left}-vs-{right}.html"


def _safe_file_stem(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return sanitized or "comparison"

