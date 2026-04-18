# Abobi Server Cron

<div align="center">

**Python job orchestrator · BigQuery registry · Web dashboard · MIT**

[English](#english-us) · [Português (Brasil)](#português-brasil)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)

</div>

---

## English (US)

### One-liner for your LinkedIn / portfolio

> **Abobi Server Cron** — Open-source Python orchestrator: automations registered in **Google BigQuery**, scheduled with **APScheduler**, executed with **priority queues** and a **CPU/RAM governor**, exposed through a **Flask + Waitress** dashboard with token login and REST API. Built for 24/7 operations teams who need visibility without microservices overhead.

### What this repository contains (safe for GitHub)

| Artifact | Purpose |
|----------|---------|
| `main.py` | **Canonical server** — scheduler, API, executor |
| `dashboard.html` | **Canonical web UI** |
| `ServidorCron.example.py` | Optional launcher that delegates to `main.py` (no secrets) |
| `ServidorCron.example.html` | Short note for teams that use a private HTML filename locally |
| `automacoes/` | Sample tree scanned for `.py` jobs (add your own scripts) |

**Not committed (see `.gitignore`):** `ServidorCron.py` and `ServidorCron.html` — use these names **only on private machines** when you fork `main.py` / `dashboard.html` for internal branding or confidential paths. Never push them if they contain employer-specific data.

### Features

- Cron scheduling (5-field crontab) with **APScheduler** + SQLite job store  
- **BigQuery** automation registry; optional **Excel** CRON overrides per business area  
- **Catch-up** for missed runs (`croniter`)  
- Priorities **P1 / P2 / P3**, concurrency cap, **resource governor**  
- Token login via e-mail (**Outlook COM** on Windows, or `ABOBI_MOCK_EMAIL` for dev)  
- REST JSON API + single-file dashboard  

### Quick start

```bash
git clone https://github.com/abobicaduco/ServidorCron.git
cd ServidorCron
pip install -r requirements.txt
copy .env.example .env   # optional; edit for your environment
python main.py
```

Open **http://127.0.0.1:5002/** (override with `ABOBI_PORT`).

### Configuration (high level)

| Variable | Purpose |
|----------|---------|
| `ABOBI_SECRET_KEY` | Flask session secret (set in production) |
| `ABOBI_EMAIL_DOMAIN` | Suffix for token e-mails (e.g. `@yourcompany.com`) |
| `ABOBI_ADMIN_USERS` | Comma-separated admin usernames |
| `ABOBI_MOCK_EMAIL` | `1` / `true` — log token to console instead of Outlook |
| `ABOBI_AUTOMATIONS_DIR` | Root folder to scan for `.py` files |
| `BQ_REGISTRO_TABLE` | BigQuery table id for the automation registry |
| `BQ_ACCESS_TABLE` | BigQuery table for `users` / `level_access` |

Details: `.env.example`.

### Security & publishing

- Do **not** commit `.env`, production credentials, or spreadsheets with real names.  
- If `ServidorCron.py` / `ServidorCron.html` were ever committed, remove them from Git history and rotate secrets:  
  `git rm --cached ServidorCron.py ServidorCron.html` then commit.  
- Run behind firewall/VPN in production; set a strong `ABOBI_SECRET_KEY`.

### License

[MIT](LICENSE) — English legal text + Portuguese informative translation + short EN summary.

---

## Português (Brasil)

### Frase para LinkedIn / portfólio

> **Abobi Server Cron** — Orquestrador Python open-source: cadastro de robôs no **BigQuery**, agendamento com **APScheduler**, execução com **fila por prioridade** e **governador de CPU/RAM**, painel **Flask + Waitress** com login por token e API REST. Pensado para equipes de operações que precisam de visibilidade sem stack de microserviços.

### O que entra no GitHub

| Arquivo | Função |
|---------|--------|
| `main.py` | **Servidor canônico** — agendador, API, executor |
| `dashboard.html` | **Interface web canônica** |
| `ServidorCron.example.py` | Launcher opcional que chama `main.py` (sem dados confidenciais) |
| `ServidorCron.example.html` | Nota para quem usa nome de HTML privado localmente |
| `automacoes/` | Pasta exemplo para seus `.py` |

**Não versionar** (`.gitignore`): `ServidorCron.py` e `ServidorCron.html` — nomes usados em **cópias internas** quando você duplica `main.py` / `dashboard.html` com marca ou caminhos da empresa. **Não envie** ao GitHub se houver dados do empregador.

### Início rápido

```bash
git clone https://github.com/abobicaduco/ServidorCron.git
cd ServidorCron
pip install -r requirements.txt
copy .env.example .env
python main.py
```

Acesse **http://127.0.0.1:5002/** (porta padrão; altere com `ABOBI_PORT`).

### Fluxo recomendado (empresa vs. público)

1. **Repositório público:** trabalhe com `main.py` + `dashboard.html`.  
2. **Máquina corporativa:** copie `main.py` → `ServidorCron.py`, `dashboard.html` → `ServidorCron.html`, ajuste caminhos e textos **apenas localmente**; mantenha esses dois arquivos fora do Git.  
3. Use `deploy_para_github.bat.example` como modelo para copiar **só** os artefatos open-source para o clone que vai subir.

### Licença

[MIT](LICENSE) — texto legal em inglês + tradução informativa em português.

---

## Replacing remote history on GitHub

If `main` already exists with older commits, your first push may be rejected. Options:

1. **Overwrite** (only if intended): `git push --force-with-lease origin main`  
2. **Merge**: `git pull origin main --allow-unrelated-histories`, resolve, then push.

---

## Links

- **License:** [MIT](LICENSE)  
- **Suggested repo URL:** `https://github.com/abobicaduco/ServidorCron` (adjust if your fork name differs)
