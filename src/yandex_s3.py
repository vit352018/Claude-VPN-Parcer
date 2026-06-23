"""
yandex_s3.py — загружает файлы в Yandex Object Storage (S3).

Постоянные ссылки вида:
  https://storage.yandexcloud.net/<бакет>/<файл>

Отдаёт сырой текст напрямую — Karing читает без проблем.
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

CONTENT_TYPES = {
    ".txt":  "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
}

FILES_TO_UPLOAD = [
    "VLESS_WORKING.txt",
    "RU_BYPASS.txt",
    "MOB_WL.txt",
    "WIFI_BL.txt",
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


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, date_stamp: str) -> bytes:
    k = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k = _sign(k, S3_REGION)
    k = _sign(k, "s3")
    k = _sign(k, "aws4_request")
    return k


async def _put_object(
    session: aiohttp.ClientSession,
    bucket: str, key: str, data: bytes,
    content_type: str, access_key: str, secret_key: str,
) -> int:
    now        = datetime.now(timezone.utc)
    amz_date   = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    host       = f"{bucket}.{S3_ENDPOINT}"
    uri        = "/" + quote(key, safe="/")
    ph         = hashlib.sha256(data).hexdigest()

    can_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-amz-acl:public-read\n"
        f"x-amz-content-sha256:{ph}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed = "content-type;host;x-amz-acl;x-amz-content-sha256;x-amz-date"
    can_req = "\n".join(["PUT", uri, "", can_headers, signed, ph])

    scope = f"{date_stamp}/{S3_REGION}/s3/aws4_request"
    sts   = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(can_req.encode()).hexdigest(),
    ])
    sig  = hmac.new(_signing_key(secret_key, date_stamp), sts.encode(), hashlib.sha256).hexdigest()
    auth = f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={sig}"

    headers = {
        "Content-Type":         content_type,
        "x-amz-acl":            "public-read",
        "x-amz-content-sha256": ph,
        "x-amz-date":           amz_date,
        "Authorization":        auth,
    }
    async with session.put(
        f"https://{host}{uri}", data=data, headers=headers,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status not in (200, 201):
            body = await resp.text()
            log.warning("  ❌ %-28s HTTP %s: %s", key, resp.status, body[:150])
        return resp.status


async def upload_all(bucket: str, access_key: str, secret_key: str) -> dict:
    if not (bucket and access_key and secret_key):
        log.info("☁️  Yandex S3 пропущен (нет bucket/keys)")
        return {"uploaded": 0, "failed": 0, "skipped": 0}

    log.info("☁️  Yandex Object Storage → бакет: %s", bucket)
    results = {"uploaded": 0, "failed": 0, "skipped": 0}
    links:  dict[str, str] = {}

    connector = aiohttp.TCPConnector(ssl=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        for filename in FILES_TO_UPLOAD:
            path = OUTPUT_DIR / filename
            if not path.exists():
                results["skipped"] += 1; continue

            data  = path.read_bytes()
            ctype = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
            status = await _put_object(session, bucket, filename, data, ctype, access_key, secret_key)

            if status in (200, 201):
                url = f"https://{S3_ENDPOINT}/{bucket}/{filename}"
                links[filename] = url
                results["uploaded"] += 1
                log.info("  ✅ %-28s (%d байт)", filename, len(data))
            else:
                results["failed"] += 1

    if links:
        _save_links(links, bucket)

    log.info("☁️  S3 готово: загружено=%d  ошибок=%d  пропущено=%d",
             results["uploaded"], results["failed"], results["skipped"])
    return results


def _save_links(links: dict[str, str], bucket: str):
    lines = [
        "# ═══════════════════════════════════════════════════════",
        "# Постоянные ссылки — Yandex Object Storage",
        "# Отдают сырой текст напрямую. Karing читает без проблем.",
        "# ═══════════════════════════════════════════════════════",
        "",
        f"# Бакет: {bucket}",
        "",
    ]
    for filename in FILES_TO_UPLOAD:
        if filename.endswith(".txt") and filename in links:
            lines.append(f"# {filename}:")
            lines.append(links[filename])
            lines.append("")

    out = OUTPUT_DIR / "yadisk_links.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    log.info("  💾 Ссылки → output/yadisk_links.txt")
