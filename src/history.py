"""
history.py — ведёт историю проверок каждого сервера.

Простыми словами:
  Представь журнал наблюдений за серверами.
  Каждый час бот записывает: "сервер X ответил за 150мс",
  или "сервер Y не ответил".

  Со временем накапливается история:
  - Сервер видели 10 раз, работал 9 → надёжность 90% ⭐⭐⭐⭐⭐
  - Сервер видели 5 раз, работал 2  → надёжность 40% ⭐⭐

  Это позволяет выкидывать нестабильные серверы,
  которые сегодня работают, завтра нет.

  История хранится в файле output/server_history.json
  и накапливается между запусками.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("history")

HISTORY_FILE  = Path(__file__).parent.parent / "output" / "server_history.json"
MAX_ENTRIES   = 24   # сколько последних запусков помним для каждого сервера
MIN_SEEN      = 3    # нужно минимум 3 наблюдения для оценки надёжности


def _load() -> dict:
    """Загружает историю из файла. Если файла нет — возвращает пустой словарь."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict):
    """Сохраняет историю в файл."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def update(working_hosts: set[str], all_tested_hosts: set[str]):
    """
    Обновляет историю после очередного запуска.

    working_hosts      — хосты которые ПРОШЛИ проверку (живые)
    all_tested_hosts   — все хосты которых проверяли (живые + мёртвые)
    """
    history = _load()
    now_ts  = int(time.time())
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")

    for host in all_tested_hosts:
        if host not in history:
            history[host] = {"checks": [], "first_seen": now_str}

        alive = host in working_hosts
        # Дописываем результат этой проверки
        history[host]["checks"].append({"ts": now_ts, "ok": alive})
        # Оставляем только последние MAX_ENTRIES записей
        history[host]["checks"] = history[host]["checks"][-MAX_ENTRIES:]
        history[host]["last_checked"] = now_str

    _save(history)
    log.info("📝 История обновлена: %d хостов всего", len(history))


def get_score(host: str) -> float:
    """
    Возвращает «оценку надёжности» хоста от 0.0 до 1.0.

    Простыми словами: какой процент проверок этот сервер прошёл.
    0.9 = работал в 90% случаев (очень надёжный)
    0.3 = работал в 30% случаев (ненадёжный)
    -1  = данных ещё нет (новый сервер)
    """
    history = _load()
    if host not in history:
        return -1.0
    checks = history[host].get("checks", [])
    if len(checks) < MIN_SEEN:
        return -1.0  # мало данных — не оцениваем
    ok_count = sum(1 for c in checks if c["ok"])
    return ok_count / len(checks)


def get_scores_bulk(hosts: list[str]) -> dict[str, float]:
    """Возвращает оценки для списка хостов за один вызов (быстрее чем по одному)."""
    history = _load()
    result  = {}
    for host in hosts:
        if host not in history:
            result[host] = -1.0
            continue
        checks = history[host].get("checks", [])
        if len(checks) < MIN_SEEN:
            result[host] = -1.0
            continue
        ok_count = sum(1 for c in checks if c["ok"])
        result[host] = ok_count / len(checks)
    return result


def score_to_stars(score: float) -> str:
    """Превращает число в звёздочки: 0.9 → '⭐⭐⭐⭐⭐'"""
    if score < 0:
        return "🆕"   # новый сервер, мало данных
    stars = round(score * 5)
    return "⭐" * stars + "·" * (5 - stars)


def get_stats() -> dict:
    """Статистика по всей истории — сколько серверов, средняя надёжность и т.д."""
    history = _load()
    if not history:
        return {"total": 0}

    scores = []
    reliable = 0   # надёжность > 70%
    unstable = 0   # надёжность < 40%
    new_servers = 0

    for host, data in history.items():
        checks = data.get("checks", [])
        if len(checks) < MIN_SEEN:
            new_servers += 1
            continue
        ok = sum(1 for c in checks if c["ok"])
        score = ok / len(checks)
        scores.append(score)
        if score >= 0.7:
            reliable += 1
        elif score < 0.4:
            unstable += 1

    avg = sum(scores) / len(scores) if scores else 0
    return {
        "total":       len(history),
        "rated":       len(scores),
        "new":         new_servers,
        "reliable":    reliable,   # > 70% uptime
        "unstable":    unstable,   # < 40% uptime
        "avg_score":   round(avg, 2),
    }


def prune_old(days: int = 7):
    """
    Удаляет из истории серверы которых не видели больше N дней.
    Чтобы файл не рос бесконечно.
    """
    history  = _load()
    cutoff   = int(time.time()) - days * 86400
    before   = len(history)
    pruned   = {
        host: data
        for host, data in history.items()
        if data.get("checks") and data["checks"][-1]["ts"] >= cutoff
    }
    if len(pruned) < before:
        _save(pruned)
        log.info("🗑  История: удалено %d старых серверов", before - len(pruned))
