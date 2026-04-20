"""
Abobi Server Cron — workflow orchestrator + web dashboard (single process).
Open-source edition: configure paths and BigQuery tables via environment variables.

Run: python main.py

Dependencies:
    pip install -r requirements.txt
"""

# ==============================================================
# IMPORTS
# ==============================================================
import json
import os
import random
import re
import signal
import string
import subprocess
import sys
import threading
import time
import logging
import platform
import socket
import webbrowser
from collections import deque
from contextlib import suppress
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from queue import PriorityQueue
from pathlib import Path
from typing import Optional

def bootstrap():
    """Instala silenciosamente as dependências se estiverem faltando."""
    import importlib.util
    
    deps = {
        "apscheduler": "apscheduler==3.10.4",
        "flask": "flask==3.0.3",
        "flask_cors": "flask-cors==4.0.1",
        "pandas": "pandas==2.3.3",
        "openpyxl": "openpyxl==3.1.2",
        "psutil": "psutil==5.9.8",
        "pytz": "pytz==2024.1",
        "croniter": "croniter==2.0.5",
        "waitress": "waitress==3.0.0",
        "google.cloud.bigquery": "google-cloud-bigquery==3.20.1",
        "db_dtypes": "db-dtypes==1.2.0",
        "sqlalchemy": "sqlalchemy==2.0.38",
    }
    
    missing = []
    for mod, pkg in deps.items():
        try:
            if "." in mod:
                import importlib
                importlib.import_module(mod)
            else:
                if importlib.util.find_spec(mod) is None:
                    missing.append(pkg)
        except Exception:
            missing.append(pkg)
            
    if missing:
        print(f"[BOOTSTRAP] Instalando {len(missing)} dependência(s) ausente(s): {', '.join(missing)}...", flush=True)
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install"] + missing,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("[BOOTSTRAP] Dependências instaladas com sucesso.", flush=True)
        except subprocess.CalledProcessError:
            print("[BOOTSTRAP] Falha ao instalar as dependências. Verifique a internet e permissões.", flush=True)
            sys.exit(1)

bootstrap()

import pandas as pd
import pytz
import psutil
from flask import Flask, jsonify, request, send_file, Response, session
from flask_cors import CORS
from waitress import serve

try:
    import pythoncom
    import win32com.client as win32
    HAS_OUTLOOK = True
except ImportError:
    HAS_OUTLOOK = False

# Importações de Confiabilidade (Escala)
from google.cloud import bigquery
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

# ==============================================================
# PATHS & OSS CONFIG — override with env vars (see .env.example)
# ==============================================================
_HOME = Path.home()
PATH_SCRIPT_DIR = Path(__file__).resolve().parent

if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
    PATH_SERVIDOR_APP = Path(os.environ["LOCALAPPDATA"]) / "AbobiServerCron"
else:
    PATH_SERVIDOR_APP = _HOME / ".abobi-server-cron"

PATH_LOG_DIR = PATH_SERVIDOR_APP / "logs"
PATH_JOBSTORE_SQLITE = PATH_SERVIDOR_APP / "jobs_scheduler.sqlite"
PATH_EXECUTION_HISTORY_JSON = PATH_LOG_DIR / "execution_history.json"

# Automation root: recursive scan for .py — default ./automacoes next to main.py
PATH_AUTOMACOES = (
    Path(os.environ["ABOBI_AUTOMATIONS_DIR"]).expanduser()
    if os.environ.get("ABOBI_AUTOMATIONS_DIR")
    else (PATH_SCRIPT_DIR / "automacoes")
)

# Optional: Excel with CRON overrides for a named business area (see README)
PATH_PLANILHA_FILEROUTER_COBRANCA = (
    Path(os.environ["ABOBI_COBRANCA_CRON_XLSX"]).expanduser()
    if os.environ.get("ABOBI_COBRANCA_CRON_XLSX")
    else (PATH_SCRIPT_DIR / "optional_cobranca_cron.xlsx")
)

PATH_DASHBOARD_HTML = PATH_SCRIPT_DIR / "dashboard.html"
PATH_ACCESS_REGISTRY_XLSX = PATH_SCRIPT_DIR / "access_registry.xlsx"

# Chrome no Windows (abrir dashboard); ordem de tentativa
PATH_CHROME_CANDIDATES = (
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    / "Google"
    / "Chrome"
    / "Application"
    / "chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
    / "Google"
    / "Chrome"
    / "Application"
    / "chrome.exe",
    _HOME / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
)

# --- Aliases usados no restante do modulo (nao duplicar logica) ---
DIRETORIO_AUTOMACOES = PATH_AUTOMACOES
PLANILHA_FILEROUTER_COB = PATH_PLANILHA_FILEROUTER_COBRANCA
_LOG_DIR = PATH_LOG_DIR
_LOG_FILE = PATH_LOG_DIR / "abobi_server_cron.log"
_HISTORY_FILE = PATH_EXECUTION_HISTORY_JSON
_DASHBOARD_FILE = PATH_DASHBOARD_HTML
_db_path = PATH_JOBSTORE_SQLITE

SHEET_COBRANCA_CRON = "AUTOMACAO"

PATH_LOG_DIR.mkdir(parents=True, exist_ok=True)

# ==============================================================
# LOGGING SETUP (Console + RotatingFile)
# ==============================================================
_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_log_formatter)

_file_handler = RotatingFileHandler(
    _LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_file_handler.setFormatter(_log_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_console_handler, _file_handler],
)
logger = logging.getLogger("AbobiServerCron")

try:
    from croniter import croniter as _Croniter
    _HAS_CRONITER = True
except ImportError:
    _HAS_CRONITER = False
    logger.warning("'croniter' nao instalado - catch-up desabilitado.")

# ==============================================================
# CONFIGURACAO SERVIDOR (nao-caminhos)
# ==============================================================
MAX_PROCESSOS_SIMULTANEOS = 3
RELOAD_INTERVAL_MINUTES   = 30
RELOAD_COOLDOWN_SECONDS   = 180
MAX_CPU_PERCENT           = 90
MAX_RAM_PERCENT           = 90
DEFAULT_TIMEOUT_SECONDS   = 7200  # 2h

HOST     = os.environ.get("ABOBI_HOST", "0.0.0.0")
PORT     = int(os.environ.get("ABOBI_PORT", "5002"))
TIMEZONE = "America/Sao_Paulo"
TZ       = pytz.timezone(TIMEZONE)

OPEN_BROWSER = True
BROWSER_DELAY_SEC = 1.2

CRON_ON_DEMAND     = "ON DEMAND"
_SERVER_START_TIME = time.time()
_SERVER_VERSION    = "3.0.0"


def _split_csv_users(val: str) -> list[str]:
    return [x.strip().lower() for x in val.split(",") if x.strip()]


# --- Dashboard auth (token via e-mail; Outlook COM on Windows optional) ---
SECRET_KEY: str = os.environ.get("ABOBI_SECRET_KEY", "dev-only-change-me-to-a-long-random-string")
DOMAIN: str = os.environ.get("ABOBI_EMAIL_DOMAIN", "@example.com")
MOCK_EMAIL: bool = os.environ.get("ABOBI_MOCK_EMAIL", "").strip().lower() in ("1", "true", "yes", "on")
# Admins: full control (run, kill, sync BQ). Comma-separated login names (no domain).
ADMIN_USERS: list[str] = _split_csv_users(os.environ.get("ABOBI_ADMIN_USERS", "admin"))
_extra_viewers: list[str] = _split_csv_users(os.environ.get("ABOBI_EXTRA_VIEWERS", ""))
ALLOWED_LOGIN_USERS: list[str] = list(dict.fromkeys([*ADMIN_USERS, *_extra_viewers]))
ADMIN_USERS_LOWER = {u.strip().lower() for u in ADMIN_USERS}

# BigQuery: full table id project.dataset.table (set in .env for your GCP project)
TABLE_SERVIDORCRON_ACCESS = os.environ.get(
    "BQ_ACCESS_TABLE",
    "your-gcp-project.your_dataset.access_registry",
)
TABLE_REGISTRO_AUTOMACOES = os.environ.get(
    "BQ_REGISTRO_TABLE",
    "your-gcp-project.your_dataset.registro_automacoes",
)
_ACCESS_REGISTRY_TTL_SECONDS = 120
_access_registry_cache: dict = {"data": {}, "ts": 0.0}
_access_registry_lock = threading.Lock()

_cron_auth_tokens: dict[str, dict] = {}

# -- History (persistent JSON) --------------------------------
_MAX_HISTORY = 1000
_history_lock = threading.Lock()


def _normalize_history_entry(entry: dict) -> dict:
    """Align status with exit_code: 2 = no_data (common convention), not error."""
    if entry.get("exit_code") == 2:
        entry["status"] = "no_data"
    return entry


def _load_history_from_disk() -> deque:
    """Load execution history from JSON file on boot."""
    history = deque(maxlen=_MAX_HISTORY)
    if _HISTORY_FILE.exists():
        try:
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for entry in data:
                history.append(_normalize_history_entry(entry))
            logger.info(f"[BOOT] Histórico carregado: {len(history)} entradas de {_HISTORY_FILE}")
        except Exception:
            logger.warning(f"[BOOT] Falha ao carregar histórico de {_HISTORY_FILE}. Iniciando vazio.")
    return history

def _save_history_to_disk() -> None:
    """Persist current history to JSON file."""
    try:
        with _history_lock:
            data = list(_execution_history)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=None)
    except Exception:
        logger.warning("[HISTORY] Falha ao salvar histórico em disco.")

_execution_history: deque = _load_history_from_disk()

# ==============================================================
# UTILITÁRIOS DE PARSING
# ==============================================================

def _safe_str(val) -> str:
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()

def _parse_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    return _safe_str(val).lower() in ("true", "1", "yes", "sim")

def _parse_priority(val) -> int:
    try:
        p = int(float(_safe_str(val)))
        return p if p in (1, 2, 3) else 2
    except Exception:
        return 2

def _parse_int_safe(val, default=0) -> int:
    try:
        s = _safe_str(val)
        return int(float(s)) if s else default
    except (ValueError, TypeError):
        return default

def _normalize_name(raw: str) -> str:
    s = str(raw).strip().lower()
    return s[:-3] if s.endswith(".py") else s


def _normalize_access_role(level_access: str) -> str:
    s = _safe_str(level_access).strip().lower()
    if s in ("admin", "administrador", "adm", "administrator"):
        return "admin"
    return "viewer"


_XLS_ACCESS_CANONICAL = {
    "users": "users",
    "user": "users",
    "usuario": "users",
    "usuarios": "users",
    "level_access": "level_access",
    "level_acess": "level_access",
    "level_acesso": "level_access",
    "nivel": "level_access",
    "nivel_acesso": "level_access",
}


def _normalize_excel_access_col(name: str) -> str:
    s = str(name).strip().lower().replace(" ", "_")
    return _XLS_ACCESS_CANONICAL.get(s, s)


def _fetch_servidorcron_access_excel() -> dict[str, str]:
    """users -> admin|viewer from access_registry.xlsx next to main.py (works without BigQuery)."""
    out: dict[str, str] = {}
    if not PATH_ACCESS_REGISTRY_XLSX.is_file():
        logger.debug("[AUTH] access_registry.xlsx not found at %s", PATH_ACCESS_REGISTRY_XLSX)
        return out
    try:
        df_raw = pd.read_excel(PATH_ACCESS_REGISTRY_XLSX, sheet_name=0, engine="openpyxl")
    except Exception:
        logger.exception("[AUTH] Failed to read access_registry.xlsx at %s", PATH_ACCESS_REGISTRY_XLSX)
        return out
    if df_raw.empty:
        logger.warning("[AUTH] Local access_registry.xlsx is empty.")
        return out
    df = df_raw.copy()
    df.columns = [_normalize_excel_access_col(c) for c in df.columns]
    if "users" not in df.columns or "level_access" not in df.columns:
        logger.warning(
            "[AUTH] Planilha local: colunas invalidas (esperado users, level_access). Encontrado: %s",
            list(df.columns),
        )
        return out
    for _, row in df.iterrows():
        u = _safe_str(row.get("users", "")).strip().lower()
        if not u:
            continue
        out[u] = _normalize_access_role(_safe_str(row.get("level_access", "")))
    logger.info("[AUTH] Local access_registry.xlsx: %d user(s).", len(out))
    return out


def _fetch_servidorcron_access_bq() -> dict[str, str]:
    """users -> admin|viewer from BigQuery access table."""
    out: dict[str, str] = {}
    try:
        client = bigquery.Client()
        query = f"SELECT users, level_access FROM `{TABLE_SERVIDORCRON_ACCESS}`"
        df = client.query(query).to_dataframe(create_bqstorage_client=False)
        if df.empty:
            logger.info("[AUTH] BigQuery access table: empty.")
            return out
        df.columns = [str(c).strip().lower() for c in df.columns]
        if "users" not in df.columns or "level_access" not in df.columns:
            logger.warning(
                "[AUTH] BigQuery access table: unexpected columns (expected users, level_access). Found: %s",
                list(df.columns),
            )
            return out
        for _, row in df.iterrows():
            u = _safe_str(row.get("users", "")).strip().lower()
            if not u:
                continue
            out[u] = _normalize_access_role(_safe_str(row.get("level_access", "")))
        logger.info("[AUTH] BigQuery access table: %d user(s) loaded.", len(out))
    except Exception:
        logger.exception("[AUTH] BigQuery access table read failed (using local fallback).")
    return out


def _build_access_registry() -> dict[str, str]:
    """Mescla: planilha local (xlsx) + BigQuery (BQ sobrescreve mesmo usuario) + fallback do codigo."""
    xl = _fetch_servidorcron_access_excel()
    bq = _fetch_servidorcron_access_bq()
    merged: dict[str, str] = {}
    merged.update(xl)
    merged.update(bq)
    if not xl and not bq:
        logger.warning(
            "[AUTH] No users in access_registry.xlsx or BigQuery access table. "
            "Only ALLOWED_LOGIN_USERS from env/code can request a token. "
            "Add access_registry.xlsx under %s or fix BQ credentials / table ids.",
            PATH_SCRIPT_DIR,
        )
    for u in ALLOWED_LOGIN_USERS:
        ul = u.strip().lower()
        if ul not in merged:
            merged[ul] = "admin" if ul in ADMIN_USERS_LOWER else "viewer"
    logger.info(
        "[AUTH] Registro de acesso | xlsx=%d usuario(s) | bq=%d usuario(s) | total_mesclado=%d (apos fallback codigo)",
        len(xl),
        len(bq),
        len(merged),
    )
    return merged


def _get_access_registry() -> dict[str, str]:
    with _access_registry_lock:
        age = time.time() - _access_registry_cache["ts"]
        if _access_registry_cache["data"] and age < _ACCESS_REGISTRY_TTL_SECONDS:
            return dict(_access_registry_cache["data"])
    merged = _build_access_registry()
    with _access_registry_lock:
        _access_registry_cache["data"] = merged
        _access_registry_cache["ts"] = time.time()
    return dict(merged)


def _invalidate_access_registry_cache() -> None:
    with _access_registry_lock:
        _access_registry_cache["data"] = {}
        _access_registry_cache["ts"] = 0.0


def _is_cobranca_area(area_name: str) -> bool:
    a = _safe_str(area_name).strip().lower()
    return a in ("cobranca", "cobrança")


def _alnum_lower(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _strip_item_date_tokens(s: str) -> str:
    """Remove leading YYYYMMDD_ and trailing _AAAAMMDD / _YYYYMMDD / _digits from ITEM-style keys."""
    s = re.sub(r"^\d{8}_", "", s)
    s = re.sub(r"_(aaaammdd|yyyymmdd|\d{8})$", "", s, flags=re.I)
    return s


def _load_cobranca_cron_map() -> dict[str, str]:
    """Load python_name / ITEM -> cron from local workbook (AUTOMACAO sheet)."""
    path = PLANILHA_FILEROUTER_COB
    if not path.exists():
        logger.warning(f"[COBRANÇA XLSX] Arquivo não encontrado: {path}")
        return {}
    try:
        df = pd.read_excel(path, sheet_name=SHEET_COBRANCA_CRON, engine="openpyxl").dropna(how="all")
    except Exception as e:
        logger.warning(f"[COBRANÇA XLSX] Falha ao ler {path}: {e}")
        return {}
    df.columns = (
        df.columns.astype(str).str.strip().str.lower()
        .str.replace(r"[\s_]+", "_", regex=True)
    )
    if "cron" not in df.columns:
        logger.warning("[COBRANÇA XLSX] Coluna CRON não encontrada na aba AUTOMACAO.")
        return {}
    has_py = "python_name" in df.columns
    has_item = "item" in df.columns
    if not has_py and not has_item:
        logger.warning("[COBRANÇA XLSX] Nenhuma coluna python_name ou item encontrada.")
        return {}

    m: dict[str, str] = {}
    for _, row in df.iterrows():
        cron_raw = _safe_str(row.get("cron", ""))
        if not cron_raw or cron_raw.strip().upper() == CRON_ON_DEMAND:
            continue
        if not _is_valid_cron(cron_raw):
            logger.warning(f"[COBRANÇA XLSX] Linha com CRON inválido ignorada: {cron_raw!r}")
            continue
        keys: list[str] = []
        if has_py:
            pv = _safe_str(row.get("python_name", ""))
            if pv:
                pn = _normalize_name(pv)
                keys.append(pn)
                keys.append(_alnum_lower(pn))
        if has_item:
            iv = _safe_str(row.get("item", ""))
            if iv:
                n = _normalize_name(iv)
                keys.append(n)
                keys.append(_strip_item_date_tokens(n))
                keys.append(_alnum_lower(n))
                keys.append(_alnum_lower(_strip_item_date_tokens(n)))
        for k in keys:
            if k:
                m[k] = cron_raw.strip()

    logger.info(f"[COBRANÇA XLSX] {len(df)} linha(s) na aba {SHEET_COBRANCA_CRON!r} -> {len(m)} chave(s) de cron indexadas ({path.name}).")
    return m


def _apply_cobranca_cron_from_excel(records: list[dict]) -> None:
    """Override CRON from BigQuery for COBRANCA rows when matched in EXPORTACAO_IMPORTACAO planilha."""
    m = _load_cobranca_cron_map()
    if not m:
        return
    for r in records:
        if not _is_cobranca_area(r["area_name"]):
            continue
        name = r["python_name"]
        cron_new = m.get(name)
        if cron_new is None:
            cron_new = m.get(_strip_item_date_tokens(name))
        if cron_new is None:
            cron_new = m.get(_alnum_lower(name))
        if cron_new:
            old = r["cron_raw"]
            r["cron_raw"] = cron_new
            r["is_valid_cron"] = _is_valid_cron(cron_new)
            r["cron_source"] = "cobranca_xlsx"
            logger.debug(f"[COBRANÇA XLSX] {name}: CRON pela planilha (BQ tinha {old!r})")
        else:
            logger.warning(
                f"[COBRANÇA XLSX] {name}: sem correspondencia na planilha - mantendo CRON do BigQuery ({r['cron_raw']!r})."
            )


def _is_valid_cron(cron_str: str) -> bool:
    s = str(cron_str).strip().upper()
    if not s or s == CRON_ON_DEMAND:
        return False
    try:
        CronTrigger.from_crontab(s, timezone=TZ)
        return True
    except ValueError:
        return False

def _now_br() -> datetime:
    """Current datetime in São Paulo timezone (naive)."""
    return datetime.now(TZ).replace(tzinfo=None)


def _history_entry_start_date(entry: dict):
    """Calendar date of execution start from stored ISO `start_time`."""
    st = entry.get("start_time") or ""
    if len(st) >= 10:
        try:
            return datetime.strptime(st[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def _format_duration(seconds: float) -> str:
    """Human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours}h{mins:02d}m{secs:02d}s"

# ==============================================================
# HISTORY RECORDER
# ==============================================================

def _record_execution(
    python_name: str, area_name: str, priority: int,
    start_ts: float, end_ts: float, exit_code: int | None,
    trigger_reason: str, error_msg: str | None = None,
    stdout_tail: str | None = None, stderr_tail: str | None = None,
) -> None:
    """Append a finished execution to in-memory history."""
    elapsed = round(end_ts - start_ts, 1)
    if exit_code == 0:
        status = "success"
    elif exit_code == 2:
        status = "no_data"
    elif exit_code is None:
        status = "killed"
    else:
        status = "error"
    entry = {
        "python_name":    python_name,
        "area_name":      area_name,
        "priority":       priority,
        "start_time":     datetime.fromtimestamp(start_ts, TZ).isoformat(),
        "end_time":       datetime.fromtimestamp(end_ts, TZ).isoformat(),
        "duration_seconds": elapsed,
        "duration_label":   _format_duration(elapsed),
        "exit_code":      exit_code,
        "status":         status,
        "trigger_reason": trigger_reason,
        "error_message":  error_msg,
        "stdout_tail":    stdout_tail,
        "stderr_tail":    stderr_tail,
    }
    with _history_lock:
        _execution_history.appendleft(entry)
    _save_history_to_disk()

# ==============================================================
# SCANNER (OTIMIZADO + cache em memória)
# ==============================================================

_LOCAL_FILES_TTL_SECONDS = 180
_local_files_cache: dict = {"data": {}, "ts": 0.0}
_local_files_lock = threading.Lock()


def _invalidate_local_files_cache() -> None:
    with _local_files_lock:
        _local_files_cache["data"] = {}
        _local_files_cache["ts"] = 0.0


def buscar_arquivos_locais() -> dict[str, Path]:
    """Varre o disco por .py; resultado fica em cache ~3 min para acelerar o dashboard."""
    with _local_files_lock:
        age = time.time() - _local_files_cache["ts"]
        if _local_files_cache["data"] and age < _LOCAL_FILES_TTL_SECONDS:
            return dict(_local_files_cache["data"])

    found: dict[str, Path] = {}
    if not DIRETORIO_AUTOMACOES or not DIRETORIO_AUTOMACOES.exists():
        logger.warning(f"DIRETORIO_AUTOMACOES não encontrado: {DIRETORIO_AUTOMACOES}")
        return found

    ignore_dirs = {".git", ".vscode", "__pycache__", "venv", "env", "node_modules", ".venv"}

    for root, dirs, files in os.walk(DIRETORIO_AUTOMACOES):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        root_path = Path(root)
        for filename in files:
            if not filename.endswith(".py") or filename.startswith("_"):
                continue
            name = _normalize_name(filename)
            full = root_path / filename
            if name in found:
                continue
            found[name] = full

    logger.info(f"[SCAN] Disco: {len(found)} arquivos .py (cache {_LOCAL_FILES_TTL_SECONDS}s).")
    with _local_files_lock:
        _local_files_cache["data"] = found
        _local_files_cache["ts"] = time.time()
    return dict(found)

# ==============================================================
# BIGQUERY REGISTRY READER (com cache em memoria - TTL 600s)
# ==============================================================

_BQ_CACHE_TTL_SECONDS = 600  # 10 minutos
_bq_cache: dict = {"records": [], "ts": 0.0}
_bq_cache_lock = threading.Lock()

def _ler_registro_bq(force: bool = False) -> list[dict]:
    """Lê o cadastro de robôs diretamente da tabela no BigQuery.
    Usa cache em memória com TTL de 10 min para evitar abuso de queries.
    Passe force=True para ignorar o cache (usado no reload manual).
    """
    with _bq_cache_lock:
        age = time.time() - _bq_cache["ts"]
        if not force and _bq_cache["records"] and age < _BQ_CACHE_TTL_SECONDS:
            return _bq_cache["records"]

    logger.info("[BIGQUERY] Consultando tabela registro_automacoes...")
    try:
        client = bigquery.Client()
        query = f"SELECT * FROM `{TABLE_REGISTRO_AUTOMACOES}`"
        df = client.query(query).to_dataframe(create_bqstorage_client=False)
        df = df.dropna(how='all')
        df.columns = [str(c).strip().upper() for c in df.columns]
        logger.info(f"[BIGQUERY] {len(df)} registros encontrados.")
    except Exception as e:
        logger.exception(f"[BIGQUERY] Erro crítico ao ler tabela: {e}")
        # On error, return stale cache if available
        with _bq_cache_lock:
            return _bq_cache["records"]

    records = []
    for _, row in df.iterrows():
        python_name = _safe_str(row.get("PYTHON_NAME", ""))
        if not python_name:
            continue

        normalized = _normalize_name(python_name)
        cron_raw = _safe_str(row.get("CRON", ""))

        val_fin_mov = row.get("MOVIMENTACAO_FINANCEIRA", row.get("MOVIMENTACAO FINANCEIRA", False))
        val_cli_int = row.get("INTERACAO_CLIENTE", row.get("INTERACAO CLIENTE", False))
        val_tempo   = row.get("TEMPO_MANUAL_MINUTOS", row.get("TEMPO MANUAL MINUTOS", 0))

        records.append({
            "python_name":             normalized,
            "area_name":               _safe_str(row.get("AREA_NAME", "sem area")).lower(),
            "cron_raw":                cron_raw,
            "is_valid_cron":           _is_valid_cron(cron_raw),
            "cron_source":             "bigquery",
            "is_active":               _parse_bool(row.get("IS_ACTIVE", False)),
            "priority":                _parse_priority(row.get("PRIORITY", 2)),
            "emails_principal":        _safe_str(row.get("EMAILS_PRINCIPAL", "")),
            "emails_cc":               _safe_str(row.get("EMAILS_CC", "")),
            "move_file":               _parse_bool(row.get("MOVE_FILE", False)),
            "movimentacao_financeira": _parse_bool(val_fin_mov),
            "interacao_cliente":       _parse_bool(val_cli_int),
            "tempo_manual":            _parse_int_safe(val_tempo, 0),
            "objetivo":                _safe_str(row.get("OBJETIVO", "")),
            "responsavel":             _safe_str(row.get("RESPONSAVEL", "")),
        })

    _apply_cobranca_cron_from_excel(records)

    with _bq_cache_lock:
        _bq_cache["records"] = records
        _bq_cache["ts"] = time.time()
    logger.info(f"[BQ CACHE] Cache atualizado com {len(records)} registros.")
    return records

def _get_all_scripts(local_files: dict[str, Path], force_bq: bool = False) -> list[dict]:
    result = []
    for r in _ler_registro_bq(force=force_bq):
        r = dict(r)  # copy to avoid mutating cache
        r["available_locally"] = r["python_name"] in local_files
        r["path"] = str(local_files[r["python_name"]]) if r["available_locally"] else None
        result.append(r)
    return result

def _get_schedulable_scripts(local_files: dict[str, Path], force_bq: bool = False) -> list[dict]:
    schedulable = []
    for s in _get_all_scripts(local_files, force_bq=force_bq):
        if not s["is_active"]:
            continue
        if s["cron_raw"].strip().upper() == CRON_ON_DEMAND:
            continue
        if not s["is_valid_cron"]:
            _hint = (
                "planilha EXPORTACAO_IMPORTACAO_ARQUIVOS_FILEROUTER (aba AUTOMACAO)"
                if _is_cobranca_area(s["area_name"])
                else "BigQuery (coluna CRON)"
            )
            logger.warning(f"[IGNORADO] '{s['python_name']}': CRON inválido ('{s['cron_raw']}'). Corrija em {_hint}.")
            continue
        if not s["available_locally"]:
            logger.warning(f"[IGNORADO] '{s['python_name']}': Arquivo .py não encontrado no disco local.")
            continue
        schedulable.append(s)
    return schedulable

# ==============================================================
# CATCH-UP ENGINE - detecta e executa scripts pendentes do dia
# ==============================================================

def _detect_pending_scripts() -> list[dict]:
    """Return scripts whose cron window already passed today but haven't run.
    Each entry includes python_name, area_name, cron_raw, priority,
    expected_time, available_locally, and path.
    """
    if not _HAS_CRONITER:
        return []

    today_str = _now_br().strftime("%Y-%m-%d")
    local_files = buscar_arquivos_locais()
    all_scripts = _get_all_scripts(local_files)
    schedulable = [
        s for s in all_scripts
        if s["is_active"] and s["is_valid_cron"]
        and s["cron_raw"].strip().upper() != CRON_ON_DEMAND
    ]

    with _history_lock:
        today_history = {
            e["python_name"] for e in _execution_history
            if e.get("start_time", "").startswith(today_str)
        }
    with _running_lock:
        running_names = {d["python_name"] for d in _running.values()}
    queued_names = {task["python_name"] for _, _, _, task in list(_task_queue.queue)}

    pending = []
    now_dt = _now_br()
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    for s in schedulable:
        name = s["python_name"]
        if name in today_history or name in running_names or name in queued_names:
            continue
        try:
            cron = _Croniter(s["cron_raw"], today_start)
            next_fire = cron.get_next(datetime)
            if next_fire <= now_dt:
                pending.append({
                    "python_name": name,
                    "area_name": s["area_name"],
                    "cron_raw": s["cron_raw"],
                    "priority": s["priority"],
                    "expected_time": next_fire.strftime("%H:%M"),
                    "available_locally": s["available_locally"],
                    "path": s.get("path"),
                })
        except Exception:
            pass

    # Sort by priority (P1=1 first, then P2=2, then P3=3), then by expected_time
    pending.sort(key=lambda x: (x["priority"], x["expected_time"]))
    return pending


def _catchup_pending_scripts() -> None:
    """Detect scripts that missed their cron window today and enqueue them.
    Order: all P1 first, then P2, then P3.
    Only enqueues scripts that are available locally.
    """
    pending = _detect_pending_scripts()
    if not pending:
        logger.info("[CATCH-UP] Nenhum script pendente do dia.")
        return

    enqueued = 0
    skipped = 0
    for s in pending:
        if not s["available_locally"] or not s.get("path"):
            logger.warning(f"[CATCH-UP] '{s['python_name']}' sem arquivo local. Pulando.")
            skipped += 1
            continue

        ok = enqueue_script(
            python_name=s["python_name"],
            path=s["path"],
            area_name=s["area_name"],
            priority=s["priority"],
            scheduled_ts=time.time(),
            trigger_reason="catch-up",
        )
        if ok:
            enqueued += 1
            logger.info(f"[CATCH-UP] Enfileirado: {s['python_name']} (P{s['priority']}, esperado {s['expected_time']})")
        else:
            skipped += 1

    logger.info(f"[CATCH-UP] Concluído: {enqueued} enfileirado(s), {skipped} pulado(s) de {len(pending)} pendente(s).")

# ==============================================================
# PROCESS METRICS COLLECTOR
# ==============================================================

def _get_process_metrics(pid: int) -> dict:
    """Collect CPU% and memory for a given PID."""
    try:
        proc = psutil.Process(pid)
        mem_info = proc.memory_info()
        cpu = proc.cpu_percent(interval=0)
        children = proc.children(recursive=True)
        child_mem = sum(c.memory_info().rss for c in children)
        return {
            "rss_mb": round((mem_info.rss + child_mem) / (1024 * 1024), 1),
            "cpu_percent": cpu,
            "num_children": len(children),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"rss_mb": 0.0, "cpu_percent": 0.0, "num_children": 0}

# ==============================================================
# EXECUTOR & HEALTH GOVERNOR
# ==============================================================

_semaphore          = threading.Semaphore(MAX_PROCESSOS_SIMULTANEOS)
_task_queue: PriorityQueue = PriorityQueue()
_running: dict[int, dict]  = {}
_running_lock               = threading.Lock()

def _priority_to_tier(priority: int) -> int:
    return {1: 0, 2: 1, 3: 2}.get(priority, 1)

def enqueue_script(python_name: str, path: str, area_name: str, priority: int, scheduled_ts: float, trigger_reason: str = "scheduled") -> bool:
    with _running_lock:
        if any(d["python_name"] == python_name for d in _running.values()):
            return False
    for _, _, _, task in list(_task_queue.queue):
        if task["python_name"] == python_name:
            return False

    tier = _priority_to_tier(priority)
    task_data = {
        "python_name":   python_name, "path": path, "area_name": area_name,
        "priority":      priority, "tier": tier, "trigger_reason": trigger_reason,
        "scheduled_ts":  scheduled_ts,
    }
    _task_queue.put((tier, scheduled_ts, time.time(), task_data))
    logger.info(f"[QUEUE] {python_name} | p={priority} | motivo={trigger_reason}")
    return True

def _register_pid(proc, task_data: dict) -> None:
    with _running_lock:
        _running[proc.pid] = {
            "pid": proc.pid, "proc_obj": proc, "python_name": task_data["python_name"],
            "area_name": task_data["area_name"], "priority": task_data["priority"],
            "start_time": time.time(), "trigger_reason": task_data["trigger_reason"],
        }

def _unregister_pid(pid: int) -> None:
    with _running_lock:
        _running.pop(pid, None)

def _wait_for_resources():
    """
    HEALTH GOVERNOR: Impede que o servidor seja sufocado.
    Se o disco/CPU chegar no talo, ele segura os processos da fila P2 e P3
    """
    while True:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        if cpu <= MAX_CPU_PERCENT and ram <= MAX_RAM_PERCENT:
            break
        logger.warning(f"[RECURSOS ALTO] CPU: {cpu}% | RAM: {ram}%. Aguardando estabilização para rodar novos processos...")
        time.sleep(5)

def _run_p2p3(task_data: dict) -> None:
    _wait_for_resources()

    name = task_data["python_name"]
    path = task_data["path"]
    proc = None
    t_start = time.time()
    stdout_tail = None
    stderr_tail = None
    error_msg = None
    exit_code = None
    logger.info(f"[>] Iniciando: {name}")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(path)],
            shell=False,
            cwd=str(Path(path).parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _register_pid(proc, task_data)
        try:
            raw_stdout, raw_stderr = proc.communicate(timeout=DEFAULT_TIMEOUT_SECONDS)
            stdout_tail = raw_stdout.decode("utf-8", errors="replace")[-2000:] if raw_stdout else None
            stderr_tail = raw_stderr.decode("utf-8", errors="replace")[-2000:] if raw_stderr else None
        except subprocess.TimeoutExpired:
            logger.warning(f"[TIMEOUT] {name} excedeu {DEFAULT_TIMEOUT_SECONDS}s. Matando...")
            with suppress(Exception):
                parent = psutil.Process(proc.pid)
                for child in parent.children(recursive=True):
                    with suppress(psutil.NoSuchProcess):
                        child.kill()
                parent.kill()
            proc.wait(timeout=10)
            error_msg = f"Timeout after {DEFAULT_TIMEOUT_SECONDS}s"

        exit_code = proc.returncode
        elapsed = round(time.time() - t_start, 1)
        if exit_code == 0:
            tag = "[OK]"
        elif exit_code == 2:
            tag = "[NO_DATA]"
        else:
            tag = "[ERR]"
        logger.info(f"{tag} {name} | exit={exit_code} | elapsed={elapsed}s")
    except Exception as exc:
        logger.critical(f"[CRIT] {name}: {exc}")
        error_msg = str(exc)
    finally:
        t_end = time.time()
        if proc:
            _unregister_pid(proc.pid)
        _semaphore.release()
        _record_execution(
            python_name=name, area_name=task_data["area_name"],
            priority=task_data["priority"], start_ts=t_start, end_ts=t_end,
            exit_code=exit_code, trigger_reason=task_data["trigger_reason"],
            error_msg=error_msg, stdout_tail=stdout_tail, stderr_tail=stderr_tail,
        )

def _run_p1(task_data: dict) -> None:
    name = task_data["python_name"]
    path = task_data["path"]
    proc = None
    t_start = time.time()
    stdout_tail = None
    stderr_tail = None
    error_msg = None
    exit_code = None
    logger.info(f"[P1] Início preemptivo: {name}")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(path)],
            shell=False,
            cwd=str(Path(path).parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _register_pid(proc, task_data)
        try:
            raw_stdout, raw_stderr = proc.communicate(timeout=DEFAULT_TIMEOUT_SECONDS)
            stdout_tail = raw_stdout.decode("utf-8", errors="replace")[-2000:] if raw_stdout else None
            stderr_tail = raw_stderr.decode("utf-8", errors="replace")[-2000:] if raw_stderr else None
        except subprocess.TimeoutExpired:
            logger.warning(f"[TIMEOUT] {name} (P1) excedeu {DEFAULT_TIMEOUT_SECONDS}s. Matando...")
            with suppress(Exception):
                parent = psutil.Process(proc.pid)
                for child in parent.children(recursive=True):
                    with suppress(psutil.NoSuchProcess):
                        child.kill()
                parent.kill()
            proc.wait(timeout=10)
            error_msg = f"Timeout after {DEFAULT_TIMEOUT_SECONDS}s"

        exit_code = proc.returncode
        elapsed = round(time.time() - t_start, 1)
        if exit_code == 0:
            tag = "[OK]"
        elif exit_code == 2:
            tag = "[NO_DATA]"
        else:
            tag = "[ERR]"
        logger.info(f"{tag} {name} (P1) | exit={exit_code} | elapsed={elapsed}s")
    except Exception as exc:
        logger.critical(f"[CRIT] {name} (P1): {exc}")
        error_msg = str(exc)
    finally:
        t_end = time.time()
        if proc:
            _unregister_pid(proc.pid)
        _record_execution(
            python_name=name, area_name=task_data["area_name"],
            priority=task_data["priority"], start_ts=t_start, end_ts=t_end,
            exit_code=exit_code, trigger_reason=task_data["trigger_reason"],
            error_msg=error_msg, stdout_tail=stdout_tail, stderr_tail=stderr_tail,
        )

def _queue_processor() -> None:
    while True:
        try:
            _tier, _sched_ts, _enq_ts, task_data = _task_queue.get()
            if task_data["priority"] == 1:
                t = threading.Thread(target=_run_p1, args=(task_data,), daemon=True, name=f"p1-{task_data['python_name']}")
                t.start()
            else:
                _semaphore.acquire()
                t = threading.Thread(target=_run_p2p3, args=(task_data,), daemon=True, name=f"worker-{task_data['python_name']}")
                t.start()
        except Exception as e:
            logger.exception(f"Erro no processador da fila: {e}")
        finally:
            _task_queue.task_done()

def kill_process(pid: int) -> bool:
    with _running_lock:
        info = _running.get(pid)
    if not info:
        return False
    t_start = info.get("start_time", time.time())
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            with suppress(psutil.NoSuchProcess):
                child.kill()
        parent.kill()
        logger.info(f"[KILL] {info['python_name']} (PID {pid})")
    except psutil.NoSuchProcess:
        pass
    except Exception as exc:
        logger.warning(f"Erro ao matar PID {pid}: {exc}")
    finally:
        _unregister_pid(pid)
        if info.get("priority", 2) != 1:
            _semaphore.release()
        _record_execution(
            python_name=info["python_name"], area_name=info["area_name"],
            priority=info.get("priority", 2), start_ts=t_start, end_ts=time.time(),
            exit_code=None, trigger_reason=info.get("trigger_reason", "unknown"),
            error_msg="Killed by user",
        )
    return True

def kill_by_name(python_name: str) -> list[int]:
    """Kill all running processes matching a script name. Returns killed PIDs."""
    killed_pids = []
    target_name = python_name.lower().strip()
    with _running_lock:
        targets = [
            (pid, info) for pid, info in _running.items()
            if info["python_name"].lower() == target_name
        ]
    for pid, _info in targets:
        if kill_process(pid):
            killed_pids.append(pid)
    return killed_pids

def graceful_shutdown() -> None:
    logger.info("[SHUTDOWN] Matando todos os processos filhos...")
    with _running_lock:
        all_pids = list(_running.keys())
    for pid in all_pids:
        kill_process(pid)
    logger.info("[SHUTDOWN] Processos filhos encerrados.")

threading.Thread(target=_queue_processor, daemon=True, name="queue-processor").start()

# ==============================================================
# SCHEDULER ENGINE (COM SQLITE JOBSTORE)
# ==============================================================

_jobstores = {
    "default": SQLAlchemyJobStore(url=f"sqlite:///{_db_path}")
}
_scheduler = BackgroundScheduler(jobstores=_jobstores, timezone=TZ)
_last_reload_ts: float = 0.0
_reload_ts_lock = threading.Lock()
_SCHEDULER_PROTECTED_JOB_IDS = frozenset({"hot_reload_job", "catchup_job"})


def _job_wrapper(python_name: str, path: str, area_name: str, priority: int) -> None:
    enqueue_script(
        python_name=python_name, path=path, area_name=area_name,
        priority=priority, scheduled_ts=time.time(), trigger_reason="scheduled"
    )

def recarregar_agendamentos() -> list[dict]:
    logger.info("[RELOAD] Recarregando agendamentos do BigQuery...")
    _invalidate_local_files_cache()
    for job in _scheduler.get_jobs():
        if job.id in _SCHEDULER_PROTECTED_JOB_IDS:
            continue
        job.remove()

    local_files = buscar_arquivos_locais()
    scripts = _get_schedulable_scripts(local_files, force_bq=True)

    jobs_criados = 0
    for s in scripts:
        try:
            trigger = CronTrigger.from_crontab(s["cron_raw"], timezone=TZ)
            _scheduler.add_job(
                _job_wrapper, trigger,
                id=f"{s['python_name']}_cron",
                name=f"{s['python_name']} [{s['cron_raw']}] (p={s['priority']})",
                args=[s["python_name"], s["path"], s["area_name"], s["priority"]],
                replace_existing=True,
                misfire_grace_time=86400,
                coalesce=True,
            )
            jobs_criados += 1
        except Exception as e:
            logger.warning(f"Cron inválido '{s['cron_raw']}' para {s['python_name']}: {e}")

    logger.info(f"[RELOAD OK] {jobs_criados} jobs criados de {len(scripts)} scripts ativos")
    threading.Thread(target=_catchup_pending_scripts, daemon=True, name="reload-catchup").start()
    return scripts

def iniciar_scheduler() -> None:
    recarregar_agendamentos()
    _scheduler.add_job(
        recarregar_agendamentos, "interval", minutes=RELOAD_INTERVAL_MINUTES,
        id="hot_reload_job", name=f"Hot-Reload automático BQ (a cada {RELOAD_INTERVAL_MINUTES}min)",
        replace_existing=True
    )
    # Catch-up job: every 10 min, detect pending scripts and enqueue them
    _scheduler.add_job(
        _catchup_pending_scripts, "interval", minutes=10,
        id="catchup_job", name="Catch-Up pendentes (a cada 10min)",
        replace_existing=True,
        misfire_grace_time=600,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(f"[BOOT] APScheduler iniciado | tz={TIMEZONE}")
    # Fire catch-up once on boot (separate thread to not block startup)
    threading.Thread(
        target=_catchup_pending_scripts, daemon=True, name="boot-catchup"
    ).start()

def get_jobs_info() -> list[dict]:
    jobs = []
    for job in _scheduler.get_jobs():
        nrt = job.next_run_time
        jobs.append({
            "id":          job.id,
            "name":        job.name or job.id,
            "next_run_br": nrt.astimezone(TZ).isoformat() if nrt else None,
        })
    return sorted(jobs, key=lambda j: j["next_run_br"] or "")


def _next_hot_reload_iso() -> str | None:
    """Next run time of the hot-reload job (for dashboard countdown without extra /api/jobs calls)."""
    try:
        job = _scheduler.get_job("hot_reload_job")
        if not job or not job.next_run_time:
            return None
        return job.next_run_time.astimezone(TZ).isoformat()
    except Exception:
        return None


class _CronEmailService:
    """Sends login token e-mails via Outlook COM on Windows (optional)."""

    @staticmethod
    def send_token_email(destinatario: str, token: str) -> bool:
        if MOCK_EMAIL:
            logger.info(f"[MOCK EMAIL] Abobi Server Cron token for {destinatario}: {token}")
            return True
        if not HAS_OUTLOOK:
            logger.error("win32com não disponível. E-mail de token não enviado.")
            return False
        pythoncom.CoInitialize()
        try:
            outlook = win32.Dispatch("outlook.application")
            mail = outlook.CreateItem(0)
            mail.To = destinatario
            mail.Subject = "Your login token — Abobi Server Cron"
            mail.HTMLBody = f"""
                <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px;">
                    <h2 style="color: #242424; border-bottom: 2px solid #d3ad65; padding-bottom: 10px;">Abobi Server Cron</h2>
                    <p>Hello,</p>
                    <p>Your dashboard login code is:</p>
                    <div style="text-align: center; margin: 30px 0;">
                        <h1 style="color: #242424; background-color: #f3f4f6; padding: 15px 30px; display: inline-block; border-radius: 8px; letter-spacing: 8px; margin: 0; font-size: 32px; border: 1px solid #ccc;">{token}</h1>
                    </div>
                    <p style="color: #d32f2f; font-size: 13px;"><b>Note:</b> This code expires in 2 minutes. Do not share it.</p>
                    <p>— Abobi Server Cron</p>
                </div>
            """
            mail.Send()
            logger.info(f"[AUTH] Token enviado para {destinatario}")
            return True
        except Exception:
            logger.exception("[AUTH] Erro ao enviar e-mail de token")
            return False
        finally:
            with suppress(Exception):
                pythoncom.CoUninitialize()


def _cron_require_admin():
    if session.get("role") != "admin":
        return jsonify({
            "status": "error",
            "message": "Acesso negado (somente administrador).",
        }), 403
    return None


def _get_local_ip() -> str:
    s: Optional[socket.socket] = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("10.254.254.254", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        if s is not None:
            s.close()
    return ip


# ==============================================================
# FLASK API
# ==============================================================

_app = Flask(__name__)
_app.secret_key = SECRET_KEY
_app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
CORS(_app, supports_credentials=True)
_reload_last: float = 0.0
_reload_lock = threading.Lock()


@_app.before_request
def _cron_auth_gate():
    p = request.path
    if p in ("/", "/favicon.ico"):
        return None
    public_api = frozenset({
        "/api/auth/status",
        "/api/auth/request-token",
        "/api/auth/verify",
        "/api/auth/logout",
    })
    if p in public_api:
        return None
    if p.startswith("/api/") and "username" not in session:
        return jsonify({"error": "unauthorized", "message": "Login required."}), 401
    return None


@_app.after_request
def _cron_security_headers(response: Response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


@_app.route("/api/auth/status")
def api_auth_status():
    if "username" not in session:
        return jsonify({"logged_in": False, "username": None, "role": None})
    return jsonify({
        "logged_in": True,
        "username": session["username"],
        "role": session.get("role", "viewer"),
    })


@_app.route("/api/auth/request-token", methods=["POST"])
def api_auth_request_token():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    if not username:
        logger.warning("[AUTH] request-token: rejeitado | motivo=username vazio")
        return jsonify({"status": "error", "message": "Informe o usuário."}), 400

    reg = _get_access_registry()
    if username not in reg:
        logger.warning(
            "[AUTH] request-token: DENIED | user=%s | not in BQ/local registry | "
            "registro atual tem %d usuario(s)",
            username,
            len(reg),
        )
        return jsonify({"status": "error", "message": "Usuário não autorizado a solicitar token."}), 403

    logger.info("[AUTH] request-token: aceito | user=%s | role=%s", username, reg[username])

    token = "".join(random.choices(string.digits, k=6))
    _cron_auth_tokens[username] = {
        "token": token,
        "expires": datetime.now() + timedelta(minutes=2),
    }
    destinatario = f"{username}{DOMAIN}"
    if _CronEmailService.send_token_email(destinatario, token):
        logger.info("[AUTH] request-token: e-mail de token enviado | user=%s | dest=%s", username, destinatario)
        return jsonify({"status": "success", "message": "Token enviado ao seu e-mail."})
    logger.error("[AUTH] request-token: falha ao enviar e-mail Outlook | user=%s", username)
    return jsonify({"status": "error", "message": "Falha ao enviar e-mail (verifique o Outlook)."}), 500


@_app.route("/api/auth/verify", methods=["POST"])
def api_auth_verify():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip().lower()
    token_in = (data.get("token") or "").strip()
    reg = _get_access_registry()
    if username not in reg:
        logger.warning(
            "[AUTH] verify: NEGADO | user=%s | nao cadastrado (BQ/fallback) — possivel remocao apos pedido de token",
            username,
        )
        return jsonify({"status": "error", "message": "Usuário não autorizado."}), 403
    if username not in _cron_auth_tokens:
        logger.warning("[AUTH] verify: rejeitado | user=%s | nenhum token pendente", username)
        return jsonify({"status": "error", "message": "Solicite um token primeiro."}), 400
    dados = _cron_auth_tokens[username]
    if datetime.now() > dados["expires"]:
        logger.warning("[AUTH] verify: rejeitado | user=%s | token expirado", username)
        return jsonify({"status": "error", "message": "Token expirado."}), 400
    if token_in != dados["token"]:
        logger.warning("[AUTH] verify: rejeitado | user=%s | codigo invalido", username)
        return jsonify({"status": "error", "message": "Token inválido."}), 400
    session["username"] = username
    session["role"] = "admin" if reg[username] == "admin" else "viewer"
    session.permanent = True
    logger.info("[AUTH] verify: sessao aberta | user=%s | role=%s", username, session["role"])
    return jsonify({
        "status": "success",
        "username": username,
        "role": session["role"],
    })


@_app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify({"status": "success"})


def _cron_access_urls() -> dict[str, str]:
    """URLs for sharing: LAN (mesma rede) e localhost (apenas na máquina do servidor)."""
    lan_ip = _get_local_ip()
    return {
        "access_url_lan": f"http://{lan_ip}:{PORT}/",
        "access_url_local": f"http://127.0.0.1:{PORT}/",
    }


@_app.route("/api/share_outlook", methods=["POST"])
def api_share_outlook():
    """Opens Outlook with a shareable HTML invite (admin only)."""
    denied = _cron_require_admin()
    if denied:
        return denied
    if not HAS_OUTLOOK:
        return jsonify({"status": "error", "message": "Outlook COM não disponível neste servidor."}), 500

    urls = _cron_access_urls()
    server_url = urls["access_url_lan"]
    url_local = urls["access_url_local"]

    html_body = f"""
        <div style="font-family: Segoe UI, Arial, sans-serif; color: #333; max-width: 700px;">
            <h2 style="color: #242424; border-bottom: 2px solid #d3ad65; padding-bottom: 10px;">
                Abobi Server Cron — Access link
            </h2>
            <p>Hello,</p>
            <p>Use the link below to open the <b>Abobi Server Cron</b> dashboard on the <b>same network</b> as the server:</p>
            <div style="text-align: center; margin: 25px 0;">
                <a href="{server_url}"
                   style="background-color: #242424; color: #d3ad65; padding: 14px 32px;
                          text-decoration: none; border-radius: 8px; font-weight: bold;
                          font-size: 16px; display: inline-block;">
                    Open Abobi Server Cron
                </a>
            </div>
            <p style="color:#555;font-size:13px;">LAN URL: <a href="{server_url}">{server_url}</a></p>
            <p style="color:#888;font-size:12px;">Localhost (on the server PC): <a href="{url_local}">{url_local}</a></p>
            <p style="color: #555; font-size: 13px; background: #f3f4f6; padding: 12px; border-radius: 6px;">
                <b>How to sign in:</b><br>
                1. Open the link in a browser (Chrome recommended).<br>
                2. Enter your configured username (no e-mail domain).<br>
                3. A 6-digit token is sent to your e-mail (username + {DOMAIN}).<br>
                4. Enter the token. Viewers see monitoring only; admins can run or stop jobs.
            </p>
            <p>— Abobi Server Cron</p>
        </div>
        """

    def _open_outlook() -> None:
        pythoncom.CoInitialize()
        try:
            outlook = win32.Dispatch("outlook.application")
            mail = outlook.CreateItem(0)
            mail.Subject = "Abobi Server Cron — Access link"
            mail.HTMLBody = html_body
            mail.Display()
            logger.info("[SHARE] Outlook window opened for Abobi Server Cron share.")
        except Exception:
            logger.exception("[SHARE] Erro ao abrir Outlook para compartilhamento")
        finally:
            with suppress(Exception):
                pythoncom.CoUninitialize()

    threading.Thread(target=_open_outlook, daemon=True, name="share-outlook-cron").start()
    logger.info(f"[SHARE] Convite Outlook aberto por {session.get('username')}")
    return jsonify({
        "status": "success",
        "message": "Outlook aberto — preencha o Para com os convidados e envie.",
        "shared_url": server_url,
        **urls,
    })


# -- Dashboard Route -----------------------------------------

@_app.route("/")
def root():
    if _DASHBOARD_FILE.exists():
        return send_file(str(_DASHBOARD_FILE), mimetype="text/html")
    return jsonify({"status": "ok", "mode": "backend-only", "docs": f"http://{HOST}:{PORT}/api/status"})

# -- API Routes ----------------------------------------------

@_app.route("/api/status")
def api_status():
    now = time.time()
    with _running_lock:
        running = []
        for info in _running.values():
            metrics = _get_process_metrics(info["pid"])
            running.append({
                "pid": info["pid"], "python_name": info["python_name"], "area_name": info["area_name"],
                "running_time_seconds": int(now - info["start_time"]),
                "trigger_reason": info.get("trigger_reason", "scheduled"), "priority": info.get("priority", 2),
                "rss_mb": metrics["rss_mb"], "cpu_percent": metrics["cpu_percent"],
                "num_children": metrics["num_children"],
            })
    running.sort(key=lambda x: x["running_time_seconds"], reverse=True)

    q_snap = sorted(list(_task_queue.queue))
    queued = [
        {
            "python_name": task["python_name"], "area_name": task["area_name"], "priority": task["priority"],
            "tier": task["tier"], "scheduled_ts": sched_ts, "position": i + 1, "waiting_seconds": int(now - enq_ts),
            "trigger_reason": task.get("trigger_reason", "scheduled"),
        }
        for i, (_, sched_ts, enq_ts, task) in enumerate(q_snap)
    ]

    vm = psutil.virtual_memory()
    return jsonify({
        "running_processes": running, "queued_processes": queued,
        "running_count": len(running), "queued_count": len(queued),
        "max_concurrent": MAX_PROCESSOS_SIMULTANEOS,
        "next_hot_reload_iso": _next_hot_reload_iso(),
        "server_metrics": {
            "cpu_percent": psutil.cpu_percent(),
            "ram_percent": vm.percent,
            "ram_used_gb": round(vm.used / (1024 ** 3), 1),
            "ram_total_gb": round(vm.total / (1024 ** 3), 1),
        },
    })

@_app.route("/api/health")
def api_health():
    return jsonify({
        "status": "ok", "uptime_seconds": round(time.time() - _SERVER_START_TIME, 1),
        "running": len(_running), "queued": _task_queue.qsize(),
    })

@_app.route("/api/server/info")
def api_server_info():
    vm = psutil.virtual_memory()
    urls = _cron_access_urls()
    return jsonify({
        "version": _SERVER_VERSION,
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "os": f"{platform.system()} {platform.release()}",
        "uptime_seconds": round(time.time() - _SERVER_START_TIME, 1),
        "timezone": TIMEZONE,
        "max_concurrent": MAX_PROCESSOS_SIMULTANEOS,
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_total_gb": round(vm.total / (1024 ** 3), 1),
        "log_file": str(_LOG_FILE),
        "dir_automacoes": str(DIRETORIO_AUTOMACOES),
        "dir_automacoes_exists": DIRETORIO_AUTOMACOES.exists(),
        "reload_interval_min": RELOAD_INTERVAL_MINUTES,
        "default_timeout_sec": DEFAULT_TIMEOUT_SECONDS,
        "max_cpu_percent": MAX_CPU_PERCENT,
        "max_ram_percent": MAX_RAM_PERCENT,
        "cobranca_cron_xlsx": str(PLANILHA_FILEROUTER_COB),
        "cobranca_cron_xlsx_exists": PLANILHA_FILEROUTER_COB.exists(),
        "cobranca_cron_sheet": SHEET_COBRANCA_CRON,
        **urls,
    })

def _annotate(scripts: list[dict]) -> list[dict]:
    with _running_lock:
        running_names = {d["python_name"] for d in _running.values()}
    queued_names = {task["python_name"] for _, _, _, task in list(_task_queue.queue)}
    for s in scripts:
        s["is_running"] = s["python_name"] in running_names
        s["is_queued"]  = s["python_name"] in queued_names
    return scripts

@_app.route("/api/scripts")
def api_scripts():
    local_files = buscar_arquivos_locais()
    return jsonify(_annotate(_get_all_scripts(local_files)))

@_app.route("/api/scripts/<python_name>")
def api_script_detail(python_name: str):
    local_files = buscar_arquivos_locais()
    name = python_name.lower().strip()
    all_scripts = _annotate(_get_all_scripts(local_files))
    found = next((s for s in all_scripts if s["python_name"] == name), None)
    if not found:
        return jsonify({"status": "error", "message": f"'{name}' não encontrado."}), 404
    # Attach recent history for this script
    with _history_lock:
        found["recent_history"] = [h for h in _execution_history if h["python_name"] == name][:20]
    return jsonify(found)

@_app.route("/api/areas")
def api_areas():
    local_files = buscar_arquivos_locais()
    areas: dict = {}
    for s in _annotate(_get_all_scripts(local_files)):
        areas.setdefault(s["area_name"], []).append(s)
    # Sort scripts within each area alphabetically
    for area_name in areas:
        areas[area_name].sort(key=lambda s: s["python_name"])
    return jsonify(areas)


@_app.route("/api/areas/summary")
def api_areas_summary():
    """Counts per area from BigQuery registry (fast; no disk walk)."""
    counts: dict[str, int] = {}
    for r in _ler_registro_bq():
        a = r["area_name"]
        counts[a] = counts.get(a, 0) + 1
    areas = [{"name": k, "count": counts[k]} for k in sorted(counts.keys())]
    return jsonify({"areas": areas})


@_app.route("/api/scripts/by-area")
def api_scripts_by_area():
    """Scripts for one area only (smaller payload than /api/areas)."""
    area = (request.args.get("area") or "").strip().lower()
    if not area:
        return jsonify({"status": "error", "message": "Query parameter 'area' is required."}), 400
    local_files = buscar_arquivos_locais()
    scripts = [
        s for s in _annotate(_get_all_scripts(local_files))
        if s["area_name"] == area
    ]
    scripts.sort(key=lambda x: x["python_name"])
    return jsonify(scripts)


@_app.route("/api/scripts/search")
def api_scripts_search():
    """Busca scripts por nome ou área em todo o cadastro (usa cache de disco + BQ)."""
    q = (request.args.get("q") or "").strip().lower()
    if not q:
        return jsonify([])
    local_files = buscar_arquivos_locais()
    all_scripts = _annotate(_get_all_scripts(local_files))
    out = [
        s for s in all_scripts
        if q in s["python_name"] or q in s.get("area_name", "")
    ]
    out.sort(key=lambda x: (x["area_name"], x["python_name"]))
    return jsonify(out[:500])


@_app.route("/api/run/<python_name>", methods=["POST"])
def api_run(python_name: str):
    denied = _cron_require_admin()
    if denied:
        return denied
    local_files = buscar_arquivos_locais()
    name = python_name.lower().strip()
    path = local_files.get(name)
    if not path:
        return jsonify({"status": "error", "message": f"'{name}' não encontrado no disco."}), 404

    all_scripts = {s["python_name"]: s for s in _get_all_scripts(local_files)}
    info = all_scripts.get(name, {})
    ok = enqueue_script(
        python_name=name, path=str(path), area_name=info.get("area_name", "manual"),
        priority=info.get("priority", 2), scheduled_ts=time.time(), trigger_reason="manual",
    )
    if ok:
        return jsonify({"status": "success", "message": f"'{name}' enfileirado."})
    return jsonify({"status": "duplicate", "message": f"'{name}' já rodando ou na fila."})

@_app.route("/api/kill/<int:pid>", methods=["POST"])
def api_kill(pid: int):
    denied = _cron_require_admin()
    if denied:
        return denied
    if kill_process(pid):
        return jsonify({"status": "success", "message": f"PID {pid} encerrado."})
    return jsonify({"status": "error", "message": "PID não encontrado."}), 404

@_app.route("/api/kill/by-name/<python_name>", methods=["POST"])
def api_kill_by_name(python_name: str):
    denied = _cron_require_admin()
    if denied:
        return denied
    killed = kill_by_name(python_name)
    if killed:
        return jsonify({"status": "success", "killed_pids": killed, "message": f"'{python_name}' encerrado ({len(killed)} processos)."})
    return jsonify({"status": "error", "message": f"'{python_name}' não está rodando."}), 404

@_app.route("/api/reload", methods=["POST"])
def api_reload():
    denied = _cron_require_admin()
    if denied:
        return denied
    global _reload_last
    now = time.time()
    with _reload_lock:
        wait = RELOAD_COOLDOWN_SECONDS - (now - _reload_last)
        if wait > 0:
            return jsonify({"status": "cooldown", "wait_seconds": int(wait)}), 429
        _reload_last = now

    scripts = recarregar_agendamentos()
    _invalidate_access_registry_cache()
    return jsonify({"status": "success", "script_count": len(scripts)})

@_app.route("/api/jobs")
def api_jobs():
    return jsonify(get_jobs_info())

@_app.route("/api/history")
def api_history():
    limit = request.args.get("limit", 100, type=int)
    script_filter = request.args.get("script", "").lower().strip()
    area_filter = request.args.get("area", "").lower().strip()
    status_filter = request.args.get("status", "").lower().strip()

    with _history_lock:
        entries = list(_execution_history)

    if script_filter:
        entries = [e for e in entries if script_filter in e["python_name"]]
    if area_filter:
        entries = [e for e in entries if area_filter in e["area_name"]]
    if status_filter:
        entries = [e for e in entries if e["status"] == status_filter]

    return jsonify({
        "history": entries[:limit],
        "total": len(entries),
        "max_stored": _MAX_HISTORY,
    })


def _aggregate_history_stats(entries: list[dict]) -> dict:
    """Counts and percentages by status; per-script breakdown. Excludes killed runs."""
    counts = {"success": 0, "error": 0, "no_data": 0}
    by_script: dict[str, dict[str, int]] = {}
    for e in entries:
        st = e.get("status", "")
        if st == "killed":
            continue
        if st in counts:
            counts[st] += 1
        pn = e.get("python_name") or "?"
        if pn not in by_script:
            by_script[pn] = {"success": 0, "error": 0, "no_data": 0, "total": 0}
        if st in by_script[pn]:
            by_script[pn][st] += 1
        by_script[pn]["total"] += 1
    total = sum(counts.values())
    pct = {k: round(100.0 * v / total, 1) if total else 0.0 for k, v in counts.items()}
    return {"total": total, "counts": counts, "percent": pct, "by_script": by_script}


@_app.route("/api/history/stats")
def api_history_stats():
    """Aggregates for dashboard: today vs last 7 calendar days. Optional `script` substring filter."""
    try:
        script_filter = request.args.get("script", "").lower().strip()
        with _history_lock:
            entries = list(_execution_history)
        if script_filter:
            entries = [e for e in entries if script_filter in (e.get("python_name") or "").lower()]

        today = datetime.now(TZ).date()
        week_start = today - timedelta(days=6)

        def in_today(e: dict) -> bool:
            d = _history_entry_start_date(e)
            return d == today if d else False

        def in_week(e: dict) -> bool:
            d = _history_entry_start_date(e)
            return d is not None and week_start <= d <= today

        today_entries = [e for e in entries if in_today(e)]
        week_entries = [e for e in entries if in_week(e)]

        return jsonify({
            "today": _aggregate_history_stats(today_entries),
            "last_7_days": _aggregate_history_stats(week_entries),
            "timezone": TIMEZONE,
            "script_filter": script_filter or None,
            "max_stored": _MAX_HISTORY,
            "note": "Stats exclude killed; buffer is rolling in-memory history.",
        })
    except Exception:
        logger.exception("[API] /api/history/stats failed")
        return jsonify({"status": "error", "message": "stats aggregation failed"}), 500


@_app.route("/api/pending")
def api_pending():
    """Scripts that should have run today but haven't yet."""
    today_str = _now_br().strftime("%Y-%m-%d")
    pending = _detect_pending_scripts()
    # Strip internal 'path' key from API response
    sanitized = [{k: v for k, v in p.items() if k != "path"} for p in pending]
    return jsonify({"pending": sanitized, "date": today_str, "total": len(sanitized)})

# ==============================================================
# MAIN
# ==============================================================

def _open_dashboard_in_browser() -> None:
    """Abre o dashboard no Chrome (Windows) se existir; senao no navegador padrao."""
    url = f"http://127.0.0.1:{PORT}/"
    try:
        if os.name == "nt":
            import subprocess
            for chrome in PATH_CHROME_CANDIDATES:
                if chrome.exists():
                    subprocess.Popen([str(chrome), url], shell=False)
                    logger.info(f"[BOOT] Chrome: {url}")
                    return
        webbrowser.open(url, new=1)
        logger.info(f"[BOOT] Navegador padrao: {url}")
    except Exception as exc:
        logger.warning(f"[BOOT] Nao foi possivel abrir o navegador ({url}): {exc}")


def _handle_exit(sig, frame):
    logger.info("\n[SHUTDOWN] Sinal recebido. Encerrando com segurança...")
    graceful_shutdown()
    logger.info("[SHUTDOWN] Tchau.")
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    logger.info("=" * 62)
    logger.info("  Abobi Server Cron | open-source edition")
    logger.info(f"  Version: {_SERVER_VERSION} | BQ sync + health governor")
    logger.info(f"  BigQuery registry : {TABLE_REGISTRO_AUTOMACOES}")
    logger.info(f"  Optional CRON XLSX: {PLANILHA_FILEROUTER_COB.name} (exists={PLANILHA_FILEROUTER_COB.is_file()})")
    logger.info(f"  Automations dir   : {DIRETORIO_AUTOMACOES}")
    if not PATH_AUTOMACOES.exists():
        logger.warning("  WARNING: automations folder missing — create it or set ABOBI_AUTOMATIONS_DIR.")
    logger.info(f"  Open browser      : {'yes' if OPEN_BROWSER else 'no'}")
    logger.info(f"  Max concurrent    : {MAX_PROCESSOS_SIMULTANEOS} (P1 bypasses this cap)")
    logger.info(f"  Health limits     : wait if CPU > {MAX_CPU_PERCENT}% or RAM > {MAX_RAM_PERCENT}%")
    logger.info(f"  Default timeout   : {DEFAULT_TIMEOUT_SECONDS}s")
    logger.info(f"  Log file          : {_LOG_FILE}")
    logger.info(f"  Dashboard file    : {'OK' if _DASHBOARD_FILE.exists() else 'MISSING'}")
    logger.info("=" * 62)

    iniciar_scheduler()

    flask_thread = threading.Thread(target=lambda: serve(_app, host=HOST, port=PORT, threads=6), daemon=True, name="waitress-server")
    flask_thread.start()

    if OPEN_BROWSER:
        def _browser_after_ready() -> None:
            time.sleep(BROWSER_DELAY_SEC)
            _open_dashboard_in_browser()

        threading.Thread(target=_browser_after_ready, daemon=True, name="open-browser").start()

    lan_ip = _get_local_ip()
    logger.info(f"[BOOT] Dashboard (local)  -> http://127.0.0.1:{PORT}/")
    logger.info(f"[BOOT] Dashboard (rede)   -> http://{lan_ip}:{PORT}/")
    logger.info(f"[BOOT] API                  -> http://127.0.0.1:{PORT}/api/status")
    logger.info("[BOOT] Servidor pronto. Ctrl+C para encerrar.\n")

    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        _handle_exit(None, None)

if __name__ == "__main__":
    main()