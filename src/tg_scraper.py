"""
tg_scraper.py — парсит публичные Telegram-каналы с VPN-ключами.
"""
import asyncio
import logging
import re
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

log = logging.getLogger("tg_scraper")

PUBLIC_CHANNELS = [
    "v2ray_free_conf", "VlessConfig", "v2rayng_config",
    "DirectVPN", "free_shadowsocks", "v2ray1_ng",
]

PROTOCOLS  = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://", "tuic://")
CONFIG_RE  = re.compile(r'((?:vless|vmess|trojan|ss|hysteria2|hy2|tuic)://[^\s<>"\']+)', re.IGNORECASE)


async def scrape_channel(session: aiohttp.ClientSession, channel: str, limit: int = 5) -> list[str]:
    """Парсит последние посты канала через t.me/s/<channel>."""
    configs: list[str] = []
    try:
        async with session.get(
            f"https://t.me/s/{channel}",
            timeout=aiohttp.ClientTimeout(total=8),
            headers={"User-Agent": "Mozilla/5.0"},
        ) as resp:
            if resp.status != 200:
                log.warning("  tg/%-20s  HTTP %s", channel, resp.status)
                return []
            html = await resp.text(errors="ignore")
        soup     = BeautifulSoup(html, "html.parser")
        messages = soup.find_all("div", class_="tgme_widget_message_text")[-limit * 2:]
        for msg in messages:
            configs.extend(CONFIG_RE.findall(msg.get_text(separator="\n")))
        log.info("  tg/%-20s  %d конфигов", channel, len(configs))
    except Exception as e:
        log.warning("  tg/%-20s  %s", channel, e)
    return configs


async def collect_from_telegram(channels: Optional[list[str]] = None) -> list[str]:
    """Собирает конфиги из всех Telegram-каналов параллельно."""
    channels = channels or PUBLIC_CHANNELS
    log.info("📱 Парсю Telegram-каналы (%d)…", len(channels))
    connector = aiohttp.TCPConnector(ssl=False, limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(*[scrape_channel(session, ch) for ch in channels])
    all_configs: list[str] = []
    for batch in results:
        all_configs.extend(batch)
    seen, unique = set(), []
    for c in all_configs:
        k = c.split("#")[0]
        if k not in seen:
            seen.add(k); unique.append(c)
    log.info("📱 Telegram: %d уникальных конфигов", len(unique))
    return unique
