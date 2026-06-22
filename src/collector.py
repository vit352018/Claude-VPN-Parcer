"""
collector.py — скачивает конфиги из GitHub-источников.

Источники делятся на три типа (поле в словаре):
  ru=True        — специальные для РФ (Reality, XTLS)
  universal=True — новые источники igareck (BL+WT коллекция)
  (обычные)      — общие бесплатные ноды

Файлы на выходе:
  VLESS_WORKING.txt  — все рабочие
  RU_BYPASS.txt      — только Reality/XTLS (обход ТСПУ)
  UNIVERSAL_BL_WT.txt — серверы из universal-источников
"""

import asyncio
import base64
import logging
import re
from pathlib import Path
from typing import Optional

import aiohttp

log = logging.getLogger("collector")

SOURCES: list[dict] = [

    # ── Специальные для РФ (Reality + XTLS) ──────────────────────────────────
    {
        "name": "igareck BLACK_VLESS_RUS",
        "url":  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
        "type": "raw", "ru": True,
    },
    {
        "name": "igareck WHITE_VLESS_RUS",
        "url":  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_RUS.txt",
        "type": "raw", "ru": True,
    },
    {
        "name": "igareck VLESS_REALITY_RUS",
        "url":  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/VLESS_REALITY_RUS.txt",
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
        "name": "MatinGhanbari sub10",
        "url":  "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/xray/sub10.txt",
        "type": "raw", "ru": True,
    },

    # ── Universal BL+WT (новые источники igareck) ─────────────────────────────
    # Эти источники собираются в отдельный файл UNIVERSAL_BL_WT.txt
    {
        "name": "igareck WHITE-SNI-RU-all",
        "url":  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-SNI-RU-all.txt",
        "type": "raw", "universal": True,
    },
    {
        "name": "igareck WHITE-CIDR-RU-checked",
        "url":  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/WHITE-CIDR-RU-checked.txt",
        "type": "raw", "universal": True,
    },
    {
        "name": "igareck Vless-Reality-White-Lists-Rus-Mobile",
        "url":  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
        "type": "raw", "universal": True,
    },
    {
        "name": "igareck BLACK_VLESS_RUS_mobile",
        "url":  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt",
        "type": "raw", "universal": True,
    },
    {
        "name": "igareck BLACK_SS+All_RUS",
        "url":  "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_SS%2BAll_RUS.txt",
        "type": "raw", "universal": True,
    },

    # ── Общие источники (все протоколы) ───────────────────────────────────────
    {
        "name": "mahdibland V2RayAggregator",
        "url":  "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
        "type": "raw",
    },
    {
        "name": "barry-far Sub1",
        "url":  "https://raw.githubusercontent.com/barry-far/V2Ray-Configs/main/Sub1.txt",
        "type": "raw",
    },
    {
        "name": "soroushmirzaei vless",
        "url":  "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/vless",
        "type": "raw",
    },
    {
        "name": "peasoft NoMoreVPN",
        "url":  "https://raw.githubusercontent.com/peasoft/NoMoreVPN/master/subscriptions/raw.txt",
        "type": "raw",
    },
    {
        "name": "freefq free",
        "url":  "https://raw.githubusercontent.com/freefq/free/master/v2",
        "type": "base64",
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

# Протоколы которые ищем в тексте
PROTOCOLS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://", "tuic://")

# URL источников помеченных ru=True — для приоритизации в тесте
RU_SOURCE_URLS: set[str] = {s["url"] for s in SOURCES if s.get("ru")}

# URL источников помеченных universal=True
UNIVERSAL_SOURCE_URLS: set[str] = {s["url"] for s in SOURCES if s.get("universal")}

# Параметры скачивания (перекрываются из config.py через main.py)
FETCH_TIMEOUT = 10


def is_russia_bypass(config_str: str) -> bool:
    """
    Проверяет является ли конфиг VLESS Reality / XTLS Vision —
    единственный надёжный способ обхода ТСПУ/DPI в РФ.

    Признаки:
      security=reality      — главный признак Reality
      flow=xtls-rprx-vision — XTLS Vision
      &pbk= или ?pbk=       — публичный ключ Reality
    """
    if not config_str.lower().startswith("vless://"):
        return False
    low = config_str.lower()
    if "security=reality"        in low: return True
    if "flow=xtls-rprx-vision"   in low: return True
    if "&pbk=" in low or "?pbk=" in low: return True
    return False


def extract_configs(text: str) -> list[str]:
    """Вытаскивает все строки начинающиеся с известных протоколов."""
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
                url,
                timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
            ) as resp:
                if resp.status == 404:
                    log.warning("  %-50s 404", name)
                    return []
                if resp.status != 200:
                    log.warning("  %-50s HTTP %s (попытка %d)", name, resp.status, attempt + 1)
                    if attempt < retries:
                        await asyncio.sleep(3)
                        continue
                    return []
                raw = await resp.text(errors="ignore")

            decoded = decode_source(raw, fmt)
            configs = extract_configs(decoded)
            log.info("  %-50s %d конфигов", name, len(configs))
            return configs

        except asyncio.TimeoutError:
            log.warning("  %-50s таймаут (попытка %d)", name, attempt + 1)
        except Exception as e:
            log.warning("  %-50s ошибка: %s (попытка %d)", name, e, attempt + 1)

        if attempt < retries:
            await asyncio.sleep(3)

    return []


async def collect_all() -> tuple[list[str], set[str], set[str]]:
    """
    Скачивает конфиги из всех источников параллельно.
    Автоматически подхватывает источники из source_discovery.

    Возвращает:
      (unique_configs, ru_keys, universal_keys)

      ru_keys        — ключи конфигов из RU-источников (для приоритизации)
      universal_keys — ключи конфигов из universal-источников (для UNIVERSAL_BL_WT.txt)
    """
    all_sources = list(SOURCES)

    # Добавляем автообнаруженные источники
    try:
        from source_discovery import load_discovered
        discovered = load_discovered()
        if discovered:
            log.info("  📡 Автообнаружено: %d источников", len(discovered))
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
    ru_keys:        set[str] = set()
    universal_keys: set[str] = set()

    for source, batch in zip(all_sources, results):
        is_ru        = source.get("ru", False)
        is_universal = source.get("universal", False)
        for c in batch:
            all_configs.append(c)
            key = c.split("#")[0].rstrip("?& ")
            if is_ru:
                ru_keys.add(key)
            if is_universal:
                universal_keys.add(key)

    # Дедупликация
    seen:   set[str]  = set()
    unique: list[str] = []
    for c in all_configs:
        key = c.split("#")[0].rstrip("?& ")
        if key not in seen:
            seen.add(key); unique.append(c)

    log.info("📦 Уникальных: %d  RU: %d  Universal BL+WT: %d",
             len(unique), len(ru_keys), len(universal_keys))
    return unique, ru_keys, universal_keys
