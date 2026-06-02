"""
source_discovery.py — автоматически ищет новые источники бесплатных конфигов.

Простыми словами:
  Бот раз в сутки идёт на GitHub и ищет новые репозитории
  с бесплатными VPN-ключами. Если нашёл рабочий —
  добавляет в список источников автоматически.

  Это значит список источников сам обновляется
  и не устаревает, даже если старые репозитории умирают.

  Результат сохраняется в output/discovered_sources.json
  и подхватывается collector.py при следующем запуске.
"""

import json
import logging
import re
from pathlib import Path

import aiohttp

log = logging.getLogger("discovery")

OUTPUT_DIR     = Path(__file__).parent.parent / "output"
SOURCES_FILE   = OUTPUT_DIR / "discovered_sources.json"
MAX_SOURCES    = 30     # не больше N автообнаруженных источников
MIN_STARS      = 5      # репозиторий должен иметь хотя бы 5 звёзд
FETCH_TIMEOUT  = 15

# Поисковые запросы на GitHub
GITHUB_QUERIES = [
    "free vless nodes subscription",
    "free vmess configs subscription",
    "free clash nodes",
    "v2ray free subscription",
    "sing-box free nodes",
]

# Паттерны файлов которые могут содержать конфиги
FILE_PATTERNS = [
    r"(?i)sub\d*\.txt$",
    r"(?i)vless.*\.txt$",
    r"(?i)vmess.*\.txt$",
    r"(?i)v2ray.*\.txt$",
    r"(?i)nodes?.*\.txt$",
    r"(?i)configs?.*\.txt$",
    r"(?i)free.*\.txt$",
    r"(?i)clash.*\.yaml$",
    r"(?i)subscription.*\.txt$",
]

PROTOCOLS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://")


def _matches_file_pattern(filename: str) -> bool:
    return any(re.search(p, filename) for p in FILE_PATTERNS)


def _count_configs(text: str) -> int:
    """Считает количество VPN-ключей в тексте."""
    count = 0
    for line in text.splitlines():
        if any(line.strip().startswith(p) for p in PROTOCOLS):
            count += 1
    return count


async def _search_github(
    session: aiohttp.ClientSession,
    query: str,
    max_results: int = 5,
) -> list[dict]:
    """
    Ищет репозитории на GitHub по запросу.
    Возвращает список {"name", "url", "stars", "default_branch"}.
    """
    url = "https://api.github.com/search/repositories"
    params = {
        "q":        f"{query} pushed:>2024-01-01",
        "sort":     "updated",
        "order":    "desc",
        "per_page": max_results,
    }
    try:
        async with session.get(
            url, params=params,
            timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
            headers={"Accept": "application/vnd.github.v3+json"},
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            results = []
            for item in data.get("items", []):
                if item.get("stargazers_count", 0) >= MIN_STARS:
                    results.append({
                        "name":    item["full_name"],
                        "stars":   item["stargazers_count"],
                        "branch":  item.get("default_branch", "main"),
                    })
            return results
    except Exception as e:
        log.warning("GitHub search error (%s): %s", query, e)
        return []


async def _find_config_files(
    session: aiohttp.ClientSession,
    repo_name: str,
    branch: str,
) -> list[str]:
    """
    Ищет файлы с конфигами в репозитории через GitHub API.
    Возвращает raw-ссылки на найденные файлы.
    """
    url = f"https://api.github.com/repos/{repo_name}/git/trees/{branch}"
    params = {"recursive": "1"}
    raw_urls = []
    try:
        async with session.get(
            url, params=params,
            timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
            headers={"Accept": "application/vnd.github.v3+json"},
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            for item in data.get("tree", []):
                if item.get("type") == "blob":
                    path = item.get("path", "")
                    filename = path.split("/")[-1]
                    if _matches_file_pattern(filename):
                        raw_url = (
                            f"https://raw.githubusercontent.com"
                            f"/{repo_name}/{branch}/{path}"
                        )
                        raw_urls.append(raw_url)
    except Exception as e:
        log.warning("Tree fetch error (%s): %s", repo_name, e)
    return raw_urls[:5]  # не больше 5 файлов с одного репозитория


async def _verify_url(session: aiohttp.ClientSession, url: str) -> int:
    """
    Проверяет, что по URL реально есть VPN-ключи.
    Возвращает количество найденных конфигов (0 = не подходит).
    """
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
            headers={"User-Agent": "Mozilla/5.0"},
        ) as resp:
            if resp.status != 200:
                return 0
            text = await resp.text(errors="ignore")
            # Декодируем base64 если нужно
            import base64 as _b64
            try:
                padded = text.strip() + "=" * (-len(text.strip()) % 4)
                decoded = _b64.b64decode(padded).decode("utf-8", errors="ignore")
                cnt_decoded = _count_configs(decoded)
                if cnt_decoded > _count_configs(text):
                    return cnt_decoded
            except Exception:
                pass
            return _count_configs(text)
    except Exception:
        return 0


async def discover_new_sources(max_new: int = 10) -> list[dict]:
    """
    Главная функция обнаружения.
    Возвращает список новых источников в формате collector.SOURCES.
    """
    log.info("🔍 Ищу новые источники конфигов на GitHub…")

    # Загружаем уже известные источники чтобы не дублировать
    existing_urls: set[str] = set()
    if SOURCES_FILE.exists():
        try:
            saved = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
            existing_urls = {s["url"] for s in saved}
        except Exception:
            pass

    # Добавляем встроенные URL из collector.py
    try:
        from collector import SOURCES as BUILTIN_SOURCES
        existing_urls |= {s["url"] for s in BUILTIN_SOURCES}
    except Exception:
        pass

    new_sources: list[dict] = []
    connector = aiohttp.TCPConnector(ssl=False, limit=10)

    async with aiohttp.ClientSession(connector=connector) as session:
        # Ищем по каждому запросу
        for query in GITHUB_QUERIES:
            if len(new_sources) >= max_new:
                break
            repos = await _search_github(session, query, max_results=5)
            log.info("  Запрос «%s» → %d репозиториев", query, len(repos))

            for repo in repos:
                if len(new_sources) >= max_new:
                    break
                # Ищем конфиг-файлы в репозитории
                raw_urls = await _find_config_files(
                    session, repo["name"], repo["branch"]
                )
                for url in raw_urls:
                    if url in existing_urls:
                        continue
                    cnt = await _verify_url(session, url)
                    if cnt >= 5:   # минимум 5 конфигов в файле
                        source = {
                            "name":  f"{repo['name']} (auto)",
                            "url":   url,
                            "type":  "raw",
                            "stars": repo["stars"],
                            "configs_found": cnt,
                        }
                        new_sources.append(source)
                        existing_urls.add(url)
                        log.info(
                            "  ✅ Найден: %-50s (%d конфигов, ⭐%d)",
                            url.split("githubusercontent.com/")[1][:50] if "githubusercontent" in url else url[:50],
                            cnt, repo["stars"]
                        )

    # Сохраняем (объединяем старые + новые)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_saved: list[dict] = []
    if SOURCES_FILE.exists():
        try:
            all_saved = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Добавляем только новые
    existing_in_saved = {s["url"] for s in all_saved}
    for s in new_sources:
        if s["url"] not in existing_in_saved:
            all_saved.append(s)

    # Не больше MAX_SOURCES — оставляем с наибольшим числом конфигов
    all_saved.sort(key=lambda x: x.get("configs_found", 0), reverse=True)
    all_saved = all_saved[:MAX_SOURCES]

    SOURCES_FILE.write_text(
        json.dumps(all_saved, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(
        "🔍 Обнаружение завершено: +%d новых, всего в базе: %d",
        len(new_sources), len(all_saved),
    )
    return new_sources


def load_discovered() -> list[dict]:
    """
    Загружает ранее найденные источники.
    Возвращает в формате совместимом с collector.SOURCES.
    """
    if not SOURCES_FILE.exists():
        return []
    try:
        saved = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        # Возвращаем только поля нужные collector-у
        return [
            {"name": s["name"], "url": s["url"], "type": s.get("type", "raw")}
            for s in saved
        ]
    except Exception:
        return []
