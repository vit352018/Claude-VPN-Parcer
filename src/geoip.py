"""
Геолокация IP-адресов через бесплатный ip-api.com
Батчевый запрос до 100 IP за раз, без ключа.
"""

import asyncio
import logging
import socket
from typing import Optional

import aiohttp

log = logging.getLogger("geoip")

GEOIP_BATCH_URL = "http://ip-api.com/batch"
BATCH_SIZE = 100
REQUEST_TIMEOUT = 10.0

# Кэш: ip → (country_code, country, city, org)
_cache: dict[str, dict] = {}

COUNTRY_CODES = {
    "AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU","AW","AX","AZ",
    "BA","BB","BD","BE","BF","BG","BH","BI","BJ","BL","BM","BN","BO","BQ","BR","BS",
    "BT","BV","BW","BY","BZ","CA","CC","CD","CF","CG","CH","CI","CK","CL","CM","CN",
    "CO","CR","CU","CV","CW","CX","CY","CZ","DE","DJ","DK","DM","DO","DZ","EC","EE",
    "EG","EH","ER","ES","ET","FI","FJ","FK","FM","FO","FR","GA","GB","GD","GE","GF",
    "GG","GH","GI","GL","GM","GN","GP","GQ","GR","GS","GT","GU","GW","GY","HK","HM",
    "HN","HR","HT","HU","ID","IE","IL","IM","IN","IO","IQ","IR","IS","IT","JE","JM",
    "JO","JP","KE","KG","KH","KI","KM","KN","KP","KR","KW","KY","KZ","LA","LB","LC",
    "LI","LK","LR","LS","LT","LU","LV","LY","MA","MC","MD","ME","MF","MG","MH","MK",
    "ML","MM","MN","MO","MP","MQ","MR","MS","MT","MU","MV","MW","MX","MY","MZ","NA",
    "NC","NE","NF","NG","NI","NL","NO","NP","NR","NU","NZ","OM","PA","PE","PF","PG",
    "PH","PK","PL","PM","PN","PR","PS","PT","PW","PY","QA","RE","RO","RS","RU","RW",
    "SA","SB","SC","SD","SE","SG","SH","SI","SJ","SK","SL","SM","SN","SO","SR","SS",
    "ST","SV","SX","SY","SZ","TC","TD","TF","TG","TH","TJ","TK","TL","TM","TN","TO",
    "TR","TT","TV","TW","TZ","UA","UG","UM","US","UY","UZ","VA","VC","VE","VG","VI",
    "VN","VU","WF","WS","YE","YT","ZA","ZM","ZW",
}


def flag_emoji(code: str) -> str:
    """ISO2 → emoji-флаг."""
    code = (code or "").strip().upper()
    if len(code) == 2 and code in COUNTRY_CODES:
        return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)
    return "🌐"


async def resolve_host(host: str) -> Optional[str]:
    """Резолвит hostname → IP."""
    try:
        loop = asyncio.get_event_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, None),
            timeout=5.0,
        )
        return infos[0][4][0] if infos else None
    except Exception:
        return None


async def geoip_batch(ips: list[str], session: aiohttp.ClientSession) -> dict[str, dict]:
    """Запрашивает геолокацию для батча IP (до 100 за раз)."""
    payload = [{"query": ip, "fields": "status,country,countryCode,city,org,query"} for ip in ips]
    try:
        async with session.post(
            GEOIP_BATCH_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                return {}
            data = await resp.json()
        result = {}
        for item in data:
            if item.get("status") == "success":
                result[item["query"]] = {
                    "country":      item.get("country", "Unknown"),
                    "country_code": item.get("countryCode", ""),
                    "city":         item.get("city", ""),
                    "org":          item.get("org", ""),
                    "flag":         flag_emoji(item.get("countryCode", "")),
                }
        return result
    except Exception as e:
        log.warning("GeoIP batch error: %s", e)
        return {}


async def geolocate_hosts(hosts: list[str]) -> dict[str, dict]:
    """
    Геолоцирует список хостов (hostname или IP).
    Использует кэш, батчевые запросы.
    Возвращает dict: host → geo_info.
    """
    # Резолвим хосты в IP параллельно
    unique_hosts = list(set(hosts))
    log.info("🌍 Геолокация %d хостов…", len(unique_hosts))

    resolve_tasks = {h: resolve_host(h) for h in unique_hosts}
    resolved = {}
    for host, coro in resolve_tasks.items():
        ip = await coro
        if ip:
            resolved[host] = ip

    # Какие IP уже в кэше?
    ips_to_fetch = [ip for ip in set(resolved.values()) if ip not in _cache]

    # Батчевые запросы
    if ips_to_fetch:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            for i in range(0, len(ips_to_fetch), BATCH_SIZE):
                batch = ips_to_fetch[i:i + BATCH_SIZE]
                geo = await geoip_batch(batch, session)
                _cache.update(geo)
                if len(ips_to_fetch) > BATCH_SIZE:
                    await asyncio.sleep(1.5)  # ip-api.com: 45 req/min без ключа

    # Собираем результат host → geo
    result: dict[str, dict] = {}
    for host in unique_hosts:
        ip = resolved.get(host)
        if ip and ip in _cache:
            result[host] = _cache[ip]
        else:
            result[host] = {
                "country": "Unknown", "country_code": "",
                "city": "", "org": "", "flag": "🌐",
            }

    log.info("🌍 Геолоцировано: %d хостов", len(result))
    return result
