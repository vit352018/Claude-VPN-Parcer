"""
tester.py — проверяет доступность серверов через TCP и TLS.
"""
import asyncio
import logging
import ssl
import time
from typing import Optional

log = logging.getLogger("tester")

TCP_TIMEOUT = 5.0
TLS_TIMEOUT = 7.0


async def tcp_ping(host: str, port: int, timeout: float = TCP_TIMEOUT) -> Optional[int]:
    """TCP-тест. Возвращает задержку мс или None."""
    t0 = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return int((time.monotonic() - t0) * 1000)
    except Exception:
        return None


async def tls_ping(host: str, port: int, sni: Optional[str] = None, timeout: float = TLS_TIMEOUT) -> Optional[int]:
    """TLS-рукопожатие. Возвращает задержку мс или None."""
    t0  = time.monotonic()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode    = ssl.CERT_NONE
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx, server_hostname=sni or host),
            timeout=timeout,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return int((time.monotonic() - t0) * 1000)
    except Exception:
        return None


async def smart_test(host: str, port: int, sni: Optional[str] = None) -> dict:
    """TCP + TLS тест. Возвращает словарь с результатами."""
    result = {"host": host, "port": port, "tcp_ms": None, "tls_ms": None, "alive": False, "tls_ok": False}
    tcp = await tcp_ping(host, port)
    result["tcp_ms"] = tcp
    if tcp is not None:
        result["alive"] = True
        if port in (443, 8443, 2053, 2083, 2087, 2096) or sni:
            tls = await tls_ping(host, port, sni=sni)
            result["tls_ms"] = tls
            result["tls_ok"] = tls is not None
    return result


async def batch_test(
    targets: list[tuple[str, int, Optional[str]]],
    max_workers: int = 80,
) -> list[dict]:
    """Тестирует список (host, port, sni) параллельно."""
    sem     = asyncio.Semaphore(max_workers)
    results = []
    total   = len(targets)
    done    = 0

    async def _one(host, port, sni):
        nonlocal done
        async with sem:
            r = await smart_test(host, port, sni)
            done += 1
            if done % 200 == 0 or done == total:
                log.info("  тест: %d/%d  живых: %d", done, total,
                         sum(1 for x in results if x["alive"]))
        if r["alive"]:
            results.append(r)

    await asyncio.gather(*[_one(h, p, s) for h, p, s in targets])
    results.sort(key=lambda r: (not r["tls_ok"], r["tcp_ms"] or 9999))
    return results
