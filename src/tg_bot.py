"""
tg_bot.py — Telegram-бот для управления коллектором прямо из Telegram.

Простыми словами:
  Обычно бот просто отправляет отчёты.
  Но если запустить этот файл отдельно (на сервере или VPS),
  ты сможешь управлять ботом прямо из Telegram:

  /status    — сколько серверов найдено, когда обновление
  /top10     — топ-10 самых быстрых серверов
  /run       — запустить сбор прямо сейчас (не ждать часа)
  /history   — статистика надёжности серверов
  /links     — все ссылки на файлы подписок
  /help      — список команд

КАК ЗАПУСТИТЬ:
  1. Создай .env с TG_BOT_TOKEN и TG_CHAT_ID
  2. python src/tg_bot.py

  Бот будет работать пока не нажмёшь Ctrl+C.
  Для постоянной работы запусти на VPS через screen/tmux.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

log = logging.getLogger("tg_bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

OUTPUT_DIR  = Path(__file__).parent.parent / "output"
POLL_TIMEOUT = 30    # секунд ожидания новых сообщений (long polling)


# ── Отправка сообщений ────────────────────────────────────────────────────────

async def send(session: aiohttp.ClientSession, token: str, chat_id: str,
               text: str, parse_mode: str = "Markdown") -> bool:
    """Отправляет сообщение в Telegram."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with session.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
            return data.get("ok", False)
    except Exception as e:
        log.warning("send error: %s", e)
        return False


# ── Команды ───────────────────────────────────────────────────────────────────

def _cmd_status() -> str:
    """Возвращает текст статуса."""
    stats_file = OUTPUT_DIR / "stats.json"
    if not stats_file.exists():
        return "❌ Данных пока нет. Бот ещё не запускался."

    s   = json.loads(stats_file.read_text(encoding="utf-8"))
    lat = s.get("latency", {})
    upd = s.get("updated_msk", "")[:16].replace("T", " ")
    total = s.get("total_working", 0)
    tls   = s.get("tls_confirmed", 0)

    emoji = "✅" if total >= 50 else ("⚠️" if total >= 20 else "❌")
    by_p  = s.get("by_protocol", {})
    proto_lines = "\n".join(
        f"  • {k.upper()}: {v}"
        for k, v in by_p.items() if v > 0
    )

    return (
        f"{emoji} *Статус коллектора*\n"
        f"🕐 Обновлено: {upd} MSK\n\n"
        f"📊 Рабочих серверов: *{total}*\n"
        f"🔒 TLS подтверждено: *{tls}*\n\n"
        f"*По протоколам:*\n{proto_lines}\n\n"
        f"⏱ Задержка:\n"
        f"  min={lat.get('min_ms',0)}мс  "
        f"avg={lat.get('avg_ms',0)}мс  "
        f"p90={lat.get('p90_ms',0)}мс"
    )


def _cmd_top10() -> str:
    """Возвращает топ-10 серверов."""
    wf = OUTPUT_DIR / "TOP50.txt"
    if not wf.exists():
        return "❌ Файл TOP50.txt не найден. Дождись первого запуска."

    lines = [
        l for l in wf.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    ][:10]

    if not lines:
        return "❌ Топ-список пуст."

    result = "🏆 *Топ-10 серверов по скорости:*\n\n"
    for i, line in enumerate(lines, 1):
        # Берём только метку (после #)
        label = line.split("#", 1)[-1] if "#" in line else line[:60]
        result += f"{i}. `{label[:60]}`\n"
    return result


def _cmd_links(raw_base: str) -> str:
    """Возвращает ссылки на все файлы подписок."""
    files = [
        ("VLESS_WORKING.txt",  "✅ Все рабочие"),
        ("VLESS_ONLY.txt",     "🔷 VLESS"),
        ("VMESS_ONLY.txt",     "🔶 VMess"),
        ("TROJAN_ONLY.txt",    "🐴 Trojan"),
        ("HYSTERIA_ONLY.txt",  "⚡ Hysteria2"),
        ("TOP50.txt",          "🏆 TOP-50 быстрых"),
        ("TOP50_RELIABLE.txt", "🛡 TOP-50 надёжных"),
    ]
    lines = ["📥 *Ссылки на файлы подписок:*\n"]
    for fname, label in files:
        if (OUTPUT_DIR / fname).exists():
            lines.append(f"{label}:\n`{raw_base}/{fname}`\n")
    lines.append("\n_Скопируй ссылку и вставь в Karing / Hiddify / v2rayN_")
    return "\n".join(lines)


def _cmd_history() -> str:
    """Возвращает статистику истории."""
    hist_file = OUTPUT_DIR / "server_history.json"
    if not hist_file.exists():
        return (
            "📝 *История надёжности*\n\n"
            "Данных пока нет. Нужно минимум 3 запуска.\n"
            "История накапливается автоматически."
        )
    try:
        hist  = json.loads(hist_file.read_text(encoding="utf-8"))
        total = len(hist)
        rated = [
            sum(1 for c in h["checks"] if c["ok"]) / len(h["checks"])
            for h in hist.values()
            if len(h.get("checks", [])) >= 3
        ]
        if not rated:
            return f"📝 Серверов в базе: {total}\nМало данных для оценки (нужно ≥3 проверок)."

        avg_r    = round(sum(rated) / len(rated) * 100)
        reliable = sum(1 for s in rated if s >= 0.7)
        unstable = sum(1 for s in rated if s < 0.4)
        return (
            f"📝 *История надёжности серверов*\n\n"
            f"📦 Серверов в базе: *{total}*\n"
            f"🔬 Оценено (≥3 чек.): *{len(rated)}*\n"
            f"✅ Надёжных (≥70%): *{reliable}*\n"
            f"❌ Нестабильных (<40%): *{unstable}*\n"
            f"📊 Средний uptime: *{avg_r}%*"
        )
    except Exception as e:
        return f"❌ Ошибка чтения истории: {e}"


def _cmd_help() -> str:
    return (
        "🤖 *VLESS Collector Bot*\n\n"
        "Доступные команды:\n\n"
        "/status   — количество серверов и статистика\n"
        "/top10    — топ-10 самых быстрых серверов\n"
        "/links    — ссылки на файлы подписок\n"
        "/history  — надёжность серверов по истории\n"
        "/run      — запустить сбор прямо сейчас\n"
        "/help     — этот список\n"
    )


# ── Обработчик сообщений ──────────────────────────────────────────────────────

async def handle_message(session, token, chat_id, message, raw_base, run_lock):
    """Обрабатывает входящее сообщение и отвечает на команду."""
    msg_chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip().split("@")[0]  # убираем @botname

    # Отвечаем только тому chat_id который указан в настройках
    if msg_chat_id != chat_id:
        log.warning("Сообщение от неизвестного chat_id: %s", msg_chat_id)
        return

    log.info("Команда: %s", text)

    if text in ("/start", "/help"):
        reply = _cmd_help()
    elif text == "/status":
        reply = _cmd_status()
    elif text == "/top10":
        reply = _cmd_top10()
    elif text == "/links":
        reply = _cmd_links(raw_base)
    elif text == "/history":
        reply = _cmd_history()
    elif text == "/run":
        if run_lock.locked():
            reply = "⏳ Сбор уже выполняется, подожди…"
        else:
            await send(session, token, chat_id, "🚀 Запускаю сбор серверов…")
            asyncio.create_task(_run_collector(session, token, chat_id, run_lock))
            return
    else:
        reply = f"❓ Неизвестная команда: `{text}`\nНапиши /help"

    await send(session, token, chat_id, reply)


async def _run_collector(session, token, chat_id, run_lock):
    """Запускает полный пайплайн коллектора в фоне."""
    async with run_lock:
        try:
            import subprocess
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "src/main.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=Path(__file__).parent.parent,
            )
            await proc.wait()
            if proc.returncode == 0:
                # Отправляем свежую статистику
                reply = "✅ Сбор завершён!\n\n" + _cmd_status()
            else:
                reply = "❌ Сбор завершился с ошибкой. Проверь логи."
        except Exception as e:
            reply = f"❌ Не удалось запустить сбор: {e}"

    await send(session, token, chat_id, reply)


# ── Long polling ──────────────────────────────────────────────────────────────

async def polling_loop(token: str, chat_id: str, raw_base: str):
    """
    Основной цикл — постоянно опрашивает Telegram на новые сообщения.
    Long polling: Telegram держит соединение до 30 секунд,
    затем возвращает ответ (с сообщениями или пустой).
    """
    offset = 0
    run_lock = asyncio.Lock()
    log.info("🤖 Бот запущен. Жду команды в Telegram…")

    connector = aiohttp.TCPConnector(ssl=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        # Приветствие при старте
        now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%H:%M")
        await send(session, token, chat_id,
                   f"🤖 *Бот запущен* ({now} MSK)\nНапиши /help для списка команд.")

        while True:
            try:
                url = f"https://api.telegram.org/bot{token}/getUpdates"
                async with session.get(
                    url,
                    params={"offset": offset, "timeout": POLL_TIMEOUT},
                    timeout=aiohttp.ClientTimeout(total=POLL_TIMEOUT + 10),
                ) as resp:
                    data = await resp.json()

                if not data.get("ok"):
                    log.warning("getUpdates error: %s", data)
                    await asyncio.sleep(5)
                    continue

                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        await handle_message(
                            session, token, chat_id,
                            update["message"], raw_base, run_lock,
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("Polling error: %s", e)
                await asyncio.sleep(5)


# ── Точка входа ───────────────────────────────────────────────────────────────

def main():
    # Загружаем .env
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    token   = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID",   "").strip()

    if not token or not chat_id:
        print("""
❌ Не заданы TG_BOT_TOKEN и TG_CHAT_ID.

Создай файл .env (скопируй .env.example → .env) и заполни:
  TG_BOT_TOKEN=токен_от_BotFather
  TG_CHAT_ID=твой_числовой_id

Как получить:
  Токен: @BotFather → /newbot
  Chat ID: напиши боту, открой
           https://api.telegram.org/bot<ТОКЕН>/getUpdates
           найди "chat":{"id": ЧИСЛО}
""")
        sys.exit(1)

    # Определяем raw_base из переменной окружения или заглушка
    repo = os.environ.get("GITHUB_REPOSITORY", "YOUR_USERNAME/vless-collector")
    raw_base = f"https://raw.githubusercontent.com/{repo}/main/output"

    try:
        asyncio.run(polling_loop(token, chat_id, raw_base))
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен.")


if __name__ == "__main__":
    main()
