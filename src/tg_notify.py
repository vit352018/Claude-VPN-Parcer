"""
tg_notify.py — отправляет отчёт в Telegram после каждого запуска.

Простыми словами:
  После того как бот проверил серверы, он отправляет тебе
  в Telegram сообщение — мол, всё готово, вот сколько серверов нашёл.

Как настроить (один раз):

  1. Создай бота в Telegram:
     - Напиши @BotFather в Telegram
     - Отправь /newbot
     - Придумай имя и username боту
     - Скопируй токен вида: 7123456789:AAF...xyz

  2. Узнай свой chat_id:
     - Напиши своему боту любое сообщение
     - Открой в браузере:
       https://api.telegram.org/bot<ТВОЙ_ТОКЕН>/getUpdates
     - Найди "chat":{"id": ЧИСЛО} — это и есть твой chat_id

  3. Добавь в GitHub Secrets:
     - TG_BOT_TOKEN = токен из шага 1
     - TG_CHAT_ID   = chat_id из шага 2

  4. Или в файл .env для локального запуска:
     TG_BOT_TOKEN=7123456789:AAF...xyz
     TG_CHAT_ID=123456789
"""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

log = logging.getLogger("tg_notify")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _flag(code: str) -> str:
    """ISO2 → emoji флаг страны."""
    code = (code or "").upper().strip()
    if len(code) != 2:
        return "🌐"
    return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)


def _build_message(stats: dict, yd_result: dict | None, elapsed_sec: int) -> str:
    """
    Собирает текст сообщения для Telegram из статистики.
    Использует Markdown-разметку которую понимает Telegram.
    """
    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    total   = stats.get("total_working", 0)
    tls_ok  = stats.get("tls_confirmed", 0)
    lat     = stats.get("latency", {})
    proto   = stats.get("by_protocol", {})
    countries = stats.get("top_countries", {})

    # Статус — хорошо или плохо?
    if total >= 50:
        status = "✅ Отлично"
    elif total >= 20:
        status = "⚠️ Нормально"
    else:
        status = "❌ Мало серверов"

    # Строки по протоколам
    proto_lines = ""
    for name, emoji in [("vless","🔷"),("vmess","🔶"),("trojan","🐴"),("hysteria","⚡"),("ss","🔲")]:
        cnt = proto.get(name, 0)
        if cnt > 0:
            proto_lines += f"  {emoji} {name.upper()}: *{cnt}*\n"

    # Топ-3 страны
    top_countries = ""
    for cc, cnt in list(countries.items())[:3]:
        top_countries += f"  {_flag(cc)} {cc}: {cnt}\n"

    # Яндекс Диск статус
    if yd_result:
        yd_line = f"☁️ Яндекс Диск: *{yd_result.get('uploaded', 0)}* файлов загружено\n"
    else:
        yd_line = "☁️ Яндекс Диск: не настроен\n"

    msg = (
        f"🔄 *VLESS Collector — обновление*\n"
        f"🕐 {now} MSK  |  за {elapsed_sec} сек\n"
        f"\n"
        f"{status}\n"
        f"📊 Рабочих серверов: *{total}*\n"
        f"🔒 TLS подтверждено: *{tls_ok}*\n"
        f"\n"
        f"*По протоколам:*\n"
        f"{proto_lines}"
        f"\n"
        f"*Задержка:*\n"
        f"  min: {lat.get('min_ms',0)}мс  "
        f"avg: {lat.get('avg_ms',0)}мс  "
        f"p90: {lat.get('p90_ms',0)}мс\n"
        f"\n"
        f"*Топ стран:*\n"
        f"{top_countries}"
        f"\n"
        f"{yd_line}"
    )
    return msg


async def send_report(
    stats: dict,
    yd_result: dict | None = None,
    elapsed_sec: int = 0,
    token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """
    Отправляет отчёт в Telegram.

    token   — берётся из переменной окружения TG_BOT_TOKEN если не передан
    chat_id — берётся из переменной окружения TG_CHAT_ID если не передан
    """
    token   = token   or os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = chat_id or os.environ.get("TG_CHAT_ID",   "").strip()

    if not token or not chat_id:
        log.info("📵 Telegram-уведомления не настроены (нет TG_BOT_TOKEN или TG_CHAT_ID)")
        return False

    text = _build_message(stats, yd_result, elapsed_sec)
    url  = TELEGRAM_API.format(token=token)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={
                    "chat_id":    chat_id,
                    "text":       text,
                    "parse_mode": "Markdown",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                if data.get("ok"):
                    log.info("📨 Telegram: отчёт отправлен")
                    return True
                else:
                    log.warning("📨 Telegram: ошибка — %s", data.get("description", "?"))
                    return False
    except Exception as e:
        log.warning("📨 Telegram: исключение — %s", e)
        return False


async def send_error(
    error_text: str,
    token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """Отправляет уведомление об ошибке в Telegram."""
    token   = token   or os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = chat_id or os.environ.get("TG_CHAT_ID",   "").strip()
    if not token or not chat_id:
        return False

    now = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    text = f"❌ *VLESS Collector — ошибка*\n🕐 {now} MSK\n\n```\n{error_text[:500]}\n```"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TELEGRAM_API.format(token=token),
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                return data.get("ok", False)
    except Exception:
        return False
