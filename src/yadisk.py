"""
Загрузка файлов на Яндекс Диск через официальное API.

Как получить токен (занимает 3 минуты):
  1. Открой в браузере: https://yandex.ru/dev/disk/poligon/
  2. Нажми большую оранжевую кнопку «Получить OAuth токен»
  3. Войди в свой Яндекс-аккаунт
  4. Скопируй токен — длинная строка вида: y0_AgAAAA...
  5. Вставь его в config.py в поле YANDEX_TOKEN = "..."
  6. Поставь YANDEX_ENABLED = True
"""

import logging
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).parent.parent))
import config as cfg

log = logging.getLogger("yadisk")
API = "https://cloud-api.yandex.net/v1/disk"


def _headers():
    return {"Authorization": f"OAuth {cfg.YANDEX_TOKEN}"}


async def _ensure_folder(session, folder):
    async with session.put(
        f"{API}/resources",
        params={"path": folder},
        headers=_headers(),
    ) as resp:
        if resp.status not in (201, 409):
            log.warning("Папка %s: статус %s", folder, resp.status)


async def _get_upload_url(session, remote_path):
    async with session.get(
        f"{API}/resources/upload",
        params={"path": remote_path, "overwrite": "true"},
        headers=_headers(),
    ) as resp:
        if resp.status != 200:
            return None
        return (await resp.json()).get("href")


async def _upload_file(session, local_path, upload_url):
    data = local_path.read_bytes()
    async with session.put(upload_url, data=data) as resp:
        return resp.status in (200, 201)


async def upload_to_yandex(output_dir=None):
    """
    Загружает все файлы из output/ на Яндекс Диск.
    Вызывается автоматически если YANDEX_ENABLED = True в config.py.
    """
    if not cfg.YANDEX_ENABLED:
        return
    if not cfg.YANDEX_TOKEN:
        log.error("❌ YANDEX_TOKEN не заполнен в config.py")
        return

    output_dir = output_dir or (Path(__file__).parent.parent / "output")
    files = [f for f in output_dir.iterdir()
             if f.is_file() and not f.name.startswith("_")]

    if not files:
        log.warning("Нет файлов для загрузки")
        return

    log.info("☁️  Загружаю %d файлов → Яндекс Диск %s", len(files), cfg.YANDEX_FOLDER)

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=True),
        timeout=aiohttp.ClientTimeout(total=60),
    ) as session:
        await _ensure_folder(session, cfg.YANDEX_FOLDER)
        ok, err = 0, 0
        for f in sorted(files):
            remote = f"{cfg.YANDEX_FOLDER}/{f.name}"
            url = await _get_upload_url(session, remote)
            if url and await _upload_file(session, f, url):
                log.info("  ✅ %s", f.name)
                ok += 1
            else:
                log.warning("  ❌ %s — не удалось загрузить", f.name)
                err += 1

    log.info("☁️  Яндекс Диск: загружено %d, ошибок %d", ok, err)
