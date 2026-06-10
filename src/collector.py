"""
collector.py — скачивает VPN-конфиги из публичных источников на GitHub.
"""
import asyncio
import base64
import logging
from pathlib import Path

import aiohttp

log = logging.getLogger("collector")

SOURCES: list[dict] = [

    # ── Специализированные для РФ (обход ТСПУ/РКН) — ru=True ─────────────────
    {
        "name": "igareck BLACK_VLESS_RUS",
        "url":  "https://raw.githack.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
        "type": "raw", "ru": True,
    },
    {
        "name": "igareck WHITE_VLESS_RUS",
        "url":  "https://raw.githack.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_RUS.txt",
        "type": "raw", "ru": True,
    },
    {
        "name": "igareck VLESS_REALITY_RUS",
        "url":  "https://raw.githack.com/igareck/vpn-configs-for-russia/main/VLESS_REALITY_RUS.txt",
        "type": "raw", "ru": True,
    },
    {
        "name": "soroushmirzaei reality",
        "url":  "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/splitted/reality",
        "type": "raw", "ru": True,
    },
    {
        "name": "yebekhe TVC reality",
        "url":  "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/reality",
        "type": "raw", "ru": True,
    },
    {
        "name": "yebekhe TelegramV2rayCollector reality",
        "url":  "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/reality",
        "type": "raw", "ru": True,
    },
    {
        "name": "MatinGhanbari v2ray sub10",
        "url":  "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/xray/sub10.txt",
        "type": "raw", "ru": True,
    },

    # ── Общие источники (все протоколы) ───────────────────────────────────────
    {
        "name": "mahdibland V2RayAggregator",
        "url":  "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
        "type": "raw",
    },
    {
        "name": "barry-far V2Ray-Configs Sub1",
        "url":  "https://raw.githubusercontent.com/barry-far/V2Ray-Configs/main/Sub1.txt",
        "type": "raw",
    },
    {
        "name": "soroushmirzaei vless",
        "url":  "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/vless",
        "type": "raw",
    },
    {
        "name": "freefq free",
        "url":  "https://raw.githubusercontent.com/freefq/free/master/v2",
        "type": "base64",
    },
    {
        "name": "peasoft NoMoreVPN",
        "url":  "https://raw.githubusercontent.com/peasoft/NoMoreVPN/master/subscriptions/raw.txt",
        "type": "raw",
    },
    {
        "name": "mfuu v2ray",
        "url":  "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
        "type": "base64",
    },
    {
        "name": "vpei Free-Node-Merge",
        "url":  "https://raw.githubusercontent.com/vpei/Free-Node-Merge/main/o/node.txt",
        "type": "base64",
    },
    {
        "name": "Leon406 SubCrawler vless",
        "url":  "https://raw.githubusercontent.com/Leon406/SubCrawler/main/sub/share/vless",
        "type": "raw",
    },
]

PROTOCOLS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://", "tuic://")

# URL-ы RU-источников для быстрой проверки
RU_SOURCE_URLS: set[str] = {s["url"] for s in SOURCES if s.get("ru")}

FETCH_TIMEOUT = 20


def is_russia_bypass(config_str: str) -> bool:
    """
    Проверяет, подходит ли конфиг для обхода ТСПУ/РКН.

    Критерии — признаки VLESS Reality / XTLS Vision:
      security=reality       — главный признак Reality
      flow=xtls-rprx-vision  — XTLS Vision (лучший обход DPI)
      &pbk= или ?pbk=        — публичный ключ Reality
    """
    if not config_str.lower().startswith("vless://"):
        return False
    low = config_str.lower()
    if "security=reality" in low:        return True
    if "flow=xtls-rprx-vision" in low:   return True
    if "&pbk=" in low or "?pbk=" in low: return True
    return False


def extract_configs(text: str) -> list[str]:
    """Вытаскивает строки с VPN-ключами из текста."""
    configs = []
    for line in text.splitlines():
        line = line.strip()
        if any(line.startswith(p) for p in PROTOCOLS):
            configs.append(line)
    return configs


def decode_source(raw: str, fmt: str) -> str:
    """Декодирует base64-подписку или возвращает как есть."""
    if fmt != "base64":
        return raw
    try:
        padded = raw.strip() + "=" * (-len(raw.strip()) % 4)
        return base64.b64decode(padded).decode("utf-8", errors="ignore")
    except Exception:
        return raw


async def fetch_source_with_retry(
    session: aiohttp.ClientSession,
    source: dict,
    retries: int = 2,
) -> list[str]:
    """Скачивает один источник, при ошибке повторяет до 2 раз."""
    url  = source["url"]
    fmt  = source.get("type", "raw")
    name = source["name"]

    for attempt in range(retries + 1):
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
            ) as resp:
                if resp.status == 404:
                    log.warning("  %-45s  404", name)
                    return []
                if resp.status != 200:
                    log.warning("  %-45s  HTTP %s (попытка %d)", name, resp.status, attempt + 1)
                    if attempt < retries:
                        await asyncio.sleep(3)
                        continue
                    return []
                raw = await resp.text(errors="ignore")
            configs = extract_configs(decode_source(raw, fmt))
            log.info("  %-45s  %d конфигов", name, len(configs))
            return configs
        except asyncio.TimeoutError:
            log.warning("  %-45s  таймаут (попытка %d)", name, attempt + 1)
        except Exception as e:
            log.warning("  %-45s  %s (попытка %d)", name, e, attempt + 1)
        if attempt < retries:
            await asyncio.sleep(3)
    return []


async def collect_all() -> tuple[list[str], set[str]]:
    """
    Скачивает конфиги из всех источников параллельно.
    Подхватывает автообнаруженные источники из source_discovery.

    Возвращает:
      (unique_configs, ru_keys)
      ru_keys — ключи конфигов из RU-источников (для RU_BYPASS.txt)
    """
    all_sources = list(SOURCES)

    # Автообнаруженные источники
    try:
        from source_discovery import load_discovered
        discovered = load_discovered()
        if discovered:
            log.info("  📡 Автообнаружено источников: %d", len(discovered))
            existing = {s["url"] for s in all_sources}
            for s in discovered:
                if s["url"] not in existing:
                    all_sources.append(s)
    except Exception as e:
        log.debug("source_discovery недоступен: %s", e)

    log.info("📥 Скачиваю %d источников…", len(all_sources))
    connector = aiohttp.TCPConnector(ssl=False, limit=20)
    headers   = {"User-Agent": "Mozilla/5.0 (compatible; VPNCollector/1.0)"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        tasks   = [fetch_source_with_retry(session, src) for src in all_sources]
        results = await asyncio.gather(*tasks)

    all_configs: list[str] = []
    ru_keys:     set[str]  = set()

    for source, batch in zip(all_sources, results):
        is_ru = source.get("ru", False)
        for c in batch:
            all_configs.append(c)
            if is_ru:
                ru_keys.add(c.split("#")[0].rstrip("?& "))

    # Дедупликация
    seen, unique = set(), []
    for c in all_configs:
        k = c.split("#")[0].rstrip("?& ")
        if k not in seen:
            seen.add(k); unique.append(c)

    log.info("📦 Уникальных: %d  RU-источники: %d", len(unique), len(ru_keys))
    return unique, ru_keys
