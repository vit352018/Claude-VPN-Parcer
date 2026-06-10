"""
history.py — ведёт историю проверок серверов и рейтинг надёжности.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("history")

HISTORY_FILE       = Path(__file__).parent.parent / "output" / "server_history.json"
MAX_ENTRIES        = 24
MIN_SEEN           = 3


def _load() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def update(working_hosts: set[str], all_tested_hosts: set[str]):
    """Обновляет историю после очередного запуска."""
    history = _load()
    now_ts  = int(time.time())
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    for host in all_tested_hosts:
        if host not in history:
            history[host] = {"checks": [], "first_seen": now_str}
        history[host]["checks"].append({"ts": now_ts, "ok": host in working_hosts})
        history[host]["checks"] = history[host]["checks"][-MAX_ENTRIES:]
        history[host]["last_checked"] = now_str
    _save(history)
    log.info("📝 История: %d хостов", len(history))


def get_scores_bulk(hosts: list[str]) -> dict[str, float]:
    """Возвращает рейтинг надёжности (0..1) для списка хостов."""
    history = _load()
    result  = {}
    for host in hosts:
        if host not in history:
            result[host] = -1.0; continue
        checks = history[host].get("checks", [])
        if len(checks) < MIN_SEEN:
            result[host] = -1.0; continue
        result[host] = sum(1 for c in checks if c["ok"]) / len(checks)
    return result


def score_to_stars(score: float) -> str:
    if score < 0: return "🆕"
    s = round(score * 5)
    return "⭐" * s + "·" * (5 - s)


def get_stats() -> dict:
    history = _load()
    if not history:
        return {"total": 0, "rated": 0, "new": 0, "reliable": 0, "unstable": 0, "avg_score": 0}
    scores, reliable, unstable, new_servers = [], 0, 0, 0
    for h in history.values():
        checks = h.get("checks", [])
        if len(checks) < MIN_SEEN:
            new_servers += 1; continue
        s = sum(1 for c in checks if c["ok"]) / len(checks)
        scores.append(s)
        if s >= 0.7: reliable += 1
        elif s < 0.4: unstable += 1
    return {
        "total": len(history), "rated": len(scores), "new": new_servers,
        "reliable": reliable, "unstable": unstable,
        "avg_score": round(sum(scores) / len(scores), 2) if scores else 0,
    }


def prune_old(days: int = 7):
    history = _load()
    cutoff  = int(time.time()) - days * 86400
    before  = len(history)
    pruned  = {
        h: d for h, d in history.items()
        if d.get("checks") and d["checks"][-1]["ts"] >= cutoff
    }
    if len(pruned) < before:
        _save(pruned)
        log.info("🗑  История: удалено %d старых", before - len(pruned))
