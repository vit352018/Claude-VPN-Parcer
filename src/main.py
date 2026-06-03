"""
main.py — главный файл. Запускает весь пайплайн.

ЧТО ДЕЛАЕТ КАЖДЫЙ ЧАС:
  1. ПОИСК НОВЫХ ИСТОЧНИКОВ — ищет новые репозитории на GitHub
     (раз в сутки, чтобы список не устаревал)
  2. СБОР     — скачивает ключи с GitHub и Telegram (со второй попыткой)
  3. ЧИСТКА   — убирает дубли
  4. ТЕСТ     — проверяет каждый сервер (TCP + TLS)
  5. ИСТОРИЯ  — обновляет журнал надёжности серверов
  6. ГЕОЛОК.  — определяет страну каждого сервера
  7. ЗАПИСЬ   — раскладывает по файлам по протоколам, TOP50 и т.д.
  8. HTML     — генерирует страницу статистики
  9. Я.ДИСК  — копирует файлы на Яндекс Диск (если настроен)
 10. TELEGRAM — отправляет отчёт (если настроен)
"""

import asyncio
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import base64
import json as _json

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from collector        import collect_all
from tg_scraper       import collect_from_telegram
from tester           import batch_test
from geoip            import geolocate_hosts
from writer           import write_all_outputs
from html_gen         import generate_html
from yandex_upload    import upload_all
from tg_notify        import send_report, send_error
from history          import update as history_update, get_scores_bulk, prune_old
from source_discovery import discover_new_sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

# Файл-маркер последнего поиска новых источников
DISCOVERY_MARKER = Path(__file__).parent.parent / "output" / ".last_discovery"


def _should_run_discovery() -> bool:
    """
    Поиск новых источников — дорогая операция (много запросов на GitHub).
    Запускаем раз в сутки, не каждый час.
    """
    if not DISCOVERY_MARKER.exists():
        return True
    try:
        last = float(DISCOVERY_MARKER.read_text().strip())
        return (time.time() - last) > 86400   # 24 часа
    except Exception:
        return True


def _mark_discovery_done():
    DISCOVERY_MARKER.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_MARKER.write_text(str(time.time()))


def _parse_host_port_sni(config_str: str):
    """Вытаскивает (host, port, sni) из строки конфига."""
    try:
        if config_str.lower().startswith("vmess://"):
            b64 = config_str[8:].split("#")[0].split("?")[0]
            b64 += "=" * (-len(b64) % 4)
            data = _json.loads(base64.b64decode(b64).decode("utf-8", errors="ignore"))
            host = str(data.get("add", "")).strip()
            port = int(data.get("port", 0))
            sni  = data.get("sni") or data.get("host") or None
            return (host, port, sni) if host and port else None
        else:
            parsed = urlparse(config_str)
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
    log.info("🚀 VLESS Collector — старт  %s",
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
    log.info("=" * 62)

    try:
        # ── ШАГ 1: Поиск новых источников (раз в сутки) ──────────────────────
        if _should_run_discovery():
            log.info("🔍 ШАГ 1/10 — Ищу новые источники на GitHub (раз в сутки)…")
            try:
                new = await discover_new_sources(max_new=10)
                log.info("   Найдено новых источников: %d", len(new))
                _mark_discovery_done()
            except Exception as e:
                log.warning("   Поиск источников не удался: %s", e)
        else:
            log.info("🔍 ШАГ 1/10 — Поиск источников пропущен (следующий через <24ч)")

        # ── ШАГ 2: Сбор конфигов ─────────────────────────────────────────────
        log.info("📥 ШАГ 2/10 — Сбор конфигов из источников…")
        github_cfgs, ru_keys = await collect_all()    # ← теперь возвращает и ru_keys
        tg_cfgs              = await collect_from_telegram()
        all_raw              = github_cfgs + tg_cfgs
        log.info("   Найдено: %d ключей суммарно  (RU-источники: %d уник.)",
                 len(all_raw), len(ru_keys))

        # ── ШАГ 3: Дедупликация ──────────────────────────────────────────────
        log.info("🧹 ШАГ 3/10 — Убираем дубли…")
        seen, unique = set(), []
        for c in all_raw:
            k = c.split("#")[0].rstrip("?& ")
            if k not in seen:
                seen.add(k); unique.append(c)
        log.info("   Уникальных: %d  (убрано дублей: %d)",
                 len(unique), len(all_raw) - len(unique))

        if not unique:
            raise RuntimeError("Ни одного конфига из источников — все недоступны?")

        # ── ШАГ 4: Тест серверов (TCP + TLS) ─────────────────────────────────
        log.info("🔍 ШАГ 4/10 — Тестирование %d серверов…", len(unique))
        targets:    list    = []
        cfg_by_hp:  dict    = {}
        for c in unique:
            t = _parse_host_port_sni(c)
            if t:
                targets.append(t)
                cfg_by_hp.setdefault((t[0], t[1]), []).append(c)
        log.info("   Уникальных адресов: %d", len(targets))

        test_results = await batch_test(targets, max_workers=cfg.MAX_WORKERS)

        working:          list[tuple[str, int]] = []
        tls_map:          dict[str, bool]       = {}
        all_tested_hosts: set[str]              = set()
        working_hosts:    set[str]              = set()
        seen_f:           set[str]              = set()

        for r in sorted(test_results, key=lambda x: x.get("tcp_ms") or 9999):
            host = r["host"];  port = r["port"]
            all_tested_hosts.add(host)
            if not r["alive"] or (r.get("tcp_ms") or 9999) > cfg.MAX_LATENCY:
                continue
            working_hosts.add(host)
            tls_map[host] = r.get("tls_ok", False)
            for c in cfg_by_hp.get((host, port), []):
                k = c.split("#")[0].rstrip("?& ")
                if k not in seen_f:
                    seen_f.add(k); working.append((c, r["tcp_ms"]))

        log.info("   ✅ Рабочих: %d из %d проверенных", len(working), len(targets))

        if not working:
            raise RuntimeError("Ни один сервер не прошёл проверку")

        # ── ШАГ 5: История надёжности ─────────────────────────────────────────
        log.info("📝 ШАГ 5/10 — Обновляем историю надёжности…")
        prune_old(days=cfg.HISTORY_PRUNE_DAYS)
        history_update(working_hosts, all_tested_hosts)
        score_map      = get_scores_bulk(list(working_hosts))
        reliable_count = sum(1 for s in score_map.values() if s >= cfg.RELIABILITY_MIN)
        new_count      = sum(1 for s in score_map.values() if s < 0)
        log.info("   Надёжных (uptime≥%.0f%%): %d  Новых: %d",
                 cfg.RELIABILITY_MIN * 100, reliable_count, new_count)

        # ── ШАГ 6: Геолокация ────────────────────────────────────────────────
        log.info("🌍 ШАГ 6/10 — Определяем страны серверов…")
        hosts = list({
            urlparse(c).hostname or ""
            for c, _ in working
            if urlparse(c).hostname
        })
        geo_map = await geolocate_hosts(hosts)

        # ── ШАГ 7: Запись файлов ─────────────────────────────────────────────
        log.info("💾 ШАГ 7/10 — Записываем файлы по протоколам…")
        stats = write_all_outputs(
            working,
            geo_map=geo_map,
            tls_map=tls_map,
            score_map=score_map,
            ru_keys=ru_keys,
        )

        # ── ШАГ 8: HTML-страница ─────────────────────────────────────────────
        log.info("🌐 ШАГ 8/10 — Генерируем HTML-дашборд…")
        generate_html(stats)

        # ── ШАГ 9: Яндекс Диск ──────────────────────────────────────────────
        yd_result = None
        if cfg.YANDEX_LOGIN and cfg.YANDEX_PASS:
            log.info("☁️  ШАГ 9/10 — Загружаем на Яндекс Диск…")
            try:
                yd_result = await upload_all(cfg.YANDEX_LOGIN, cfg.YANDEX_PASS)
            except Exception as e:
                log.warning("   Яндекс Диск: ошибка — %s", e)
        else:
            log.info("☁️  ШАГ 9/10 — Яндекс Диск пропущен (нет логина/пароля)")

        # ── ШАГ 10: Telegram ────────────────────────────────────────────────
        elapsed = int(time.monotonic() - t_start)
        if cfg.TG_BOT_TOKEN and cfg.TG_CHAT_ID:
            log.info("📨 ШАГ 10/10 — Отправляем отчёт в Telegram…")
            try:
                await send_report(stats, yd_result=yd_result, elapsed_sec=elapsed)
            except Exception as e:
                log.warning("   Telegram: ошибка — %s", e)
        else:
            log.info("📨 ШАГ 10/10 — Telegram пропущен (нет токена)")

        # ── Итог ─────────────────────────────────────────────────────────────
        log.info("=" * 62)
        log.info(
            "🏁 ГОТОВО  %d сек | серверов: %d | TLS: %d | надёжных: %d | новых: %d",
            elapsed,
            stats["total_working"],
            stats["tls_confirmed"],
            reliable_count,
            new_count,
        )
        log.info("=" * 62)

    except Exception as e:
        err = traceback.format_exc()
        log.error("💥 Критическая ошибка:\n%s", err)
        if cfg.TG_BOT_TOKEN and cfg.TG_CHAT_ID:
            try:
                await send_error(err)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
