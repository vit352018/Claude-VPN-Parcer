"""
run.py — запуск бота с компьютера (не через GitHub).

КОМАНДЫ:
  python run.py                — полный запуск (всё с нуля)
  python run.py --sources      — только скачать ключи из интернета
  python run.py --test         — только протестировать скачанные ключи
  python run.py --upload       — только загрузить файлы на Яндекс Диск
  python run.py --discover     — найти новые источники на GitHub
  python run.py --stats        — показать статистику в консоли
  python run.py --history      — показать историю надёжности серверов
  python run.py --bot          — запустить Telegram-бота (нужен TG_BOT_TOKEN)

НАСТРОЙКА:
  Скопируй .env.example → .env, заполни своими данными.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path


def _load_env():
    """Загружает переменные из .env файла."""
    env = Path(__file__).parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        print("✅ Загружен .env")


_load_env()

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run")


# ── Команды ────────────────────────────────────────────────────────────────────

def cmd_stats():
    """Показывает статистику последнего запуска."""
    f = Path("output/stats.json")
    if not f.exists():
        print("❌ output/stats.json не найден.\n   Сначала запусти: python run.py")
        return
    s   = json.loads(f.read_text(encoding="utf-8"))
    lat = s.get("latency", {})
    print(f"""
╔══════════════════════════════════════════╗
║      VLESS Collector — Статистика        ║
╠══════════════════════════════════════════╣
║  Обновлено:        {s.get("updated_msk","")[:16]:<23}║
║  Рабочих серверов: {s.get("total_working",0):<23}║
║  TLS подтверждено: {s.get("tls_confirmed",0):<23}║
╠══════════════════════════════════════════╣
║  По протоколам:                          ║""")
    for p, c in s.get("by_protocol", {}).items():
        if c:
            print(f"║    {p:<12} {c:<27}║")
    print(f"""╠══════════════════════════════════════════╣
║  Задержка (мс):                          ║
║    MIN={lat.get("min_ms",0):<6} AVG={lat.get("avg_ms",0):<6} P90={lat.get("p90_ms",0):<9}║
╠══════════════════════════════════════════╣
║  Топ-5 стран:                            ║""")
    for cc, c in list(s.get("top_countries", {}).items())[:5]:
        print(f"║    {cc:<18} {c:<22}║")
    print("╚══════════════════════════════════════════╝")

    # Показываем ссылки на файлы
    raw_base = s.get("raw_base", "")
    if raw_base:
        print(f"\n📥 Ссылки на подписки:")
        for fname in ["VLESS_WORKING.txt", "TOP50.txt", "TOP50_RELIABLE.txt"]:
            print(f"   {raw_base}/{fname}")


def cmd_history():
    """Показывает статистику истории серверов."""
    from history import get_stats, HISTORY_FILE
    if not HISTORY_FILE.exists():
        print("❌ История пуста. Запусти бота хотя бы 3 раза для накопления данных.")
        return
    s = get_stats()
    print(f"""
╔══════════════════════════════════════════╗
║     История надёжности серверов          ║
╠══════════════════════════════════════════╣
║  Серверов в базе:     {s.get("total",0):<20}║
║  Оценено (≥3 чек.):   {s.get("rated",0):<20}║
║  Новых (мало данных): {s.get("new",0):<20}║
║  Надёжных (≥70%):     {s.get("reliable",0):<20}║
║  Нестабильных (<40%): {s.get("unstable",0):<20}║
║  Средний uptime:      {str(round(s.get("avg_score",0)*100))+"%":<20}║
╚══════════════════════════════════════════╝""")


async def cmd_sources():
    """Скачивает ключи из всех источников и сохраняет в _raw_configs.txt."""
    from collector      import collect_all
    from tg_scraper     import collect_from_telegram
    github = await collect_all()
    tg     = await collect_from_telegram()
    seen, unique = set(), []
    for c in github + tg:
        k = c.split("#")[0].rstrip("?& ")
        if k not in seen:
            seen.add(k); unique.append(c)
    Path("output").mkdir(exist_ok=True)
    Path("output/_raw_configs.txt").write_text("\n".join(unique), encoding="utf-8")
    log.info("✅ Сохранено %d уникальных ключей → output/_raw_configs.txt", len(unique))


async def cmd_test():
    """Тестирует ключи из _raw_configs.txt и записывает результат."""
    raw = Path("output/_raw_configs.txt")
    if not raw.exists():
        log.error("Нет output/_raw_configs.txt — сначала: python run.py --sources")
        return
    configs = [l for l in raw.read_text(encoding="utf-8").splitlines() if l.strip()]
    log.info("Загружено %d конфигов", len(configs))

    import base64 as _b64
    import json as _j
    from urllib.parse import urlparse, parse_qs
    from tester           import batch_test
    from geoip            import geolocate_hosts
    from writer           import write_all_outputs
    from html_gen         import generate_html
    from history          import update as h_update, get_scores_bulk, prune_old
    import config as cfg

    targets, cfg_by_hp = [], {}
    for c in configs:
        try:
            if c.lower().startswith("vmess://"):
                b64 = c[8:].split("#")[0].split("?")[0]
                b64 += "=" * (-len(b64) % 4)
                d   = _j.loads(_b64.b64decode(b64).decode("utf-8", errors="ignore"))
                h, p, s = str(d.get("add", "")), int(d.get("port", 0)), d.get("sni")
            else:
                pr  = urlparse(c); qs = parse_qs(pr.query)
                h, p = pr.hostname or "", pr.port or 0
                s    = (qs.get("sni") or [None])[0]
            if h and p:
                targets.append((h, p, s))
                cfg_by_hp.setdefault((h, p), []).append(c)
        except Exception:
            pass

    results = await batch_test(targets, max_workers=cfg.MAX_WORKERS)

    working, tls_map, all_hosts, ok_hosts, seen_f = [], {}, set(), set(), set()
    for r in sorted(results, key=lambda x: x.get("tcp_ms") or 9999):
        h = r["host"]; all_hosts.add(h)
        if not r["alive"] or (r.get("tcp_ms") or 9999) > cfg.MAX_LATENCY:
            continue
        ok_hosts.add(h); tls_map[h] = r.get("tls_ok", False)
        for c in cfg_by_hp.get((h, r["port"]), []):
            k = c.split("#")[0].rstrip("?& ")
            if k not in seen_f:
                seen_f.add(k); working.append((c, r["tcp_ms"]))

    prune_old(cfg.HISTORY_PRUNE_DAYS)
    h_update(ok_hosts, all_hosts)
    score_map = get_scores_bulk(list(ok_hosts))
    hosts     = list({urlparse(c).hostname or "" for c, _ in working
                      if urlparse(c).hostname})
    geo_map   = await geolocate_hosts(hosts)
    stats     = write_all_outputs(working, geo_map=geo_map,
                                  tls_map=tls_map, score_map=score_map)
    generate_html(stats)
    log.info("✅ Готово. Рабочих: %d", stats["total_working"])


async def cmd_upload():
    """Загружает готовые файлы на Яндекс Диск."""
    import config as cfg
    from yandex_upload import upload_all
    if not cfg.YANDEX_LOGIN or not cfg.YANDEX_PASS:
        print("""
❌ Не заданы YANDEX_LOGIN и YANDEX_PASS.

Создай файл .env (скопируй .env.example → .env) и заполни:
  YANDEX_LOGIN=логин@yandex.ru
  YANDEX_PASS=пароль_приложения

Пароль приложения (НЕ основной пароль!):
  https://id.yandex.ru/security/app-passwords
""")
        return
    result = await upload_all(cfg.YANDEX_LOGIN, cfg.YANDEX_PASS)
    print(f"☁️  Загружено: {result['uploaded']}  Ошибок: {result['failed']}")


async def cmd_discover():
    """Ищет новые источники конфигов на GitHub."""
    from source_discovery import discover_new_sources
    log.info("🔍 Запускаю поиск новых источников…")
    new = await discover_new_sources(max_new=10)
    if new:
        log.info("✅ Найдено %d новых источников:", len(new))
        for s in new:
            log.info("   %s (%d конфигов)", s["name"], s.get("configs_found", 0))
    else:
        log.info("Новых источников не найдено (все уже в базе или не прошли проверку)")


def cmd_bot():
    """Запускает интерактивный Telegram-бот."""
    import config as cfg
    if not cfg.TG_BOT_TOKEN or not cfg.TG_CHAT_ID:
        print("""
❌ Не заданы TG_BOT_TOKEN и TG_CHAT_ID.

Добавь в .env:
  TG_BOT_TOKEN=токен_от_BotFather
  TG_CHAT_ID=твой_числовой_id

Как получить — читай инструкцию в README.md
""")
        return
    from tg_bot import main as bot_main
    bot_main()


async def cmd_full():
    """Полный пайплайн — всё с нуля."""
    from main import main
    await main()


# ── Точка входа ────────────────────────────────────────────────────────────────

def cli():
    ap = argparse.ArgumentParser(
        description="VLESS Collector — управление",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python run.py                 полный запуск (рекомендуется)
  python run.py --sources       скачать ключи из источников
  python run.py --test          протестировать скачанные ключи
  python run.py --upload        загрузить на Яндекс Диск
  python run.py --discover      найти новые источники на GitHub
  python run.py --stats         показать статистику
  python run.py --history       история надёжности серверов
  python run.py --bot           запустить Telegram-бота
        """
    )
    ap.add_argument("--sources",  action="store_true", help="Скачать ключи")
    ap.add_argument("--test",     action="store_true", help="Протестировать")
    ap.add_argument("--upload",   action="store_true", help="Загрузить на Яндекс Диск")
    ap.add_argument("--discover", action="store_true", help="Найти новые источники")
    ap.add_argument("--stats",    action="store_true", help="Статистика")
    ap.add_argument("--history",  action="store_true", help="История надёжности")
    ap.add_argument("--bot",      action="store_true", help="Запустить Telegram-бота")
    args = ap.parse_args()

    if   args.stats:    cmd_stats()
    elif args.history:  cmd_history()
    elif args.bot:      cmd_bot()
    elif args.sources:  asyncio.run(cmd_sources())
    elif args.test:     asyncio.run(cmd_test())
    elif args.upload:   asyncio.run(cmd_upload())
    elif args.discover: asyncio.run(cmd_discover())
    else:               asyncio.run(cmd_full())


if __name__ == "__main__":
    cli()
