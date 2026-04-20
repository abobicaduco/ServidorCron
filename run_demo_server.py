# -*- coding: utf-8 -*-
"""
UI demo server — no BigQuery, no pandas, no login, no scheduler.

Run (from this folder):
  python run_demo_server.py

Open: http://127.0.0.1:5050/

Requires: pip install flask
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from flask import Flask, jsonify, request, send_file
except ImportError:
    print("Install Flask:  python -m pip install flask", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard.html"


def _br_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-3))).replace(tzinfo=None)


def _fixtures():
    now = _br_now()
    today = now.strftime("%Y-%m-%d")
    hot = (now + timedelta(minutes=29)).strftime("%Y-%m-%dT%H:%M:%S")

    running = [
        {
            "python_name": "demo_relatorio",
            "area_name": "demo area",
            "pid": 91001,
            "running_time_seconds": 145,
            "trigger_reason": "scheduled",
            "priority": 1,
            "rss_mb": 420.5,
            "cpu_percent": 12.3,
            "num_children": 1,
        },
        {
            "python_name": "demo_carga",
            "area_name": "cobranca fake",
            "pid": 91002,
            "running_time_seconds": 48,
            "trigger_reason": "manual",
            "priority": 2,
            "rss_mb": 180.0,
            "cpu_percent": 4.1,
            "num_children": 0,
        },
    ]
    queued = [
        {
            "python_name": "demo_fila_a",
            "area_name": "bo renda fixa",
            "priority": 2,
            "tier": 1,
            "scheduled_ts": now.timestamp(),
            "position": 1,
            "waiting_seconds": 95,
            "trigger_reason": "catch-up",
        },
        {
            "python_name": "demo_fila_b",
            "area_name": "monitoracao financeira",
            "priority": 3,
            "tier": 2,
            "scheduled_ts": now.timestamp(),
            "position": 2,
            "waiting_seconds": 40,
            "trigger_reason": "scheduled",
        },
    ]

    def script_row(
        name: str,
        area: str,
        prio: int,
        cron: str,
        *,
        running: bool = False,
        queued: bool = False,
        local: bool = True,
        active: bool = True,
        cron_source: str = "bigquery",
    ) -> dict:
        return {
            "python_name": name,
            "area_name": area,
            "cron_raw": cron,
            "is_active": active,
            "is_valid_cron": True,
            "priority": prio,
            "available_locally": local,
            "is_running": running,
            "is_queued": queued,
            "cron_source": cron_source,
            "emails_principal": "",
            "emails_cc": "",
            "move_file": False,
            "movimentacao_financeira": False,
            "interacao_cliente": False,
            "tempo_manual": 0,
            "objetivo": "Demo fixture — not a real job.",
            "responsavel": "demo",
        }

    scripts_demo = [
        script_row("conciliacao_demo", "bo renda fixa", 1, "0 7 * * 1-5", running=True),
        script_row("extrato_demo", "monitoracao financeira", 2, "0 8 * * 1-5", queued=True),
        script_row("carga_demo", "cobranca", 2, "30 8 * * 1-5"),
        script_row("relatorio_offline", "governanca", 3, "ON DEMAND", local=False, active=False),
        script_row("sp_demo", "agro", 3, "0 6 * * 1-5"),
    ]

    history = []
    for i, st in enumerate(
        ["success", "success", "no_data", "error", "success", "no_data", "killed", "success"] * 3
    ):
        t0 = now - timedelta(minutes=15 * (i + 1))
        t1 = t0 + timedelta(seconds=30 + i)
        start_iso = t0.strftime("%Y-%m-%dT%H:%M:%S")
        end_iso = t1.strftime("%Y-%m-%dT%H:%M:%S")
        history.append(
            {
                "python_name": f"script_fake_{i % 5}",
                "area_name": ["bo renda fixa", "cobranca", "agro"][i % 3],
                "priority": (i % 3) + 1,
                "start_time": start_iso,
                "end_time": end_iso,
                "duration_seconds": float(30 + i),
                "duration_label": f"{30 + i}s",
                "exit_code": 0 if st == "success" else (2 if st == "no_data" else (None if st == "killed" else 1)),
                "status": st,
                "trigger_reason": "scheduled" if i % 2 == 0 else "catch-up",
                "error_message": "Demo error" if st == "error" else None,
            }
        )

    pending = [
        {
            "python_name": "pendente_am",
            "area_name": "bo renda fixa",
            "cron_raw": "0 1 * * 1-5",
            "priority": 1,
            "expected_time": "01:00",
            "available_locally": True,
        },
        {
            "python_name": "pendente_pm",
            "area_name": "cobranca",
            "cron_raw": "0 14 * * 1-5",
            "priority": 3,
            "expected_time": "14:00",
            "available_locally": True,
        },
    ]

    stats_block = {
        "total": 24,
        "counts": {"success": 18, "no_data": 4, "error": 2},
        "percent": {"success": 75.0, "no_data": 16.7, "error": 8.3},
        "by_script": {
            "script_fake_0": {"success": 10, "no_data": 2, "error": 1, "total": 13},
            "script_fake_1": {"success": 8, "no_data": 2, "error": 1, "total": 11},
        },
    }

    jobs = [
        {"id": "hot_reload_job", "name": "Hot-Reload [30min] (demo)", "next_run_br": hot},
        {"id": "conciliacao_demo_cron", "name": "conciliacao_demo [0 7 * * 1-5] (p=1)", "next_run_br": hot},
        {"id": "demo_relatorio_cron", "name": "demo_relatorio [0 8 * * 1-5] (p=1)", "next_run_br": hot},
    ]

    return {
        "today": today,
        "now": now,
        "hot": hot,
        "status": {
            "running_processes": running,
            "queued_processes": queued,
            "running_count": len(running),
            "queued_count": len(queued),
            "max_concurrent": 3,
            "next_hot_reload_iso": hot,
            "server_metrics": {
                "cpu_percent": 24.6,
                "ram_percent": 58.2,
                "ram_used_gb": 18.4,
                "ram_total_gb": 31.6,
            },
        },
        "health": {"status": "ok", "uptime_seconds": 3600.0, "running": len(running), "queued": len(queued)},
        "server_info": {
            "version": "demo-1.0.0",
            "hostname": "demo-pc",
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "os": "Windows (demo)",
            "uptime_seconds": 3661.0,
            "timezone": "America/Sao_Paulo",
            "max_concurrent": 3,
            "cpu_cores": 8,
            "ram_total_gb": 31.6,
            "log_file": str(ROOT / "demo.log"),
            "dir_automacoes": str(ROOT / "automacoes"),
            "dir_automacoes_exists": True,
            "reload_interval_min": 30,
            "default_timeout_sec": 7200,
            "max_cpu_percent": 90,
            "max_ram_percent": 90,
            "cobranca_cron_xlsx": str(ROOT / "optional_cobranca_cron.xlsx"),
            "cobranca_cron_xlsx_exists": False,
            "cobranca_cron_sheet": "AUTOMACAO",
            "access_url_lan": "http://127.0.0.1:5050/",
            "access_url_local": "http://127.0.0.1:5050/",
        },
        "areas_summary": {
            "areas": [
                {"name": "bo renda fixa", "count": 8},
                {"name": "cobranca", "count": 5},
                {"name": "monitoracao financeira", "count": 4},
                {"name": "demo area", "count": 2},
            ]
        },
        "scripts": scripts_demo,
        "history": history[:40],
        "pending": pending,
        "jobs": jobs,
        "stats": {
            "today": stats_block,
            "last_7_days": {
                "total": 120,
                "counts": {"success": 96, "no_data": 18, "error": 6},
                "percent": {"success": 80.0, "no_data": 15.0, "error": 5.0},
                "by_script": stats_block["by_script"],
            },
            "max_stored": 1000,
        },
    }


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "demo-secret"
    F = _fixtures()

    @app.after_request
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
        resp.headers["Access-Control-Allow-Credentials"] = "true"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    @app.route("/", methods=["GET"])
    def index():
        if not DASHBOARD.is_file():
            return (
                f"Missing {DASHBOARD.name}. Copy dashboard.html next to run_demo_server.py.",
                404,
                {"Content-Type": "text/plain; charset=utf-8"},
            )
        return send_file(str(DASHBOARD), mimetype="text/html; charset=utf-8")

    @app.route("/api/auth/status", methods=["GET"])
    def auth_status():
        return jsonify({"logged_in": True, "username": "demo", "role": "admin"})

    @app.route("/api/auth/request-token", methods=["POST", "OPTIONS"])
    def auth_token():
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({"status": "success", "message": "Demo mode — no e-mail sent."})

    @app.route("/api/auth/verify", methods=["POST", "OPTIONS"])
    def auth_verify():
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({"status": "success", "username": "demo", "role": "admin"})

    @app.route("/api/auth/logout", methods=["POST", "OPTIONS"])
    def auth_logout():
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({"status": "success"})

    @app.route("/api/status", methods=["GET"])
    def api_status():
        return jsonify(F["status"])

    @app.route("/api/health", methods=["GET"])
    def api_health():
        return jsonify(F["health"])

    @app.route("/api/server/info", methods=["GET"])
    def api_server_info():
        return jsonify(F["server_info"])

    @app.route("/api/areas/summary", methods=["GET"])
    def api_areas_summary():
        return jsonify(F["areas_summary"])

    @app.route("/api/scripts/by-area", methods=["GET"])
    def api_scripts_by_area():
        area = (request.args.get("area") or "").strip().lower()
        out = [s for s in F["scripts"] if s["area_name"].lower() == area]
        if not out:
            out = F["scripts"]
        return jsonify(out)

    @app.route("/api/scripts/search", methods=["GET"])
    def api_scripts_search():
        q = (request.args.get("q") or "").strip().lower()
        out = [s for s in F["scripts"] if q in s["python_name"].lower() or q in s["area_name"].lower()]
        return jsonify(out)

    @app.route("/api/pending", methods=["GET"])
    def api_pending():
        return jsonify({"pending": F["pending"], "date": F["today"], "total": len(F["pending"])})

    @app.route("/api/jobs", methods=["GET"])
    def api_jobs():
        return jsonify(F["jobs"])

    @app.route("/api/history", methods=["GET"])
    def api_history():
        return jsonify({"history": F["history"], "total": len(F["history"]), "max_stored": 1000})

    @app.route("/api/history/stats", methods=["GET"])
    def api_history_stats():
        return jsonify(
            {
                "today": F["stats"]["today"],
                "last_7_days": F["stats"]["last_7_days"],
                "timezone": "America/Sao_Paulo",
                "script_filter": None,
                "max_stored": F["stats"]["max_stored"],
                "note": "Demo data — not real executions.",
            }
        )

    @app.route("/api/reload", methods=["POST", "OPTIONS"])
    def api_reload():
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({"status": "success", "script_count": len(F["scripts"])})

    @app.route("/api/run/<name>", methods=["POST", "OPTIONS"])
    def api_run(name: str):
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({"status": "success", "message": f"'{name}' enfileirado (demo)."})

    @app.route("/api/kill/<int:pid>", methods=["POST", "OPTIONS"])
    def api_kill(pid: int):
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({"status": "success", "message": f"PID {pid} encerrado (demo)."})

    @app.route("/api/kill/by-name/<name>", methods=["POST", "OPTIONS"])
    def api_kill_name(name: str):
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify({"status": "success", "message": f"'{name}' encerrado (demo)."})

    @app.route("/api/share_outlook", methods=["POST", "OPTIONS"])
    def api_share():
        if request.method == "OPTIONS":
            return ("", 204)
        return jsonify(
            {
                "status": "success",
                "message": "Demo — Outlook not opened.",
                "shared_url": "http://127.0.0.1:5050/",
                "access_url_lan": "http://127.0.0.1:5050/",
                "access_url_local": "http://127.0.0.1:5050/",
            }
        )

    return app


def main() -> None:
    p = argparse.ArgumentParser(description="Demo UI server for Abobi Server Cron dashboard.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5050)
    args = p.parse_args()
    app = create_app()
    print(f"[DEMO] Dashboard: http://{args.host}:{args.port}/", flush=True)
    print("[DEMO] Login bypassed — user demo / admin.", flush=True)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
