# -*- coding: utf-8 -*-
"""
Public template — safe to commit to GitHub.

This repository ships the open-source server as main.py and the UI as dashboard.html.

Some teams keep a private entry point and UI:
  - Copy main.py → ServidorCron.py (gitignored)
  - Copy dashboard.html → ServidorCron.html (gitignored)
  - Point PATH_DASHBOARD_HTML to ServidorCron.html inside your private ServidorCron.py

Never commit ServidorCron.py or ServidorCron.html if they contain internal data.

Run the public edition:
    python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def _run_public_server() -> None:
    import runpy

    root = Path(__file__).resolve().parent
    main_py = root / "main.py"
    if not main_py.is_file():
        print("main.py not found next to ServidorCron.example.py.", file=sys.stderr)
        sys.exit(1)
    runpy.run_path(str(main_py), run_name="__main__")


if __name__ == "__main__":
    _run_public_server()
