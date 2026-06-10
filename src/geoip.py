"""
geoip.py — определяет страну каждого сервера через ip-api.com.
"""
import asyncio
import logging
import socket
from typing import Optional

import aiohttp

log = logging.getLogger("geoip")

GEOIP_BATCH_URL = "http://ip-api.com/batch"
BATCH_SIZE      = 100
REQUEST_TIMEOUT = 10.0
_cache: dict[str, dict] = {}

COUNTRY_CODES = {
    "AD","AE","AF","AG","AL","AM","AO","AR","AT","AU","AZ","BA","BB","BD","BE","BF",
    "BG","BH","BI","BJ","BN","BO","BR","BS","BT","BW","BY","BZ","CA","CD","CF","CG",
    "CH","CI","CL","CM","CN","CO","CR","CU","CV","CY","CZ","DE","DJ","DK","DM","DO",
    "DZ","EC","EE","EG","ER","ES","ET","FI","FJ","FR","GA","GB","GD","GE","GH","GM",
    "GN","GQ","GR","GT","GW","GY","HK","HN","HR","HT","HU","ID","IE","IL","IN","IQ",
    "IR","IS","IT","JM","JO","JP","KE","KG","KH","KI","KM","KN","KP","KR","KW","KY",
    "KZ","LA","LB","LC","LI","LK","LR","LS","LT","LU","LV","LY","MA","MC","MD","ME",
    "MG","MK","ML","MM","MN","MO","MR","MT","MU","MV","MW","MX","MY","MZ","NA","NE",
    "NG","NI","NL","NO","NP","NR","NZ","OM","PA","PE","PG","PH","PK","PL","PS","PT",
    "PW","PY","QA","RO","RS","RU","RW","SA","SB","SC","SD","SE","SG","SI","SK","SL",
    "SM","SN","SO","SR","SS","ST","SV","SY","SZ","TD","TG","TH","TJ","TL","TM","TN",
    "TO","TR","TT","TV","TW","TZ","UA","UG","US","UY","UZ","VC","VE","VN","VU","WS",
    "YE","ZA","ZM","ZW",
}


def flag_emoji(code: str) -> str:
    code = (code or "").strip().upper()
    if len(code) == 2 and code in COUNTRY_CODES:
        return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)
    return "🌐"


async def resolve_host(host: str) -> Optional[str]:
    try:
        loop  = asyncio.get_event_loop()
        infos = await asyncio.wait_for(loop.getaddrinfo(host, None), timeout=5.0)
        return infos[0][4][0] if infos else None
    except Exception:
        return None


async def geoip_batch(ips: list[str], session: aiohttp.ClientSession) -> dict[str, dict]:
    payload = [{"query": ip, "fields": "status,country,countryCode,city,org,query"} for ip in ips]
    try:
        async with session.post(GEOIP_BATCH_URL, json=payload,
                                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as resp:
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
    """Геолоцирует список хостов. Возвращает dict: host → geo_info."""
    unique = list(set(hosts))
    log.info("🌍 Геолокация %d хостов…", len(unique))

    # Резолвим хосты в IP параллельно (вместо последовательно)
    unique_hosts = list(set(hosts))
    log.info("🌍 Геолокация %d хостов…", len(unique_hosts))

    resolve_tasks = await asyncio.gather(
        *[resolve_host(h) for h in unique_hosts],
        return_exceptions=True,
    )
    resolved = {
        h: ip
        for h, ip in zip(unique_hosts, resolve_tasks)
        if ip and isinstance(ip, str)
    }

    ips_to_fetch = [ip for ip in set(resolved.values()) if ip not in _cache]
    if ips_to_fetch:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            for i in range(0, len(ips_to_fetch), BATCH_SIZE):
                batch = ips_to_fetch[i:i + BATCH_SIZE]
                geo   = await geoip_batch(batch, session)
                _cache.update(geo)
                if i + BATCH_SIZE < len(ips_to_fetch):
                    await asyncio.sleep(1.5)  # ip-api.com: 45 req/min

    result: dict[str, dict] = {}
    empty = {"country": "Unknown", "country_code": "", "city": "", "org": "", "flag": "🌐"}
    for host in unique_hosts:
        ip = resolved.get(host)
        result[host] = _cache.get(ip, empty) if ip else empty

    log.info("🌍 Геолоцировано: %d хостов", len(result))
    return result
