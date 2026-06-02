"""
yandex_upload.py — загружает готовые файлы на Яндекс Диск

Как это работает, простыми словами:
  Яндекс Диск умеет принимать файлы по протоколу WebDAV.
  Это как "загрузить файл по ссылке", только автоматически.
  Нам нужен только логин и пароль приложения (не основной пароль!).

Что нужно сделать ОДИН РАЗ:
  1. Зайти на https://id.yandex.ru/security/app-passwords
  2. Нажать "Создать пароль приложения"
  3. Выбрать тип "WebDAV" → дать название "vless-bot"
  4. Скопировать пароль (он показывается только один раз!)
  5. В настройках GitHub репозитория:
     Settings → Secrets → Actions → New repository secret
     Имя:  YANDEX_LOGIN   Значение: ваш_логин@yandex.ru
     Имя:  YANDEX_PASS    Значение: пароль_из_шага_4
"""

import logging
from pathlib import Path

import aiohttp

log = logging.getLogger("yandex")

# Адрес WebDAV Яндекс Диска — это фиксированный адрес, не меняется
YANDEX_WEBDAV = "https://webdav.yandex.ru"

# Папка на Яндекс Диске, куда складывать файлы
# Если папки нет — создадим автоматически
REMOTE_FOLDER = "vless-collector"

# Какие файлы загружать (из папки output/)
FILES_TO_UPLOAD = [
    "VLESS_WORKING.txt",
    "VLESS_ONLY.txt",
    "VMESS_ONLY.txt",
    "TROJAN_ONLY.txt",
    "HYSTERIA_ONLY.txt",
    "SS_ONLY.txt",
    "TOP50.txt",
    "stats.json",
    "index.html",
]

OUTPUT_DIR = Path(__file__).parent.parent / "output"


async def create_folder_if_needed(session: aiohttp.ClientSession, folder: str):
    """
    Создаёт папку на Яндекс Диске, если её ещё нет.
    Команда MKCOL — это WebDAV-способ сказать "создай папку".
    Если папка уже есть — просто игнорируем ошибку.
    """
    url = f"{YANDEX_WEBDAV}/{folder}"
    async with session.request("MKCOL", url) as resp:
        if resp.status in (201, 405):
            # 201 = папка создана, 405 = уже существует — оба варианта OK
            log.info("📁 Папка /%s готова", folder)
        else:
            log.warning("⚠️  Папка /%s — статус %s", folder, resp.status)


async def upload_file(
    session: aiohttp.ClientSession,
    local_path: Path,
    remote_folder: str,
) -> bool:
    """
    Загружает один файл на Яндекс Диск.

    Простыми словами: берём файл с компьютера (или сервера GitHub)
    и кладём его в нужную папку на Яндекс Диске.
    Команда PUT — это WebDAV-способ сказать "положи файл сюда".
    """
    if not local_path.exists():
        log.warning("  Файл не найден, пропускаю: %s", local_path.name)
        return False

    url = f"{YANDEX_WEBDAV}/{remote_folder}/{local_path.name}"
    data = local_path.read_bytes()

    try:
        async with session.put(
            url,
            data=data,
            timeout=aiohttp.ClientTimeout(total=60),
            headers={"Content-Type": "application/octet-stream"},
        ) as resp:
            if resp.status in (200, 201, 204):
                # 200/201/204 — всё хорошо, файл загружен
                log.info("  ✅ %-25s → /%s/  (%d байт)",
                         local_path.name, remote_folder, len(data))
                return True
            else:
                body = await resp.text()
                log.warning("  ❌ %-25s — HTTP %s: %s",
                            local_path.name, resp.status, body[:200])
                return False
    except Exception as e:
        log.error("  💥 %-25s — ошибка: %s", local_path.name, e)
        return False


async def upload_all(login: str, password: str) -> dict:
    """
    Главная функция — загружает все файлы на Яндекс Диск.

    login    — ваш логин на Яндексе (например, vasya@yandex.ru)
    password — пароль приложения из настроек безопасности
    """
    log.info("☁️  Загружаю файлы на Яндекс Диск (логин: %s)…", login)

    # Создаём сессию с авторизацией
    # BasicAuth — это стандартный способ передать логин/пароль
    auth = aiohttp.BasicAuth(login, password)
    connector = aiohttp.TCPConnector(ssl=True)

    results = {"uploaded": 0, "failed": 0, "skipped": 0}

    async with aiohttp.ClientSession(auth=auth, connector=connector) as session:

        # Шаг 1: убеждаемся что папка существует
        await create_folder_if_needed(session, REMOTE_FOLDER)

        # Шаг 2: загружаем каждый файл по очереди
        for filename in FILES_TO_UPLOAD:
            local_path = OUTPUT_DIR / filename
            if not local_path.exists():
                results["skipped"] += 1
                continue

            ok = await upload_file(session, local_path, REMOTE_FOLDER)
            if ok:
                results["uploaded"] += 1
            else:
                results["failed"] += 1

    log.info(
        "☁️  Яндекс Диск: загружено=%d  ошибок=%d  пропущено=%d",
        results["uploaded"], results["failed"], results["skipped"],
    )
    return results


def get_public_link(filename: str) -> str:
    """
    Возвращает прямую ссылку на файл на Яндекс Диске.

    ВАЖНО: эта ссылка работает только если файл/папка
    сделана публичной вручную через интерфейс Яндекс Диска!
    (Правой кнопкой → "Поделиться" → включить публичный доступ)

    После того как папка vless-collector открыта для всех,
    ссылки на файлы внутри неё будут выглядеть так.
    """
    return f"https://disk.yandex.ru/d/vless-collector/{filename}"
