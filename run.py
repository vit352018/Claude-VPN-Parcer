#!/usr/bin/env python3
"""
Скрипт локального запуска и управления коллектором.
Использование:
  python run.py            — полный пайплайн
  python run.py --test     — только тест уже собранных конфигов
  python run.py --sources  — только скачать источники (без теста)
  python run.py --stats    — показать текущую статистику
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run")


def show_stats():
    stats_file = Path("output/stats.json")
    if not stats_file.exists():
        print("❌ stats.json не найден. Сначала запусти полный пайплайн.")
        return
    stats = json.loads(stats_file.read_text())
    print(f"""
╔══════════════════════════════════════╗
║       VLESS Collector — Stats        ║
╠══════════════════════════════════════╣
║ Обновлено:    {stats.get('updated_msk','')[:16]:<22} ║
║ Всего рабочих: {stats.get('total_working',0):<21} ║
║ TLS подтверждено: {stats.get('tls_confirmed',0):<18} ║
╠══════════════════════════════════════╣
║ Протоколы:                           ║""")
    for proto, cnt in stats.get("by_protocol", {}).items():
        print(f"║   {proto:<10} {cnt:<26} ║")
    lat = stats.get("latency", {})
    print(f"""╠══════════════════════════════════════╣
║ Задержка (мс):                       ║
║   min={lat.get('min_ms',0):<6} avg={lat.get('avg_ms',0):<6} p90={lat.get('p90_ms',0):<6}   ║
╠══════════════════════════════════════╣
║ Топ стран:                           ║""")
    for country, cnt in list(stats.get("top_countries", {}).items())[:5]:
        print(f"║   {country:<18} {cnt:<17} ║")
    print("╚══════════════════════════════════════╝")


async def run_sources_only():
    from collector import collect_all
    from tg_scraper import collect_from_telegram
    configs = await collect_all()
    tg      = await collect_from_telegram()
    all_c   = list(set(configs + tg))
    log.info("Всего уникальных: %d", len(all_c))
    # Сохраняем сырой список для последующего теста
    Path("output").mkdir(exist_ok=True)
    Path("output/_raw_configs.txt").write_text("\n".join(all_c), encoding="utf-8")
    log.info("Сохранено в output/_raw_configs.txt")


async def run_test_only():
    raw_file = Path("output/_raw_configs.txt")
    if not raw_file.exists():
        log.error("Нет output/_raw_configs.txt. Сначала запусти --sources")
        return
    configs = [l for l in raw_file.read_text().splitlines() if l.strip()]
    log.info("Загружено %d конфигов для теста", len(configs))

    # Импортируем остальные модули
    from main import get_host_port_sni
    from tester import batch_test
    from geoip import geolocate_hosts
    from writer import write_all_outputs
    from html_gen import generate_html
    from urllib.parse import urlparse

    MAX_LATENCY = 4000
    targets = []
    cfg_by_target: dict = {}
    for cfg in configs:
        t = get_host_port_sni(cfg)
        if t:
            targets.append(t)
            cfg_by_target.setdefault((t[0], t[1]), []).append(cfg)

    test_results = await batch_test(targets, max_workers=80)

    working = []
    tls_map = {}
    seen = set()
    for r in test_results:
        if not r["alive"] or (r["tcp_ms"] or 9999) > MAX_LATENCY:
            continue
        host, port = r["host"], r["port"]
        tls_map[host] = r.get("tls_ok", False)
        for cfg in cfg_by_target.get((host, port), []):
            key = cfg.split("#")[0].rstrip("?& ")
            if key not in seen:
                seen.add(key)
                working.append((cfg, r["tcp_ms"]))

    working.sort(key=lambda x: x[1])
    log.info("✅ Рабочих: %d", len(working))

    hosts = list({urlparse(c).hostname or "" for c, _ in working if urlparse(c).hostname})
    geo_map = await geolocate_hosts(hosts)
    stats = write_all_outputs(working, geo_map=geo_map, tls_map=tls_map)
    generate_html(stats)
    log.info("Готово.")


async def run_full():
    from main import main
    await main()


def main_cli():
    parser = argparse.ArgumentParser(description="VLESS Collector")
    parser.add_argument("--sources", action="store_true", help="Только скачать источники")
    parser.add_argument("--test",    action="store_true", help="Только тест (нужен _raw_configs.txt)")
    parser.add_argument("--stats",   action="store_true", help="Показать статистику")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.sources:
        asyncio.run(run_sources_only())
    elif args.test:
        asyncio.run(run_test_only())
    else:
        asyncio.run(run_full())


if __name__ == "__main__":
    main_cli()
