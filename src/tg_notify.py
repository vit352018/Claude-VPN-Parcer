"""
tg_notify.py — отправляет отчёт в Telegram после каждого запуска.
"""
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

log = logging.getLogger("tg_notify")
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _flag(code: str) -> str:
    code = (code or "").upper().strip()
    if len(code) == 2:
        try: return chr(0x1F1E6+ord(code[0])-65)+chr(0x1F1E6+ord(code[1])-65)
        except Exception: pass
    return "🌐"


def _build_message(stats: dict, yd_result: dict | None, elapsed_sec: int) -> str:
    now    = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    total  = stats.get("total_working", 0)
    tls_ok = stats.get("tls_confirmed", 0)
    lat    = stats.get("latency", {})
    proto  = stats.get("by_protocol", {})
    ru_cnt = proto.get("ru_bypass", 0)
    countries = stats.get("top_countries", {})

    status = "✅ Отлично" if total >= 50 else ("⚠️ Нормально" if total >= 20 else "❌ Мало")

    proto_lines = ""
    for name, emoji in [("vless","🔷"),("vmess","🔶"),("trojan","🐴"),("hysteria","⚡"),("ss","🔲")]:
        cnt = proto.get(name, 0)
        if cnt: proto_lines += f"  {emoji} {name.upper()}: *{cnt}*\n"

    top3 = "".join(f"  {_flag(cc)} {cc}: {cnt}\n" for cc, cnt in list(countries.items())[:3])
    yd_line = (f"☁️ Яндекс Диск: *{yd_result.get('uploaded', 0)}* файлов\n" if yd_result
               else "☁️ Яндекс Диск: не настроен\n")

    return (
        f"🔄 *VLESS Collector — обновление*\n"
        f"🕐 {now} MSK  |  за {elapsed_sec} сек\n\n"
        f"{status}\n"
        f"📊 Рабочих: *{total}*  🔒 TLS: *{tls_ok}*\n"
        f"🇷🇺 Обход РКН (Reality): *{ru_cnt}*\n\n"
        f"*По протоколам:*\n{proto_lines}\n"
        f"⏱ Задержка: min={lat.get('min_ms',0)}мс avg={lat.get('avg_ms',0)}мс\n\n"
        f"*Топ стран:*\n{top3}\n"
        f"{yd_line}"
    )


async def send_report(stats: dict, yd_result: dict | None = None,
                      elapsed_sec: int = 0, token: str | None = None,
                      chat_id: str | None = None) -> bool:
    token   = token   or os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = chat_id or os.environ.get("TG_CHAT_ID",   "").strip()
    if not token or not chat_id:
        log.info("📵 Telegram не настроен")
        return False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TELEGRAM_API.format(token=token),
                json={"chat_id": chat_id, "text": _build_message(stats, yd_result, elapsed_sec),
                      "parse_mode": "Markdown"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                ok   = data.get("ok", False)
                if ok: log.info("📨 Telegram: отчёт отправлен")
                else:  log.warning("📨 Telegram: %s", data.get("description"))
                return ok
    except Exception as e:
        log.warning("📨 Telegram: %s", e)
        return False


async def send_error(error_text: str, token: str | None = None, chat_id: str | None = None) -> bool:
    token   = token   or os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = chat_id or os.environ.get("TG_CHAT_ID",   "").strip()
    if not token or not chat_id: return False
    now  = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%d.%m.%Y %H:%M")
    text = f"❌ *VLESS Collector — ошибка*\n🕐 {now} MSK\n\n```\n{error_text[:500]}\n```"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TELEGRAM_API.format(token=token),
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                return (await resp.json()).get("ok", False)
    except Exception:
        return False
