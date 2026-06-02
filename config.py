"""
config.py — ВСЕ настройки проекта в одном месте.

Простыми словами: это как пульт управления ботом.
Хочешь изменить поведение — меняй здесь, а не в глубине кода.

Переменные читаются из .env (для локального запуска)
или из GitHub Secrets (для запуска в облаке).
"""

import os
from pathlib import Path

# ── Загрузка .env файла ────────────────────────────────────────────────────────
# Если рядом есть файл .env — читаем настройки из него.
# Это удобно при запуске на своём компьютере.
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── GitHub (заполняется автоматически в Actions) ───────────────────────────────
_repo = os.environ.get("GITHUB_REPOSITORY", "YOUR_USERNAME/vless-collector")
GITHUB_USERNAME, _, GITHUB_REPO = _repo.partition("/")
# Ссылка на выходные файлы (для README и HTML-дашборда)
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{GITHUB_REPO}/main/output"
PAGES_URL = f"https://{GITHUB_USERNAME}.github.io/{GITHUB_REPO}/"

# ── Яндекс Диск (WebDAV) ──────────────────────────────────────────────────────
# Логин и пароль приложения из https://id.yandex.ru/security/app-passwords
# Добавь в GitHub: Settings → Secrets → Actions
YANDEX_LOGIN  : str = os.environ.get("YANDEX_LOGIN",  "").strip()
YANDEX_PASS   : str = os.environ.get("YANDEX_PASS",   "").strip()
YANDEX_FOLDER : str = os.environ.get("YANDEX_FOLDER", "vless-collector").strip()

# ── Telegram-уведомления ──────────────────────────────────────────────────────
# Как получить: читай комментарии в src/tg_notify.py
TG_BOT_TOKEN : str = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID   : str = os.environ.get("TG_CHAT_ID",   "").strip()

# ── Параметры тестирования серверов ───────────────────────────────────────────
# Сколько секунд ждать ответа от сервера (5 — разумный баланс)
TCP_TIMEOUT   : float = float(os.environ.get("TCP_TIMEOUT",  "5.0"))
# Сколько серверов проверять одновременно (больше = быстрее, но нагрузка)
MAX_WORKERS   : int   = int(os.environ.get("MAX_WORKERS",    "80"))
# Максимальная задержка сервера в мс (4000 = 4 секунды — уже очень медленно)
MAX_LATENCY   : int   = int(os.environ.get("MAX_LATENCY",    "4000"))
# Сколько секунд ждать при скачивании источника
FETCH_TIMEOUT : int   = int(os.environ.get("FETCH_TIMEOUT",  "20"))

# ── Параметры истории ─────────────────────────────────────────────────────────
# Серверы с надёжностью ниже этого порога будут помечены как нестабильные
# 0.4 = 40% uptime — сервер работал меньше чем в половине проверок
RELIABILITY_MIN : float = float(os.environ.get("RELIABILITY_MIN", "0.4"))
# Через сколько дней забыть сервер которого давно не видели
HISTORY_PRUNE_DAYS : int = int(os.environ.get("HISTORY_PRUNE_DAYS", "7"))
