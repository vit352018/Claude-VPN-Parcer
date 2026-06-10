"""
yandex_upload.py — загружает файлы на Яндекс Диск.

Два режима:
  1. OAuth-токен (YANDEX_TOKEN) — рекомендуется.
     Загружает файлы через REST API, открывает папку публично,
     получает прямые ссылки для скачивания — именно их читает Karing.

  2. WebDAV (YANDEX_LOGIN + YANDEX_PASS) — запасной вариант.
     Загружает файлы, но прямые ссылки недоступны.
     Нужно вручную открыть папку на disk.yandex.ru.

Как получить OAuth-токен (5 минут):
  1. https://oauth.yandex.ru/ → "Зарегистрировать приложение"
  2. Название: vless-collector, Платформа: Веб-сервисы
  3. Redirect URI: https://oauth.yandex.ru/verification_code
  4. Права: Яндекс Диск → "Запись в любом месте диска"
  5. Создать → скопируй CLIENT_ID
  6. Открой в браузере:
     https://oauth.yandex.ru/authorize?response_type=token&client_id=ТВОЙ_CLIENT_ID
  7. Разреши → скопируй токен из адресной строки (после access_token= до &)
  8. Добавь в GitHub Secrets: YANDEX_TOKEN = полученный токен
"""
import logging
import os
from pathlib import Path

import aiohttp

log = logging.getLogger("yandex")

YADISK_API    = "https://cloud-api.yandex.net/v1/disk"
REMOTE_FOLDER = "vless-collector"

FILES_TO_UPLOAD = [
    "VLESS_WORKING.txt",
    "RU_BYPASS.txt",
    "VLESS_ONLY.txt",
    "VMESS_ONLY.txt",
    "TROJAN_ONLY.txt",
    "HYSTERIA_ONLY.txt",
    "SS_ONLY.txt",
    "TOP50.txt",
    "TOP50_RELIABLE.txt",
    "stats.json",
    "index.html",
]

OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ── REST API (OAuth) ───────────────────────────────────────────────────────────

async def _api_get(session, url, params=None):
    async with session.get(url, params=params or {},
                           timeout=aiohttp.ClientTimeout(total=30)) as resp:
        return await resp.json(), resp.status


async def ensure_folder(session, folder: str) -> bool:
    data, status = await _api_get(session, f"{YADISK_API}/resources", {"path": folder})
    if status == 200:
        log.info("📁 Папка /%s существует", folder); return True
    if status == 404:
        async with session.put(f"{YADISK_API}/resources", params={"path": folder},
                               timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status in (201, 409):
                log.info("📁 Папка /%s создана", folder); return True
    log.warning("⚠️  Не удалось подготовить папку /%s: HTTP %s", folder, status)
    return False


async def publish_folder(session, folder: str) -> str | None:
    """Открывает папку публично, возвращает public_key."""
    async with session.put(f"{YADISK_API}/resources/publish", params={"path": folder},
                           timeout=aiohttp.ClientTimeout(total=30)) as resp:
        if resp.status not in (200, 201, 409):
            log.warning("⚠️  Публикация папки: HTTP %s", resp.status)
            return None
    data, status = await _api_get(session, f"{YADISK_API}/resources",
                                  {"path": folder, "fields": "public_key,public_url"})
    if status == 200:
        log.info("🌐 Публичная ссылка: %s", data.get("public_url", ""))
        return data.get("public_key")
    return None


async def upload_file_api(session, local_path: Path, remote_folder: str) -> tuple[bool, str | None]:
    """Загружает файл через REST API. Возвращает (успех, прямая_ссылка)."""
    if not local_path.exists():
        log.warning("  Файл не найден: %s", local_path.name)
        return False, None

    remote_path = f"{remote_folder}/{local_path.name}"
    data_bytes  = local_path.read_bytes()

    try:
        # Шаг 1: получить URL для загрузки
        data, status = await _api_get(session, f"{YADISK_API}/resources/upload",
                                      {"path": remote_path, "overwrite": "true"})
        if status != 200 or not data.get("href"):
            log.warning("  ❌ %-25s нет upload URL: HTTP %s", local_path.name, status)
            return False, None

        # Шаг 2: загрузить файл
        async with session.put(data["href"], data=data_bytes,
                               timeout=aiohttp.ClientTimeout(total=120),
                               headers={"Content-Type": "text/plain; charset=utf-8"}) as resp:
            if resp.status not in (200, 201, 204):
                log.warning("  ❌ %-25s HTTP %s", local_path.name, resp.status)
                return False, None

        log.info("  ✅ %-25s (%d байт)", local_path.name, len(data_bytes))

        # Шаг 3: получить прямую ссылку для скачивания
        dl_data, dl_status = await _api_get(session, f"{YADISK_API}/resources/download",
                                            {"path": remote_path})
        direct_url = dl_data.get("href") if dl_status == 200 else None
        return True, direct_url

    except Exception as e:
        log.error("  💥 %-25s %s", local_path.name, e)
        return False, None


def _save_links(links: dict[str, str], raw_base: str):
    """
    Сохраняет все ссылки в output/yadisk_links.txt.

    Содержит:
    - Постоянные ссылки с GitHub (рекомендуются для Karing)
    - Временные прямые ссылки с Яндекс Диска (~30 минут)
    """
    lines = [
        "# ═══════════════════════════════════════════════════════",
        "# Ссылки для подписок Karing / Hiddify / v2rayN",
        "# ═══════════════════════════════════════════════════════",
        "",
        "# ПОСТОЯННЫЕ ссылки (GitHub) — рекомендуются:",
        "# Работают всегда, обновляются каждый час.",
        "",
    ]
    for filename in FILES_TO_UPLOAD:
        if filename.endswith((".txt",)):
            lines.append(f"# {filename}:")
            lines.append(f"{raw_base}/{filename}")
            lines.append("")

    lines += [
        "",
        "# ВРЕМЕННЫЕ прямые ссылки Яндекс Диска (~30 минут):",
        "# Обновляются при каждом запуске бота.",
        "",
    ]
    for filename, url in sorted(links.items()):
        lines.append(f"# {filename}:")
        lines.append(url)
        lines.append("")

    out = OUTPUT_DIR / "yadisk_links.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("  💾 Ссылки сохранены: output/yadisk_links.txt")


async def _upload_via_api(token: str, raw_base: str) -> dict:
    """Загрузка через REST API с OAuth-токеном."""
    log.info("☁️  Яндекс Диск REST API…")
    headers   = {"Authorization": f"OAuth {token}", "Accept": "application/json"}
    connector = aiohttp.TCPConnector(ssl=True)
    results   = {"uploaded": 0, "failed": 0, "skipped": 0}
    dl_links: dict[str, str] = {}

    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        if not await ensure_folder(session, REMOTE_FOLDER):
            return results
        await publish_folder(session, REMOTE_FOLDER)

        for filename in FILES_TO_UPLOAD:
            local_path = OUTPUT_DIR / filename
            if not local_path.exists():
                results["skipped"] += 1; continue
            ok, direct_url = await upload_file_api(session, local_path, REMOTE_FOLDER)
            if ok:
                results["uploaded"] += 1
                if direct_url:
                    dl_links[filename] = direct_url
            else:
                results["failed"] += 1

    if dl_links:
        _save_links(dl_links, raw_base)

    log.info("☁️  API: загружено=%d  ошибок=%d  пропущено=%d",
             results["uploaded"], results["failed"], results["skipped"])
    return results


# ── WebDAV (запасной вариант) ─────────────────────────────────────────────────

async def _upload_via_webdav(login: str, password: str) -> dict:
    """Загрузка через WebDAV. Прямые ссылки недоступны."""
    log.info("☁️  Яндекс Диск WebDAV (логин: %s)…", login)
    log.warning(
        "⚠️  WebDAV не поддерживает прямые ссылки для Karing.\n"
        "    Для работы с Karing настрой YANDEX_TOKEN (OAuth).\n"
        "    Инструкция: читай комментарий в yandex_upload.py"
    )
    WEBDAV    = "https://webdav.yandex.ru"
    auth      = aiohttp.BasicAuth(login, password)
    connector = aiohttp.TCPConnector(ssl=True)
    results   = {"uploaded": 0, "failed": 0, "skipped": 0}

    async with aiohttp.ClientSession(auth=auth, connector=connector) as session:
        async with session.request("MKCOL", f"{WEBDAV}/{REMOTE_FOLDER}") as resp:
            if resp.status in (201, 405):
                log.info("📁 Папка /%s готова", REMOTE_FOLDER)

        for filename in FILES_TO_UPLOAD:
            local_path = OUTPUT_DIR / filename
            if not local_path.exists():
                results["skipped"] += 1; continue
            data = local_path.read_bytes()
            try:
                async with session.put(
                    f"{WEBDAV}/{REMOTE_FOLDER}/{filename}", data=data,
                    timeout=aiohttp.ClientTimeout(total=60),
                    headers={"Content-Type": "application/octet-stream"},
                ) as resp:
                    if resp.status in (200, 201, 204):
                        log.info("  ✅ %-25s (%d байт)", filename, len(data))
                        results["uploaded"] += 1
                    else:
                        body = await resp.text()
                        log.warning("  ❌ %-25s HTTP %s: %s", filename, resp.status, body[:100])
                        results["failed"] += 1
            except Exception as e:
                log.error("  💥 %-25s %s", filename, e)
                results["failed"] += 1

    log.info("☁️  WebDAV: загружено=%d  ошибок=%d  пропущено=%d",
             results["uploaded"], results["failed"], results["skipped"])
    log.info("📋 Открой папку вручную: disk.yandex.ru → vless-collector → Поделиться")
    return results


# ── Главная функция ────────────────────────────────────────────────────────────

async def upload_all(token: str = "", login: str = "", password: str = "",
                     raw_base: str = "") -> dict:
    """Загружает все файлы — выбирает метод автоматически."""
    token = token or os.environ.get("YANDEX_TOKEN", "").strip()
    if not raw_base:
        import sys; sys.path.insert(0, str(Path(__file__).parent.parent))
        import config as _cfg; raw_base = _cfg.RAW_BASE

    if token:
        return await _upload_via_api(token, raw_base)
    elif login and password:
        return await _upload_via_webdav(login, password)
    else:
        log.warning("☁️  Нет YANDEX_TOKEN и нет YANDEX_LOGIN+YANDEX_PASS")
        return {"uploaded": 0, "failed": 0, "skipped": 0}
