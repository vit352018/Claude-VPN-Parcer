"""
Telegram scraper — собирает конфиги из публичных каналов
через web-интерфейс t.me (без API-ключа).
Для работы с приватными каналами нужен Telegram API key.
"""

import asyncio
import logging
import re
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

log = logging.getLogger("tg_scraper")

# Публичные каналы с бесплатными конфигами
PUBLIC_CHANNELS = [
    "v2ray_free_conf",
    "freev2rays",
    "free_v2rayyy",
    "VlessConfig",
    "v2rayng_config",
    "proxystore11",
    "DirectVPN",
    "vpnfail_v2ray",
    "free_shadowsocks",
    "v2ray1_ng",
]

PROTOCOLS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://", "tuic://")
CONFIG_RE  = re.compile(r'((?:vless|vmess|trojan|ss|hysteria2|hy2|tuic)://[^\s<>"\']+)', re.IGNORECASE)


async def scrape_channel(
    session: aiohttp.ClientSession,
    channel: str,
    limit: int = 5,
) -> list[str]:
    """
    Парсит последние посты публичного Telegram-канала через t.me/s/<channel>.
    Возвращает список найденных конфигов.
    """
    url = f"https://t.me/s/{channel}"
    configs: list[str] = []
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"User-Agent": "Mozilla/5.0 (compatible; VPNCollector/1.0)"},
        ) as resp:
            if resp.status != 200:
                log.warning("  tg/%-25s  HTTP %s", channel, resp.status)
                return []
            html = await resp.text(errors="ignore")

        soup = BeautifulSoup(html, "html.parser")
        messages = soup.find_all("div", class_="tgme_widget_message_text")[-limit * 2:]

        for msg in messages:
            text = msg.get_text(separator="\n")
            found = CONFIG_RE.findall(text)
            configs.extend(found)

        log.info("  tg/%-25s  %d конфигов", channel, len(configs))
    except Exception as e:
        log.warning("  tg/%-25s  ошибка: %s", channel, e)

    return configs


async def collect_from_telegram(channels: Optional[list[str]] = None) -> list[str]:
    """Собирает конфиги из всех Telegram-каналов параллельно."""
    channels = channels or PUBLIC_CHANNELS
    log.info("📱 Парсю Telegram-каналы (%d)…", len(channels))

    connector = aiohttp.TCPConnector(ssl=False, limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [scrape_channel(session, ch) for ch in channels]
        results = await asyncio.gather(*tasks)

    all_configs: list[str] = []
    for batch in results:
        all_configs.extend(batch)

    # Дедупликация
    seen: set[str] = set()
    unique: list[str] = []
    for c in all_configs:
        key = c.split("#")[0]
        if key not in seen:
            seen.add(key)
            unique.append(c)

    log.info("📱 Telegram итого: %d уникальных конфигов", len(unique))
    return unique


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    configs = asyncio.run(collect_from_telegram())
    for c in configs[:5]:
        print(c[:80])
