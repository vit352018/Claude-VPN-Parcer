"""
main.py — главный пайплайн с жёстким таймаутом 12 минут.

Шаги:
  1.  Поиск новых источников (раз в сутки)
  2.  Сбор с GitHub + Telegram
  3.  Дедупликация + лимит MAX_CONFIGS
  4.  Тест TCP + TLS
  5.  История надёжности
  6.  Геолокация
  7.  Запись файлов (включая RU_BYPASS и UNIVERSAL_BL_WT)
  8.  HTML-дашборд
  9a. Yandex Object Storage (S3)
  9b. Яндекс Диск (запасной)
  10. Telegram-уведомление
"""
import asyncio
import base64
import json as _json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import config as cfg
from collector     import collect_all
from tg_scraper    import collect_from_telegram
from tester        import batch_test
from geoip         import geolocate_hosts
from writer        import write_all_outputs
from html_gen      import generate_html
from yandex_upload import upload_all
from yandex_s3     import upload_all as yandex_s3_upload
from tg_notify     import send_report, send_error
from history       import update as history_update, get_scores_bulk, prune_old

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

HARD_DEADLINE    = 12 * 60   # 12 минут максимум
DISCOVERY_MARKER = Path(__file__).parent.parent / "output" / ".last_discovery"


def _should_discover() -> bool:
    if not DISCOVERY_MARKER.exists():
        return True
    try:
        return (time.time() - float(DISCOVERY_MARKER.read_text().strip())) > 86400
    except Exception:
        return True


def _mark_discovery():
    DISCOVERY_MARKER.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_MARKER.write_text(str(time.time()))


def _parse(cfg_str: str):
    try:
        if cfg_str.lower().startswith("vmess://"):
            b64 = cfg_str[8:].split("#")[0].split("?")[0]
            b64 += "=" * (-len(b64) % 4)
            d   = _json.loads(base64.b64decode(b64).decode("utf-8", errors="ignore"))
            h, p, s = str(d.get("add", "")), int(d.get("port", 0)), d.get("sni")
            return (h, p, s) if h and p else None
        else:
            pr = urlparse(cfg_str)
            h  = pr.hostname or ""
            p  = pr.port or 0
            s  = (parse_qs(pr.query).get("sni") or [None])[0]
            return (h, p, s) if h and p else None
    except Exception:
        return None


async def main():
    t_start = time.monotonic()

    def elapsed():  return time.monotonic() - t_start
    def time_left(): return HARD_DEADLINE - elapsed()

    log.info("=" * 62)
    log.info("🚀 VLESS Collector  %s  (дедлайн %d мин)",
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             HARD_DEADLINE // 60)
    log.info("=" * 62)

    try:
        # ── 1. Поиск новых источников (раз в сутки) ───────────────────────────
        if _should_discover() and time_left() > 120:
            log.info("🔍 ШАГ 1 — Поиск новых источников…")
            try:
                from source_discovery import discover_new_sources
                new = await asyncio.wait_for(
                    discover_new_sources(max_new=5), timeout=60
                )
                log.info("   Найдено: %d  (%.0f сек)", len(new), elapsed())
                _mark_discovery()
            except asyncio.TimeoutError:
                log.warning("   Поиск: таймаут 60 сек")
            except Exception as e:
                log.warning("   Поиск: %s", e)
        else:
            log.info("🔍 ШАГ 1 — Пропущен")

        # ── 2. Сбор конфигов ──────────────────────────────────────────────────
        log.info("📥 ШАГ 2 — Сбор конфигов…  (%.0f сек)", elapsed())
        try:
            github_cfgs, ru_keys, universal_keys = await asyncio.wait_for(
                collect_all(), timeout=90
            )
        except asyncio.TimeoutError:
            log.warning("   GitHub: таймаут")
            github_cfgs, ru_keys, universal_keys = [], set(), set()

        try:
            tg_cfgs = await asyncio.wait_for(
                collect_from_telegram(), timeout=60
            )
        except asyncio.TimeoutError:
            log.warning("   Telegram: таймаут")
            tg_cfgs = []

        all_raw = github_cfgs + tg_cfgs
        log.info("   Найдено: %d  RU: %d  Universal: %d  (%.0f сек)",
                 len(all_raw), len(ru_keys), len(universal_keys), elapsed())

        # ── 3. Дедупликация ───────────────────────────────────────────────────
        seen, unique = set(), []
        for c in all_raw:
            k = c.split("#")[0].rstrip("?& ")
            if k not in seen:
                seen.add(k); unique.append(c)
        log.info("🧹 ШАГ 3 — Уникальных: %d  (дублей: %d)",
                 len(unique), len(all_raw) - len(unique))

        if not unique:
            raise RuntimeError("Нет конфигов из источников")

        # Лимит — RU и Universal идут первыми
        limit = cfg.MAX_CONFIGS
        if len(unique) > limit:
            priority_keys = ru_keys | universal_keys
            prio  = [c for c in unique if c.split("#")[0].rstrip("?& ") in priority_keys]
            rest  = [c for c in unique if c.split("#")[0].rstrip("?& ") not in priority_keys]
            slots = max(0, limit - len(prio))
            unique = prio + rest[:slots]
            log.info("   Лимит %d: приоритет %d + остальные %d",
                     limit, len(prio), slots)

        # ── 4. Тест серверов ──────────────────────────────────────────────────
        test_budget = min(int(time_left()) - 180, 480)
        if test_budget < 30:
            raise RuntimeError("Закончилось время до тестирования")

        log.info("🔍 ШАГ 4 — Тест %d конфигов (бюджет %d сек)…",
                 len(unique), test_budget)

        targets:   list = []
        cfg_by_hp: dict = {}
        for c in unique:
            t = _parse(c)
            if t:
                targets.append(t)
                cfg_by_hp.setdefault((t[0], t[1]), []).append(c)

        try:
            test_results = await asyncio.wait_for(
                batch_test(targets, max_workers=cfg.MAX_WORKERS),
                timeout=test_budget,
            )
        except asyncio.TimeoutError:
            log.warning("   Тест: таймаут %d сек — частичные результаты", test_budget)
            test_results = []

        working: list = []
        tls_map: dict = {}
        all_h:   set  = set()
        ok_h:    set  = set()
        seen_f:  set  = set()

        for r in sorted(test_results, key=lambda x: x.get("tcp_ms") or 9999):
            h = r["host"]; all_h.add(h)
            if not r["alive"] or (r.get("tcp_ms") or 9999) > cfg.MAX_LATENCY:
                continue
            ok_h.add(h); tls_map[h] = r.get("tls_ok", False)
            for c in cfg_by_hp.get((h, r["port"]), []):
                k = c.split("#")[0].rstrip("?& ")
                if k not in seen_f:
                    seen_f.add(k); working.append((c, r["tcp_ms"]))

        log.info("   ✅ Рабочих: %d из %d  (%.0f сек)",
                 len(working), len(targets), elapsed())

        if not working:
            raise RuntimeError("Ни один сервер не прошёл проверку")

        # ── 5. История ────────────────────────────────────────────────────────
        log.info("📝 ШАГ 5 — История надёжности…")
        prune_old(days=cfg.HISTORY_PRUNE_DAYS)
        history_update(ok_h, all_h)
        score_map = get_scores_bulk(list(ok_h))

        # ── 6. Геолокация ─────────────────────────────────────────────────────
        log.info("🌍 ШАГ 6 — Геолокация…  (%.0f сек)", elapsed())
        hosts = list({urlparse(c).hostname or "" for c, _ in working
                      if urlparse(c).hostname})
        try:
            geo_map = await asyncio.wait_for(geolocate_hosts(hosts), timeout=60)
        except asyncio.TimeoutError:
            log.warning("   Геолокация: таймаут")
            geo_map = {}

        # ── 7. Запись файлов ──────────────────────────────────────────────────
        log.info("💾 ШАГ 7 — Запись файлов…  (%.0f сек)", elapsed())
        stats = write_all_outputs(
            working,
            geo_map=geo_map,
            tls_map=tls_map,
            score_map=score_map,
            ru_keys=ru_keys,
            universal_keys=universal_keys,
        )

        # ── 8. HTML ───────────────────────────────────────────────────────────
        log.info("🌐 ШАГ 8 — HTML-дашборд…")
        generate_html(stats)

        # ── 9a. Yandex Object Storage (S3) ────────────────────────────────────
        yd_result = None
        if cfg.YANDEX_S3_BUCKET and cfg.YANDEX_S3_ACCESS_KEY and time_left() > 60:
            log.info("☁️  ШАГ 9a — Yandex Object Storage…  (%.0f сек)", elapsed())
            try:
                yd_result = await asyncio.wait_for(
                    yandex_s3_upload(
                        bucket=cfg.YANDEX_S3_BUCKET,
                        access_key=cfg.YANDEX_S3_ACCESS_KEY,
                        secret_key=cfg.YANDEX_S3_SECRET_KEY,
                    ),
                    timeout=90,
                )
            except asyncio.TimeoutError:
                log.warning("   Yandex S3: таймаут")
            except Exception as e:
                log.warning("   Yandex S3: %s", e)
        else:
            log.info("☁️  ШАГ 9a — Yandex S3 пропущен")

        # ── 9b. Яндекс Диск (запасной) ────────────────────────────────────────
        if (cfg.YANDEX_TOKEN or (cfg.YANDEX_LOGIN and cfg.YANDEX_PASS)) and time_left() > 60:
            log.info("☁️  ШАГ 9b — Яндекс Диск…  (%.0f сек)", elapsed())
            try:
                disk_result = await asyncio.wait_for(
                    upload_all(
                        token=cfg.YANDEX_TOKEN,
                        login=cfg.YANDEX_LOGIN,
                        password=cfg.YANDEX_PASS,
                    ),
                    timeout=90,
                )
                if yd_result is None:
                    yd_result = disk_result
            except asyncio.TimeoutError:
                log.warning("   Яндекс Диск: таймаут")
            except Exception as e:
                log.warning("   Яндекс Диск: %s", e)
        else:
            log.info("☁️  ШАГ 9b — Яндекс Диск пропущен")

        # ── 10. Telegram ──────────────────────────────────────────────────────
        elapsed_total = int(elapsed())
        if cfg.TG_BOT_TOKEN and cfg.TG_CHAT_ID:
            log.info("📨 ШАГ 10 — Telegram…")
            try:
                await asyncio.wait_for(
                    send_report(stats, yd_result=yd_result, elapsed_sec=elapsed_total),
                    timeout=15,
                )
            except Exception as e:
                log.warning("   Telegram: %s", e)

        log.info("=" * 62)
        log.info("🏁 ГОТОВО за %d сек | всего: %d | RU: %d | Universal: %d",
                 elapsed_total,
                 stats["total_working"],
                 stats["by_protocol"].get("ru_bypass", 0),
                 stats["by_protocol"].get("universal", 0))
        log.info("=" * 62)

    except Exception as e:
        log.error("💥 %s\n%s", e, traceback.format_exc())
        if cfg.TG_BOT_TOKEN and cfg.TG_CHAT_ID:
            try:
                await asyncio.wait_for(send_error(traceback.format_exc()), timeout=10)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
