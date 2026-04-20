# Abobi Server Cron

<div align="center">

**Python job orchestrator · BigQuery registry · Web dashboard · MIT**

[English](#english-us) · [Português (Brasil)](#português-brasil)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10–3.14](https://img.shields.io/badge/python-3.10–3.14-blue.svg)](https://www.python.org/) (3.12 LTS recommended on locked-down Windows)

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

### Troubleshooting (Windows)

**`ImportError: DLL load failed ... _bounded_integers: An Application Control policy has blocked this file`**

This is **not a bug in this repo**. Windows **WDAC / AppLocker** (or similar) is blocking a native extension shipped with **NumPy** (used by **pandas**). It often happens when packages live under the per-user path, e.g. `AppData\Roaming\Python\Python314\site-packages`.

**What to try (in order):**

1. **Virtual environment inside the project** (DLLs under the repo folder are sometimes allowed):
   ```powershell
   cd G:\My Drive\python\ServerCron
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -U pip
   pip install -r requirements.txt
   python main.py
   ```
   If `py -3.12` is not installed, install **Python 3.11 or 3.12** from [python.org](https://www.python.org/downloads/) (LTS; better ecosystem support than 3.14 for scientific wheels).

2. **Ask IT** to allow your Python interpreter and the `numpy` `.pyd` files under your venv path, or to whitelist the official Python install directory.

3. **Avoid** relying only on `pip install --user` into `Roaming\Python` on locked-down PCs; prefer a **venv** or a **conda** env in a path your policy trusts.

**`py -3.12` → “No suitable Python runtime found”**

The [Python Launcher for Windows](https://docs.python.org/3/using/windows.html#python-launcher-for-windows) only lists versions you actually installed.

1. Download **Python 3.12.x** from [python.org/downloads/windows](https://www.python.org/downloads/windows/) (64-bit installer).
2. Run the installer: enable **“Add python.exe to PATH”** and **“Install launcher for all users”** (if your policy allows).
3. Confirm: `py -0` or `py -3.12 -V`.
4. Create the venv: `py -3.12 -m venv .venv` then `.\.venv\Scripts\Activate.ps1`.

If you must stay on **Python 3.14**, use a **venv** and `pip install -r requirements.txt` from this repo (pandas/sqlalchemy versions include wheels / fixes for 3.13+). If pip still tries to **compile** pandas, you are missing a matching wheel — install **3.12** or ask IT for a supported Python build.

**`TypeError: Can't replace canonical symbol for '__firstlineno__'` (SQLAlchemy)**

Caused by **SQLAlchemy older than 2.0.36** on **Python 3.13+**. This repository pins **SQLAlchemy 2.0.38**. Upgrade: `pip install -U "sqlalchemy>=2.0.38"`.

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

### Problemas no Windows

**`ImportError: DLL load failed ... _bounded_integers: An Application Control policy has blocked this file`**

Isso é **política de segurança do Windows** (WDAC / AppLocker etc.), não falha do código. O carregamento de uma DLL do **NumPy** (dependência do **pandas**) foi **bloqueado**. Costuma ocorrer com pacotes em `AppData\Roaming\Python\...` (Python “de usuário”).

**O que fazer:**

1. Criar um **venv na pasta do projeto** e reinstalar dependências (muitas empresas liberam o disco do projeto e bloqueiam só `Roaming`):
   ```powershell
   cd G:\My Drive\python\ServerCron
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -U pip
   pip install -r requirements.txt
   python main.py
   ```
   Se não tiver o launcher `py`, use o executável completo do Python 3.11/3.12 instalado.

2. Pedir ao **time de TI** exceção para o `python.exe` que você usa e para os `.pyd` do NumPy no caminho do `.venv`, ou usar uma instalação Python **aprovada pela empresa**.

3. Preferir **Python 3.11 ou 3.12** (LTS) em vez de 3.14 para wheels de `pandas`/`numpy` mais estáveis.

**`py -3.12` → “No suitable Python runtime found”**

O launcher `py` só encontra versões **instaladas**. Baixe o instalador **Windows x64** em [python.org/downloads/windows](https://www.python.org/downloads/windows/), marque **Add to PATH** / **py launcher**, depois teste `py -0` e `py -3.12 -m venv .venv`.

**`TypeError: Can't replace canonical symbol for '__firstlineno__'` (SQLAlchemy)**

Incompatibilidade de **SQLAlchemy antigo** com **Python 3.13+**. Este repositório usa **SQLAlchemy ≥ 2.0.38**. Atualize: `pip install -U "sqlalchemy>=2.0.38"`.

**Pandas tentando compilar com Meson / `vswhere`**

Em **Python 3.14**, versões antigas de `pandas` podem não ter wheel no Windows e o `pip` cai em build local (exige Visual Studio). Use as versões do `requirements.txt` atuais (**pandas 2.3.x**) ou instale **Python 3.12** e um **venv** no projeto.

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
