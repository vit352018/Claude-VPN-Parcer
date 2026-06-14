"""
config.py — все настройки проекта в одном месте.
Значения берутся из .env (локально) или GitHub Secrets (в облаке).
"""
import os
from pathlib import Path

# Загрузка .env
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# GitHub
_repo = os.environ.get("GITHUB_REPOSITORY", "YOUR_USERNAME/vless-collector")
GITHUB_USERNAME, _, GITHUB_REPO = _repo.partition("/")
RAW_BASE  = f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{GITHUB_REPO}/main/output"
PAGES_URL = f"https://{GITHUB_USERNAME}.github.io/{GITHUB_REPO}/"

# Яндекс Object Storage (S3) — даёт ПОСТОЯННЫЕ прямые ссылки, читается Karing
YANDEX_S3_BUCKET     : str = os.environ.get("YANDEX_S3_BUCKET",     "").strip()
YANDEX_S3_ACCESS_KEY : str = os.environ.get("YANDEX_S3_ACCESS_KEY", "").strip()
YANDEX_S3_SECRET_KEY : str = os.environ.get("YANDEX_S3_SECRET_KEY", "").strip()

# Яндекс Диск — запасные варианты (без гарантии постоянных прямых ссылок)
YANDEX_TOKEN  : str = os.environ.get("YANDEX_TOKEN",  "").strip()
YANDEX_LOGIN  : str = os.environ.get("YANDEX_LOGIN",  "").strip()
YANDEX_PASS   : str = os.environ.get("YANDEX_PASS",   "").strip()
YANDEX_FOLDER : str = os.environ.get("YANDEX_FOLDER", "vless-collector").strip()

# Telegram
TG_BOT_TOKEN : str = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID   : str = os.environ.get("TG_CHAT_ID",   "").strip()

# Параметры тестирования
TCP_TIMEOUT   : float = float(os.environ.get("TCP_TIMEOUT",   "3.0"))
MAX_WORKERS   : int   = int(os.environ.get("MAX_WORKERS",     "150"))
MAX_LATENCY   : int   = int(os.environ.get("MAX_LATENCY",     "4000"))
FETCH_TIMEOUT : int   = int(os.environ.get("FETCH_TIMEOUT",   "10"))
# Максимум конфигов для тестирования (800 — укладывается в 15 минут)
MAX_CONFIGS   : int   = int(os.environ.get("MAX_CONFIGS",     "800"))

# История
RELIABILITY_MIN    : float = float(os.environ.get("RELIABILITY_MIN",    "0.4"))
HISTORY_PRUNE_DAYS : int   = int(os.environ.get("HISTORY_PRUNE_DAYS",   "7"))
