"""
yandex_s3.py — загружает файлы в Yandex Object Storage (S3-совместимое).

Простыми словами:
  Это другой продукт Яндекса — облачное хранилище файлов,
  как Amazon S3, но от Яндекса. Домен storage.yandexcloud.net.

  В отличие от Яндекс Диска, отдаёт файлы напрямую как обычный
  веб-сервер — без HTML-обёрток. Karing читает такие ссылки
  как обычную подписку.

  Ссылка ПОСТОЯННАЯ и НЕ истекает:
    https://storage.yandexcloud.net/<бакет>/<файл>

─────────────────────────────────────────────────────────────────────────
НАСТРОЙКА (10 минут, один раз):

  1. https://cloud.yandex.ru → зарегистрируйся (есть бесплатный грант)

  2. Слева: Object Storage → "Создать бакет"
     - Имя: придумай уникальное, например vless-collector-12345
     - Доступ на чтение объектов: ПУБЛИЧНОЕ (на чтение)
     - Остальное можно оставить по умолчанию

  3. Слева: Сервисные аккаунты → "Создать сервисный аккаунт"
     - Имя: vless-bot
     - Роль: storage.editor
     - Создать

  4. Открой созданный сервисный аккаунт → вкладка "Ключи доступа"
     → "Создать новый ключ" → "Статический ключ доступа"
     → скопируй Key ID и Secret Key (Secret показывается ОДИН РАЗ)

  5. Добавь в GitHub Secrets:
       YANDEX_S3_BUCKET     = имя бакета из шага 2
       YANDEX_S3_ACCESS_KEY = Key ID из шага 4
       YANDEX_S3_SECRET_KEY = Secret Key из шага 4
"""
import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import aiohttp

log = logging.getLogger("yandex_s3")

S3_ENDPOINT = "storage.yandexcloud.net"
S3_REGION   = "ru-central1"

# Content-Type для разных расширений — важно, чтобы Karing
# и браузер правильно понимали что внутри файла
CONTENT_TYPES = {
    ".txt":  "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}

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


# ── AWS Signature V4 (используется и Yandex S3) ────────────────────────────────

def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signature_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date    = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region  = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


async def _put_object(
    session: aiohttp.ClientSession,
    bucket: str,
    key: str,
    data: bytes,
    content_type: str,
    access_key: str,
    secret_key: str,
) -> int:
    """
    Загружает один файл (объект) в бакет через S3 PUT-запрос
    с подписью AWS Signature V4.

    Возвращает HTTP-статус ответа.
    """
    now        = datetime.now(timezone.utc)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    host          = f"{bucket}.{S3_ENDPOINT}"
    canonical_uri = "/" + quote(key, safe="/")
    payload_hash  = hashlib.sha256(data).hexdigest()

    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-amz-acl:public-read\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-amz-acl;x-amz-content-sha256;x-amz-date"

    canonical_request = "\n".join([
        "PUT", canonical_uri, "",
        canonical_headers, signed_headers, payload_hash,
    ])

    credential_scope = f"{date_stamp}/{S3_REGION}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _signature_key(secret_key, date_stamp, S3_REGION, "s3")
    signature   = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "Content-Type":         content_type,
        "x-amz-acl":            "public-read",
        "x-amz-content-sha256": payload_hash,
        "x-amz-date":           amz_date,
        "Authorization":        authorization,
    }

    url = f"https://{host}{canonical_uri}"
    async with session.put(
        url, data=data, headers=headers,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status not in (200, 201):
            body = await resp.text()
            log.warning("  ❌ %s — HTTP %s: %s", key, resp.status, body[:200])
        return resp.status


async def upload_all(bucket: str, access_key: str, secret_key: str) -> dict:
    """
    Загружает все файлы из output/ в бакет Yandex Object Storage.
    Делает их публично доступными по постоянным ссылкам:
      https://storage.yandexcloud.net/<bucket>/<filename>
    """
    if not (bucket and access_key and secret_key):
        log.info("☁️  Yandex S3 пропущен (нет bucket/access_key/secret_key)")
        return {"uploaded": 0, "failed": 0, "skipped": 0}

    log.info("☁️  Загружаю в Yandex Object Storage (бакет: %s)…", bucket)
    results = {"uploaded": 0, "failed": 0, "skipped": 0}
    links: dict[str, str] = {}

    connector = aiohttp.TCPConnector(ssl=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        for filename in FILES_TO_UPLOAD:
            path = OUTPUT_DIR / filename
            if not path.exists():
                results["skipped"] += 1
                continue

            data = path.read_bytes()
            ext  = path.suffix
            ctype = CONTENT_TYPES.get(ext, "application/octet-stream")

            status = await _put_object(
                session, bucket, filename, data, ctype, access_key, secret_key,
            )
            if status in (200, 201):
                url = f"https://{S3_ENDPOINT}/{bucket}/{filename}"
                links[filename] = url
                results["uploaded"] += 1
                log.info("  ✅ %-25s (%d байт) → %s", filename, len(data), url)
            else:
                results["failed"] += 1

    # Сохраняем ссылки
    if links:
        _save_links(links, bucket)

    log.info("☁️  Yandex S3: загружено=%d  ошибок=%d  пропущено=%d",
             results["uploaded"], results["failed"], results["skipped"])
    return results


def _save_links(links: dict[str, str], bucket: str):
    """Сохраняет постоянные ссылки в output/yadisk_links.txt."""
    lines = [
        "# ═══════════════════════════════════════════════════════",
        "# Постоянные ссылки — Yandex Object Storage",
        "# Никогда не истекают, отдают сырой текст напрямую.",
        "# ═══════════════════════════════════════════════════════",
        "",
        f"# Бакет: {bucket}",
        "",
    ]
    for filename, url in sorted(links.items()):
        if filename.endswith(".txt"):
            lines.append(f"# {filename}:")
            lines.append(url)
            lines.append("")

    out = OUTPUT_DIR / "yadisk_links.txt"
    existing = out.read_text(encoding="utf-8") if out.exists() else ""
    out.write_text(existing + "\n" + "\n".join(lines), encoding="utf-8")
    log.info("  💾 Ссылки добавлены в output/yadisk_links.txt")
