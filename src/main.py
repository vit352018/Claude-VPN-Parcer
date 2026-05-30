"""
Главный пайплайн:
  1. Сбор конфигов из GitHub-источников
  2. Сбор из Telegram-каналов
  3. Дедупликация
  4. Умное тестирование (TCP + TLS)
  5. Геолокация рабочих хостов
  6. Запись раздельных файлов по протоколам
  7. Генерация HTML-страницы статистики
  8. Загрузка на Яндекс Диск (если включено в config.py)
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# Корень проекта — на уровень выше папки src/
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from config import YANDEX_ENABLED, YANDEX_TOKEN, YANDEX_FOLDER, MAX_LATENCY
from collector import collect_all
from tg_scraper import collect_from_telegram
from tester import batch_test
from geoip import geolocate_hosts
from writer import write_all_outputs, OUTPUT_DIR
from html_gen import generate_html
from yadisk import upload_to_yandex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def get_host_port_sni(cfg: str):
    """Достаёт адрес сервера, порт и SNI из строки конфига."""
    try:
        if cfg.lower().startswith("vmess://"):
            import base64, json as _json
            b64 = cfg[8:].split("#")[0].split("?")[0]
            padded = b64 + "=" * (-len(b64) % 4)
            data = _json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
            host = str(data.get("add", "")).strip()
            port = int(data.get("port", 0))
            sni  = data.get("sni") or data.get("host") or None
            return (host, port, sni) if host and port else None
        else:
            from urllib.parse import parse_qs
            parsed = urlparse(cfg)
            host   = parsed.hostname or ""
            port   = parsed.port or 0
            qs     = parse_qs(parsed.query)
            sni    = (qs.get("sni") or qs.get("peer") or [None])[0]
            return (host, port, sni) if host and port else None
    except Exception:
        return None


async def main():
    t_start = time.monotonic()
    log.info("=" * 62)
    log.info("🚀 VLESS Collector — старт")
    log.info("=" * 62)

    # ── 1. Сбор конфигов ──────────────────────────────────────────────────────
    github_configs = await collect_all()
    tg_configs     = await collect_from_telegram()

    all_raw = github_configs + tg_configs
    log.info("📦 Всего из источников: %d", len(all_raw))

    # ── 2. Дедупликация ───────────────────────────────────────────────────────
    seen:   set[str]       = set()
    unique: list[str]      = []
    for c in all_raw:
        key = c.split("#")[0].rstrip("?& ")
        if key not in seen:
            seen.add(key)
            unique.append(c)
    log.info("🔗 После дедупликации: %d", len(unique))

    if not unique:
        log.error("❌ Нет конфигов для тестирования")
        sys.exit(1)

    # ── 3. Извлекаем (host, port, sni) ────────────────────────────────────────
    targets: list[tuple] = []
    cfg_by_target: dict  = {}
    for cfg in unique:
        t = get_host_port_sni(cfg)
        if t:
            targets.append(t)
            cfg_by_target.setdefault((t[0], t[1]), []).append(cfg)

    log.info("🎯 Хостов для проверки: %d", len(targets))

    # ── 4. Тестирование (TCP + TLS) ───────────────────────────────────────────
    test_results = await batch_test(targets, max_workers=80)

    working:   list[tuple] = []
    tls_map:   dict        = {}
    seen_final: set[str]   = set()

    for r in sorted(test_results, key=lambda x: x.get("tcp_ms") or 9999):
        if not r["alive"]:
            continue
        latency = r["tcp_ms"]
        if latency is None or latency > MAX_LATENCY:
            continue
        host = r["host"]
        port = r["port"]
        tls_map[host] = r.get("tls_ok", False)
        for cfg in cfg_by_target.get((host, port), []):
            key = cfg.split("#")[0].rstrip("?& ")
            if key not in seen_final:
                seen_final.add(key)
                working.append((cfg, latency))

    log.info("✅ Рабочих серверов: %d", len(working))

    if not working:
        log.warning("⚠️  Ни один сервер не прошёл проверку")
        sys.exit(1)

    # ── 5. Геолокация ─────────────────────────────────────────────────────────
    hosts = list({
        urlparse(c).hostname or ""
        for c, _ in working
        if urlparse(c).hostname
    })
    geo_map = await geolocate_hosts(hosts)

    # ── 6. Запись файлов ──────────────────────────────────────────────────────
    stats = write_all_outputs(working, geo_map=geo_map, tls_map=tls_map)

    # ── 7. HTML-страница статистики ───────────────────────────────────────────
    generate_html(stats)

    # ── 8. Яндекс Диск (если включён в config.py) ────────────────────────────
    if YANDEX_ENABLED:
        await upload_to_yandex(OUTPUT_DIR, YANDEX_TOKEN, YANDEX_FOLDER)
    else:
        log.info("☁️  Яндекс Диск отключён (YANDEX_ENABLED = False в config.py)")

    # ── Итог ──────────────────────────────────────────────────────────────────
    elapsed = int(time.monotonic() - t_start)
    log.info("=" * 62)
    log.info("🏁 Готово за %d сек.  Рабочих: %d  TLS: %d",
             elapsed, stats["total_working"], stats["tls_confirmed"])
    log.info("=" * 62)


if __name__ == "__main__":
    asyncio.run(main())
