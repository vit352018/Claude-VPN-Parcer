"""
source_discovery.py — ищет новые репозитории с VPN-конфигами на GitHub.
Запускается раз в сутки, результат сохраняется в output/discovered_sources.json.
"""
import json
import logging
import re
from pathlib import Path

import aiohttp

log = logging.getLogger("discovery")

OUTPUT_DIR   = Path(__file__).parent.parent / "output"
SOURCES_FILE = OUTPUT_DIR / "discovered_sources.json"
MAX_SOURCES  = 30
MIN_STARS    = 5
FETCH_TIMEOUT = 15

GITHUB_QUERIES = [
    "free vless nodes subscription",
    "free vmess configs subscription",
    "free clash nodes",
    "v2ray free subscription",
    "sing-box free nodes",
]

FILE_PATTERNS = [
    r"(?i)sub\d*\.txt$", r"(?i)vless.*\.txt$", r"(?i)vmess.*\.txt$",
    r"(?i)v2ray.*\.txt$", r"(?i)nodes?.*\.txt$", r"(?i)configs?.*\.txt$",
    r"(?i)free.*\.txt$", r"(?i)clash.*\.yaml$", r"(?i)subscription.*\.txt$",
]

PROTOCOLS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://")


def _matches(filename: str) -> bool:
    return any(re.search(p, filename) for p in FILE_PATTERNS)


def _count(text: str) -> int:
    return sum(1 for l in text.splitlines() if any(l.strip().startswith(p) for p in PROTOCOLS))


async def _search(session, query: str, max_results: int = 5) -> list[dict]:
    try:
        async with session.get(
            "https://api.github.com/search/repositories",
            params={"q": f"{query} pushed:>2024-01-01", "sort": "updated", "order": "desc", "per_page": max_results},
            timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
            headers={"Accept": "application/vnd.github.v3+json"},
        ) as resp:
            if resp.status != 200: return []
            data = await resp.json()
            return [{"name": i["full_name"], "stars": i["stargazers_count"],
                     "branch": i.get("default_branch","main")}
                    for i in data.get("items",[]) if i.get("stargazers_count",0) >= MIN_STARS]
    except Exception as e:
        log.warning("GitHub search (%s): %s", query, e); return []


async def _find_files(session, repo: str, branch: str) -> list[str]:
    try:
        async with session.get(
            f"https://api.github.com/repos/{repo}/git/trees/{branch}",
            params={"recursive": "1"}, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
            headers={"Accept": "application/vnd.github.v3+json"},
        ) as resp:
            if resp.status != 200: return []
            data = await resp.json()
            return [
                f"https://raw.githubusercontent.com/{repo}/{branch}/{i['path']}"
                for i in data.get("tree",[])
                if i.get("type") == "blob" and _matches(i.get("path","").split("/")[-1])
            ][:5]
    except Exception:
        return []


async def _verify(session, url: str) -> int:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT),
                               headers={"User-Agent": "Mozilla/5.0"}) as resp:
            if resp.status != 200: return 0
            text = await resp.text(errors="ignore")
            import base64 as _b64
            try:
                padded  = text.strip() + "=" * (-len(text.strip()) % 4)
                decoded = _b64.b64decode(padded).decode("utf-8", errors="ignore")
                cnt_d   = _count(decoded)
                if cnt_d > _count(text): return cnt_d
            except Exception:
                pass
            return _count(text)
    except Exception:
        return 0


async def discover_new_sources(max_new: int = 10) -> list[dict]:
    """Ищет новые источники на GitHub. Возвращает список новых."""
    log.info("🔍 Ищу новые источники на GitHub…")

    existing: set[str] = set()
    if SOURCES_FILE.exists():
        try:
            existing = {s["url"] for s in json.loads(SOURCES_FILE.read_text(encoding="utf-8"))}
        except Exception:
            pass
    try:
        from collector import SOURCES as BUILTIN
        existing |= {s["url"] for s in BUILTIN}
    except Exception:
        pass

    new_sources: list[dict] = []
    connector = aiohttp.TCPConnector(ssl=False, limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        for query in GITHUB_QUERIES:
            if len(new_sources) >= max_new: break
            repos = await _search(session, query, max_results=5)
            log.info("  «%s» → %d репозиториев", query, len(repos))
            for repo in repos:
                if len(new_sources) >= max_new: break
                for url in await _find_files(session, repo["name"], repo["branch"]):
                    if url in existing: continue
                    cnt = await _verify(session, url)
                    if cnt >= 5:
                        new_sources.append({"name": f"{repo['name']} (auto)", "url": url,
                                            "type": "raw", "stars": repo["stars"], "configs_found": cnt})
                        existing.add(url)
                        log.info("  ✅ %s (%d конфигов)", url.split("githubusercontent.com/")[1][:60] if "githubusercontent" in url else url[:60], cnt)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_saved: list[dict] = []
    if SOURCES_FILE.exists():
        try: all_saved = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        except Exception: pass

    saved_urls = {s["url"] for s in all_saved}
    for s in new_sources:
        if s["url"] not in saved_urls:
            all_saved.append(s)

    all_saved.sort(key=lambda x: x.get("configs_found", 0), reverse=True)
    all_saved = all_saved[:MAX_SOURCES]
    SOURCES_FILE.write_text(json.dumps(all_saved, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("🔍 Готово: +%d новых, в базе: %d", len(new_sources), len(all_saved))
    return new_sources


def load_discovered() -> list[dict]:
    if not SOURCES_FILE.exists(): return []
    try:
        return [{"name": s["name"], "url": s["url"], "type": s.get("type","raw")}
                for s in json.loads(SOURCES_FILE.read_text(encoding="utf-8"))]
    except Exception:
        return []
