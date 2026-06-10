"""
main.py — главный пайплайн с жёстким таймаутом 12 минут.
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
from tg_notify     import send_report, send_error
from history       import update as history_update, get_scores_bulk, prune_old

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

# Жёсткий дедлайн — за сколько секунд должно уложиться всё
HARD_DEADLINE = 12 * 60   # 12 минут

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
    """Вытаскивает (host, port, sni) из строки конфига."""
    try:
        if cfg_str.lower().startswith("vmess://"):
            b64 = cfg_str[8:].split("#")[0].split("?")[0]
            b64 += "=" * (-len(b64) % 4)
            d    = _json.loads(base64.b64decode(b64).decode("utf-8", errors="ignore"))
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

    def elapsed():
        return time.monotonic() - t_start

    def time_left():
        return HARD_DEADLINE - elapsed()

    log.info("=" * 60)
    log.info("🚀 VLESS Collector  %s  (дедлайн %d мин)",
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             HARD_DEADLINE // 60)
    log.info("=" * 60)

    try:
        # ── 1. Поиск новых источников (раз в сутки, макс 60 сек) ─────────────
        if _should_discover() and time_left() > 120:
            log.info("🔍 ШАГ 1 — Поиск новых источников…")
            try:
                from source_discovery import discover_new_sources
                new = await asyncio.wait_for(
                    discover_new_sources(max_new=5),
                    timeout=60,
                )
                log.info("   Найдено новых: %d  (%.0f сек)", len(new), elapsed())
                _mark_discovery()
            except asyncio.TimeoutError:
                log.warning("   Поиск источников: таймаут 60 сек, пропускаем")
            except Exception as e:
                log.warning("   Поиск источников: %s", e)
        else:
            log.info("🔍 ШАГ 1 — Пропущен")

        # ── 2. Сбор конфигов (макс 90 сек) ───────────────────────────────────
        log.info("📥 ШАГ 2 — Сбор из источников…  (%.0f сек)", elapsed())
        try:
            github_cfgs, ru_keys = await asyncio.wait_for(
                collect_all(), timeout=90
            )
        except asyncio.TimeoutError:
            log.warning("   GitHub: таймаут, берём пустой список")
            github_cfgs, ru_keys = [], set()

        try:
            tg_cfgs = await asyncio.wait_for(
                collect_from_telegram(), timeout=60
            )
        except asyncio.TimeoutError:
            log.warning("   Telegram: таймаут, пропускаем")
            tg_cfgs = []

        all_raw = github_cfgs + tg_cfgs
        log.info("   Найдено: %d  RU: %d  (%.0f сек)",
                 len(all_raw), len(ru_keys), elapsed())

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

        # ── 3.5. Лимит конфигов — RU идут первыми ────────────────────────────
        limit = cfg.MAX_CONFIGS
        if len(unique) > limit:
            ru_first = [c for c in unique
                        if c.split("#")[0].rstrip("?& ") in ru_keys]
            rest     = [c for c in unique
                        if c.split("#")[0].rstrip("?& ") not in ru_keys]
            slots    = max(0, limit - len(ru_first))
            unique   = ru_first + rest[:slots]
            log.info("   Обрезано до %d (RU: %d + остальные: %d)",
                     len(unique), len(ru_first), slots)

        # ── 4. Тест серверов ──────────────────────────────────────────────────
        # Вычисляем сколько времени есть на тест
        test_budget = min(int(time_left()) - 180, 480)  # оставляем 3 мин на финал
        if test_budget < 30:
            log.warning("⏰ Мало времени на тест (%d сек) — пропускаем", test_budget)
            raise RuntimeError("Закончилось время до тестирования")

        log.info("🔍 ШАГ 4 — Тест %d конфигов (бюджет %d сек)…",
                 len(unique), test_budget)

        targets: list   = []
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
            log.warning("   Тест: таймаут %d сек — используем частичные результаты", test_budget)
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

        # ── 6. Геолокация (макс 60 сек) ───────────────────────────────────────
        log.info("🌍 ШАГ 6 — Геолокация…  (%.0f сек)", elapsed())
        hosts = list({urlparse(c).hostname or "" for c, _ in working
                      if urlparse(c).hostname})
        try:
            geo_map = await asyncio.wait_for(
                geolocate_hosts(hosts), timeout=60
            )
        except asyncio.TimeoutError:
            log.warning("   Геолокация: таймаут, пропускаем")
            geo_map = {}

        # ── 7-8. Запись файлов + HTML ──────────────────────────────────────────
        log.info("💾 ШАГ 7 — Запись файлов…  (%.0f сек)", elapsed())
        stats = write_all_outputs(
            working,
            geo_map=geo_map,
            tls_map=tls_map,
            score_map=score_map,
            ru_keys=ru_keys,
        )
        log.info("🌐 ШАГ 8 — HTML-дашборд…")
        generate_html(stats)

        # ── 9. Яндекс Диск ────────────────────────────────────────────────────
        yd_result = None
        if (cfg.YANDEX_TOKEN or (cfg.YANDEX_LOGIN and cfg.YANDEX_PASS)) and time_left() > 60:
            log.info("☁️  ШАГ 9 — Яндекс Диск…  (%.0f сек)", elapsed())
            try:
                yd_result = await asyncio.wait_for(
                    upload_all(
                        token=cfg.YANDEX_TOKEN,
                        login=cfg.YANDEX_LOGIN,
                        password=cfg.YANDEX_PASS,
                    ),
                    timeout=90,
                )
            except asyncio.TimeoutError:
                log.warning("   Яндекс Диск: таймаут")
            except Exception as e:
                log.warning("   Яндекс Диск: %s", e)
        else:
            log.info("☁️  ШАГ 9 — Яндекс Диск пропущен")

        # ── 10. Telegram ───────────────────────────────────────────────────────
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

        log.info("=" * 60)
        log.info("🏁 ГОТОВО за %d сек | серверов: %d | RU: %d",
                 elapsed_total,
                 stats["total_working"],
                 stats["by_protocol"].get("ru_bypass", 0))
        log.info("=" * 60)

    except Exception as e:
        log.error("💥 %s\n%s", e, traceback.format_exc())
        if cfg.TG_BOT_TOKEN and cfg.TG_CHAT_ID:
            try:
                await asyncio.wait_for(
                    send_error(traceback.format_exc()), timeout=10
                )
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
