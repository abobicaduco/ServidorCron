# Abobi Server Cron

**English (US)** | [Português (Brasil)](#português-brasil)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Abobi Server Cron is a **single-process Python orchestrator**: it reads automation metadata from **Google BigQuery** (or local Excel fallbacks), schedules jobs with **APScheduler**, runs scripts with **priority queues** and a **health governor** (CPU/RAM), and serves a **web dashboard** (Flask + Waitress) for monitoring and admin actions.

Originally derived from an internal operations server; this repository is a **sanitized, open-source** edition with **no proprietary paths, bank names, or secrets**.

---

## Features

- Dynamic **cron** scheduling (standard 5-field crontab) with APScheduler + SQLite job store  
- **BigQuery** registry + optional **Excel** overrides for specific business areas  
- **Catch-up** for missed runs (requires `croniter`)  
- **Priority queue** (P1 / P2 / P3), concurrency limit, **resource governor**  
- **Token login** via corporate e-mail (Outlook COM on Windows) or `ABOBI_MOCK_EMAIL` for dev  
- REST **JSON API** + single-file **dashboard** (`dashboard.html`)

---

## Quick start

```bash
git clone https://github.com/abobicaduco/ServidorCron.git
cd ServidorCron
pip install -r requirements.txt
copy .env.example .env   # Windows — optional; edit values
python main.py
```

Open **http://127.0.0.1:5002/** (default port; override with `ABOBI_PORT`).

### Configuration

| Variable | Purpose |
|----------|---------|
| `ABOBI_SECRET_KEY` | Flask session secret (set in production) |
| `ABOBI_EMAIL_DOMAIN` | Suffix for token e-mails, e.g. `@yourcompany.com` |
| `ABOBI_ADMIN_USERS` | Comma-separated usernames with admin role |
| `ABOBI_EXTRA_VIEWERS` | Extra viewer logins |
| `ABOBI_MOCK_EMAIL` | `1` / `true` — log token to console instead of Outlook |
| `ABOBI_AUTOMATIONS_DIR` | Root folder to scan for `.py` files |
| `ABOBI_COBRANCA_CRON_XLSX` | Optional workbook for CRON overrides |
| `BQ_REGISTRO_TABLE` | BigQuery table id for the automation registry |
| `BQ_ACCESS_TABLE` | BigQuery table id for `users` / `level_access` |
| `ABOBI_PORT` | HTTP port (default `5002`) |

Place **`access_registry.xlsx`** next to `main.py` if you are not using BigQuery for ACLs (columns `users`, `level_access`). See `.env.example`.

### BigQuery

Use Application Default Credentials (ADC), e.g. `gcloud auth application-default login` for development, or a service account on servers. Tables must match the column names expected in code (`PYTHON_NAME`, `CRON`, `IS_ACTIVE`, etc. for the registry).

---

## Project layout

| File / folder | Role |
|----------------|------|
| `main.py` | Backend, scheduler, API |
| `dashboard.html` | Web UI |
| `automacoes/` | Default tree scanned for `.py` scripts |
| `requirements.txt` | Pinned dependencies |

---

## Security

- Do **not** commit `.env`, real `access_registry.xlsx`, or production credentials.  
- Change `ABOBI_SECRET_KEY` before any public deployment.  
- Run behind a firewall / VPN; bind to `127.0.0.1` or use a reverse proxy if needed.

---

## License

[MIT](LICENSE) — Copyright (c) 2026 abobicaduco.

---

## LinkedIn / portfolio blurb (short)

> **Abobi Server Cron** — Open-source Python job orchestrator with BigQuery-backed registry, APScheduler, priority queue, resource governor, and Flask dashboard. Token auth, REST API, production-oriented logging. [MIT License](https://github.com/abobicaduco/ServidorCron)

---

# Português (Brasil)

## Visão geral

O **Abobi Server Cron** é um orquestrador **Python** em processo único: lê metadados de automações no **Google BigQuery** (ou planilhas Excel locais), agenda tarefas com **APScheduler**, executa scripts com **fila por prioridade** e **governador de recursos** (CPU/RAM), e expõe um **painel web** (Flask + Waitress) para monitoramento e ações de administrador.

Este repositório é uma edição **sanitizada e open-source**, **sem** caminhos internos de empresa, nomes de banco ou segredos.

## Início rápido

```bash
git clone https://github.com/abobicaduco/ServidorCron.git
cd ServidorCron
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Acesse **http://127.0.0.1:5002/** (porta padrão; altere com `ABOBI_PORT`).

## Configuração

As variáveis de ambiente principais estão em **`.env.example`**. Para desenvolvimento sem Outlook, use `ABOBI_MOCK_EMAIL=1` — o token aparece no log.

## Licença

[MIT](LICENSE) — Copyright (c) 2026 abobicaduco.

## Texto curto para LinkedIn (PT-BR)

> **Abobi Server Cron** — Orquestrador Python open-source com cadastro no BigQuery, APScheduler, fila por prioridade, governador de CPU/RAM e dashboard Flask. Autenticação por token, API REST e logs para operação. Licença MIT: [github.com/abobicaduco/ServidorCron](https://github.com/abobicaduco/ServidorCron)
