"""
VLESS/VMess/Trojan Config Collector
Собирает конфиги из публичных источников, тестирует TCP-доступность,
сохраняет рабочие в выходной файл.
"""

import asyncio
import base64
import json
import logging
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse
from zoneinfo import ZoneInfo

import aiohttp
import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).parent.parent))
import config as _cfg

# ── Настройки ──────────────────────────────────────────────────────────────────

SOURCES: list[dict] = [

    # ── Специализированные источники для РФ (обход ТСПУ/РКН) ─────────────────
    # Эти источники помечены ru=True — из них берутся серверы для RU_BYPASS.txt

    {
        "name": "igareck BLACK_VLESS_RUS",
        "url": "https://raw.githack.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
        "type": "raw",
        "ru": True,   # ← специально для РФ
    },
    {
        "name": "igareck WHITE_VLESS_RUS",
        "url": "https://raw.githack.com/igareck/vpn-configs-for-russia/main/WHITE_VLESS_RUS.txt",
        "type": "raw",
        "ru": True,
    },
    {
        "name": "igareck VLESS_REALITY_RUS",
        "url": "https://raw.githack.com/igareck/vpn-configs-for-russia/main/VLESS_REALITY_RUS.txt",
        "type": "raw",
        "ru": True,
    },
    {
        "name": "soroushmirzaei reality configs",
        "url": "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/splitted/reality",
        "type": "raw",
        "ru": True,
    },
    {
        "name": "XTLS/Xray reality subscription",
        "url": "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/reality",
        "type": "raw",
        "ru": True,
    },
    {
        "name": "MatinGhanbari/FreeVlessReality",
        "url": "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/xray/sub10.txt",
        "type": "raw",
        "ru": True,
    },
    {
        "name": "Everyday-VPN russia",
        "url": "https://raw.githubusercontent.com/yebekhe/TVC/main/subscriptions/xray/reality",
        "type": "raw",
        "ru": True,
    },

    # ── Общие источники (все протоколы) ───────────────────────────────────────
    {
        "name": "mahdibland/V2RayAggregator",
        "url": "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/Eternity",
        "type": "raw",
    },
    {
        "name": "barry-far/V2Ray-Configs",
        "url": "https://raw.githubusercontent.com/barry-far/V2Ray-Configs/main/Sub1.txt",
        "type": "raw",
    },
    {
        "name": "soroushmirzaei/telegram-configs-collector",
        "url": "https://raw.githubusercontent.com/soroushmirzaei/telegram-configs-collector/main/channels/protocols/vless",
        "type": "raw",
    },
    {
        "name": "freefq/free",
        "url": "https://raw.githubusercontent.com/freefq/free/master/v2",
        "type": "base64",
    },
    {
        "name": "peasoft/NoMoreVPN",
        "url": "https://raw.githubusercontent.com/peasoft/NoMoreVPN/master/subscriptions/raw.txt",
        "type": "raw",
    },
    {
        "name": "mfuu/v2ray",
        "url": "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
        "type": "base64",
    },
    {
        "name": "vpei/Free-Node-Merge",
        "url": "https://raw.githubusercontent.com/vpei/Free-Node-Merge/main/o/node.txt",
        "type": "base64",
    },
    {
        "name": "Leon406/SubCrawler vless",
        "url": "https://raw.githubusercontent.com/Leon406/SubCrawler/main/sub/share/vless",
        "type": "raw",
    },
]

# Протоколы, которые собираем
PROTOCOLS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://", "tuic://")

# Множество URL источников помеченных ru=True — для фильтрации RU_BYPASS
RU_SOURCE_URLS: set[str] = {s["url"] for s in SOURCES if s.get("ru")}


def is_russia_bypass(config_str: str) -> bool:
    """
    Определяет, подходит ли конфиг для обхода российских блокировок (ТСПУ/РКН).

    Простыми словами:
      ТСПУ умеет распознавать обычный VPN.
      Единственный надёжный способ обойти его — VLESS + XTLS Reality.
      Сервер притворяется обычным HTTPS-сайтом (например, github.com).
      DPI видит обычный TLS и пропускает трафик.

      Признаки Reality-конфига:
        security=reality        — главный признак
        flow=xtls-rprx-vision   — XTLS Vision (лучший вариант для РФ)
        pbk=...                 — публичный ключ (есть только у Reality)
    """
    if not config_str.lower().startswith("vless://"):
        return False
    low = config_str.lower()
    if "security=reality" in low:   return True
    if "flow=xtls-rprx-vision" in low: return True
    if "&pbk=" in low or "?pbk=" in low: return True
    return False


# Параметры тестирования
TCP_TIMEOUT   = 5.0    # секунд на одну проверку
MAX_WORKERS   = 80     # параллельных TCP-тестов
MAX_LATENCY   = 4000   # мс — верхняя граница «рабочего» сервера
FETCH_TIMEOUT = 20     # секунд на скачивание источника

OUTPUT_DIR  = Path(__file__).parent.parent / "output"
OUTPUT_FILE = OUTPUT_DIR / "VLESS_WORKING.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("collector")


# ── Парсинг конфигов ────────────────────────────────────────────────────────────

def extract_configs(text: str) -> list[str]:
    """Вытащить все строки, начинающиеся с известных протоколов."""
    configs = []
    for line in text.splitlines():
        line = line.strip()
        if any(line.startswith(p) for p in PROTOCOLS):
            configs.append(line)
    return configs


def decode_source(raw: str, fmt: str) -> str:
    """Декодировать base64-подписку или вернуть как есть."""
    if fmt != "base64":
        return raw
    try:
        # Добавляем padding если нужно
        padded = raw.strip() + "=" * (-len(raw.strip()) % 4)
        return base64.b64decode(padded).decode("utf-8", errors="ignore")
    except Exception:
        return raw


def get_host_port(config: str) -> Optional[tuple[str, int]]:
    """Извлечь (host, port) из конфига для TCP-проверки."""
    try:
        if config.startswith("vmess://"):
            # vmess — base64 JSON
            b64 = config[8:].split("#")[0].split("?")[0]
            padded = b64 + "=" * (-len(b64) % 4)
            data = json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
            host = str(data.get("add", "")).strip()
            port = int(data.get("port", 0))
            if host and port:
                return host, port

        elif any(config.startswith(p) for p in ("vless://", "trojan://", "ss://",
                                                  "hysteria2://", "hy2://", "tuic://")):
            parsed = urlparse(config)
            host = parsed.hostname or ""
            port = parsed.port or 0
            if host and port:
                return host, port

    except Exception:
        pass
    return None


# ── TCP-тест ───────────────────────────────────────────────────────────────────

async def tcp_check(host: str, port: int, timeout: float = TCP_TIMEOUT) -> Optional[int]:
    """
    Проверяет TCP-доступность сервера.
    Возвращает задержку в мс или None если недоступен.
    """
    t0 = time.monotonic()
    try:
        # Резолвим DNS заранее (чтобы не платить за него в latency)
        loop = asyncio.get_event_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM),
            timeout=timeout,
        )
        if not infos:
            return None
        af, socktype, proto, _, addr = infos[0]

        # Пробуем подключиться
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(addr[0], addr[1]),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        latency_ms = int((time.monotonic() - t0) * 1000)
        return latency_ms if latency_ms <= MAX_LATENCY else None
    except Exception:
        return None


# ── Сбор из источников ─────────────────────────────────────────────────────────

async def fetch_source_with_retry(
    session: aiohttp.ClientSession,
    source: dict,
    retries: int = 2,
) -> list[str]:
    """
    Скачивает один источник, при ошибке повторяет до 2 раз.

    Простыми словами: если сайт не ответил — подождём 3 секунды
    и попробуем ещё раз. Иногда серверы просто временно перегружены.
    """
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
                    log.warning("  %-45s  404 — источник не найден", name)
                    return []  # повтор не поможет
                if resp.status != 200:
                    log.warning("  %-45s  HTTP %s (попытка %d)", name, resp.status, attempt + 1)
                    if attempt < retries:
                        await asyncio.sleep(3)
                        continue
                    return []
                raw = await resp.text(errors="ignore")

            decoded = decode_source(raw, fmt)
            configs = extract_configs(decoded)
            log.info("  %-45s  %d конфигов", name, len(configs))
            return configs

        except asyncio.TimeoutError:
            log.warning("  %-45s  таймаут (попытка %d)", name, attempt + 1)
        except Exception as e:
            log.warning("  %-45s  ошибка: %s (попытка %d)", name, e, attempt + 1)

        if attempt < retries:
            await asyncio.sleep(3)

    return []


async def collect_all() -> tuple[list[str], set[str]]:
    """
    Скачивает конфиги из всех источников параллельно.
    Автоматически подхватывает источники найденные source_discovery.

    Возвращает:
      (unique_configs, ru_candidate_keys)
      ru_candidate_keys — ключи конфигов из RU-источников (для RU_BYPASS.txt)
    """
    # Основные встроенные источники
    all_sources = list(SOURCES)

    # Добавляем автоматически найденные (если есть)
    try:
        from source_discovery import load_discovered
        discovered = load_discovered()
        if discovered:
            log.info("  📡 Автообнаружено источников: %d", len(discovered))
            existing_urls = {s["url"] for s in all_sources}
            for s in discovered:
                if s["url"] not in existing_urls:
                    all_sources.append(s)
    except Exception as e:
        log.debug("source_discovery не доступен: %s", e)

    log.info("📥 Скачиваю %d источников…", len(all_sources))
    connector = aiohttp.TCPConnector(ssl=False, limit=20)
    headers   = {"User-Agent": "Mozilla/5.0 (compatible; VPNCollector/1.0)"}

    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        tasks   = [fetch_source_with_retry(session, src) for src in all_sources]
        results = await asyncio.gather(*tasks)

    all_configs: list[str] = []
    # Запоминаем ключи конфигов из RU-источников
    ru_keys: set[str] = set()

    for source, batch in zip(all_sources, results):
        is_ru_source = source.get("ru", False)
        for c in batch:
            all_configs.append(c)
            if is_ru_source:
                ru_keys.add(c.split("#")[0].rstrip("?& "))

    # Дедупликация
    seen:   set[str]  = set()
    unique: list[str] = []
    for c in all_configs:
        key = c.split("#")[0].rstrip("?& ")
        if key not in seen:
            seen.add(key)
            unique.append(c)

    log.info("📦 Уникальных: %d  из них RU-источники: %d", len(unique), len(ru_keys))
    return unique, ru_keys


# ── Тестирование ───────────────────────────────────────────────────────────────

async def test_all(configs: list[str]) -> list[tuple[str, int]]:
    """Тестирует все конфиги, возвращает список (config, latency_ms)."""
    log.info("🔍 Тестирую TCP-доступность (%d воркеров)…", MAX_WORKERS)

    sem = asyncio.Semaphore(MAX_WORKERS)
    results: list[tuple[str, int]] = []
    total = len(configs)
    done  = 0

    async def check_one(cfg: str):
        nonlocal done
        hp = get_host_port(cfg)
        if hp is None:
            async with sem:
                done += 1
            return
        host, port = hp
        async with sem:
            latency = await tcp_check(host, port)
            done += 1
            if done % 100 == 0 or done == total:
                log.info("  %d / %d  (рабочих: %d)", done, total, len(results))
        if latency is not None:
            results.append((cfg, latency))

    await asyncio.gather(*[check_one(c) for c in configs])

    # Сортируем по задержке
    results.sort(key=lambda x: x[1])
    log.info("✅ Рабочих серверов: %d / %d", len(results), total)
    return results


# ── Запись результата ──────────────────────────────────────────────────────────

def flag(country: str) -> str:
    """ISO2 → emoji-флаг."""
    country = country.strip().upper()
    if len(country) != 2:
        return "🌐"
    return chr(0x1F1E6 + ord(country[0]) - 65) + chr(0x1F1E6 + ord(country[1]) - 65)


def write_output(working: list[tuple[str, int]]):
    """Записать рабочие конфиги в файл."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now_msk = datetime.now(ZoneInfo("Europe/Moscow"))
    now_utc = datetime.now(timezone.utc)

    lines = [
        f"# profile-title: ✅ Working Servers | Auto-collected | {now_msk.strftime('%Y-%m-%d %H:%M')} MSK",
        f"# profile-update-interval: 1",
        f"# Date/Time: {now_utc.strftime('%Y-%m-%d')} / {now_msk.strftime('%H:%M')} (Moscow)",
        f"# Количество: {len(working)}",
        f"# Generated by: vless-collector (GitHub Actions)",
        f"# Source: https://github.com/{_cfg.GITHUB_USERNAME}/{_cfg.GITHUB_REPO}",
        "",
    ]

    for cfg, latency in working:
        # Дописываем задержку в метку если её нет или она устарела
        base, _, label = cfg.partition("#")
        label = unquote(label)
        # Убираем старую метку задержки
        label = re.sub(r"\s*\|\s*\d+ms", "", label)
        label = f"{label.strip()} | {latency}ms" if label.strip() else f"server | {latency}ms"
        lines.append(f"{base}#{label}")

    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("💾 Записано в %s", OUTPUT_FILE)


# ── Статистика ─────────────────────────────────────────────────────────────────

def print_stats(working: list[tuple[str, int]]):
    by_proto: dict[str, int] = {}
    for cfg, _ in working:
        for p in PROTOCOLS:
            if cfg.startswith(p):
                proto = p.rstrip(":/")
                by_proto[proto] = by_proto.get(proto, 0) + 1
                break

    log.info("📊 По протоколам:")
    for proto, count in sorted(by_proto.items(), key=lambda x: -x[1]):
        log.info("   %-12s %d", proto, count)

    latencies = [lat for _, lat in working]
    if latencies:
        log.info("⏱  Задержка: min=%dms  avg=%dms  max=%dms",
                 min(latencies),
                 sum(latencies) // len(latencies),
                 max(latencies))


# ── Точка входа ────────────────────────────────────────────────────────────────

async def main():
    log.info("=" * 60)
    log.info("🚀 VLESS Collector стартует")
    log.info("=" * 60)
    t_start = time.monotonic()

    configs = await collect_all()
    if not configs:
        log.error("❌ Источники не вернули ни одного конфига")
        return

    working = await test_all(configs)
    if not working:
        log.warning("⚠️  Ни один сервер не прошёл проверку")
        return

    write_output(working)
    print_stats(working)

    elapsed = int(time.monotonic() - t_start)
    log.info("⏰ Выполнено за %d сек.", elapsed)
    log.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
