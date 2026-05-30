"""
Генерирует output/index.html — красивую страницу статистики
которая хостится прямо через GitHub Pages.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("html_gen")

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def generate_html(stats: dict):
    total      = stats.get("total_working", 0)
    by_proto   = stats.get("by_protocol", {})
    latency    = stats.get("latency", {})
    countries  = stats.get("top_countries", {})
    tls_ok     = stats.get("tls_confirmed", 0)
    updated    = stats.get("updated_msk", "")[:16].replace("T", " ")

    # Строки протоколов
    def proto_row(name, emoji, key):
        cnt = by_proto.get(key, 0)
        pct = round(cnt / total * 100) if total else 0
        return f"""
        <div class="proto-row">
          <span class="proto-name">{emoji} {name}</span>
          <div class="proto-bar-wrap">
            <div class="proto-bar" style="width:{pct}%"></div>
          </div>
          <span class="proto-count">{cnt}</span>
        </div>"""

    proto_rows = (
        proto_row("VLESS",      "🔷", "vless")
        + proto_row("VMess",    "🔶", "vmess")
        + proto_row("Trojan",   "🐴", "trojan")
        + proto_row("Hysteria2","⚡", "hysteria")
        + proto_row("Shadowsocks","🔲","ss")
        + proto_row("Other",    "🌐", "other")
    )

    # Строки стран
    country_rows = ""
    for i, (country, cnt) in enumerate(list(countries.items())[:10], 1):
        pct = round(cnt / total * 100) if total else 0
        country_rows += f"""
        <tr>
          <td class="rank">#{i}</td>
          <td>{country}</td>
          <td><div class="mini-bar"><div style="width:{pct}%"></div></div></td>
          <td class="cnt">{cnt}</td>
        </tr>"""

    # Ссылки на файлы
    base = "https://raw.githubusercontent.com/vit352018/vless-collector/main/output"
    files = [
        ("VLESS_WORKING.txt", "✅ Все рабочие", "all"),
        ("VLESS_ONLY.txt",    "🔷 VLESS",       "vless"),
        ("VMESS_ONLY.txt",    "🔶 VMess",        "vmess"),
        ("TROJAN_ONLY.txt",   "🐴 Trojan",       "trojan"),
        ("HYSTERIA_ONLY.txt", "⚡ Hysteria2",    "hysteria"),
        ("SS_ONLY.txt",       "🔲 Shadowsocks",  "ss"),
        ("TOP50.txt",         "🏆 TOP-50",       "all"),
    ]
    file_cards = ""
    for fname, label, key in files:
        cnt = by_proto.get(key, total) if key != "all" else total
        url = f"{base}/{fname}"
        file_cards += f"""
        <div class="file-card">
          <div class="file-label">{label}</div>
          <div class="file-count">{cnt}</div>
          <a class="copy-btn" href="{url}" target="_blank" onclick="copyUrl(this, '{url}')">📋 Копировать URL</a>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VPN Collector — Stats</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #0f1117; --card: #1a1d27; --card2: #22263a;
      --text: #e2e8f0; --muted: #8892a4; --accent: #6366f1;
      --green: #22c55e; --amber: #f59e0b; --red: #ef4444;
      --border: rgba(255,255,255,.07);
    }}
    body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
            min-height: 100vh; padding: 2rem 1rem; }}
    .wrap {{ max-width: 860px; margin: 0 auto; }}
    header {{ text-align: center; margin-bottom: 2.5rem; }}
    header h1 {{ font-size: 2rem; font-weight: 700;
                 background: linear-gradient(90deg,#6366f1,#a78bfa);
                 -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
    header p {{ color: var(--muted); margin-top: .4rem; font-size: .95rem; }}
    .badge {{ display: inline-block; background: var(--card2); border: 1px solid var(--border);
              border-radius: 20px; padding: .25rem .8rem; font-size: .8rem; color: var(--muted);
              margin-top: .6rem; }}

    .grid3 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr));
              gap: 1rem; margin-bottom: 2rem; }}
    .stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px;
                  padding: 1.2rem 1.4rem; }}
    .stat-card .val {{ font-size: 2.2rem; font-weight: 700; color: var(--accent); }}
    .stat-card .lbl {{ font-size: .8rem; color: var(--muted); margin-top: .3rem; }}

    .card {{ background: var(--card); border: 1px solid var(--border);
             border-radius: 14px; padding: 1.4rem; margin-bottom: 1.5rem; }}
    .card h2 {{ font-size: 1rem; font-weight: 600; margin-bottom: 1rem; color: var(--text); }}

    .proto-row {{ display: flex; align-items: center; gap: .75rem; margin-bottom: .6rem; font-size: .9rem; }}
    .proto-name {{ width: 120px; flex-shrink: 0; }}
    .proto-bar-wrap {{ flex: 1; background: var(--card2); border-radius: 99px; height: 8px; overflow: hidden; }}
    .proto-bar {{ height: 100%; background: linear-gradient(90deg,#6366f1,#a78bfa); border-radius: 99px;
                  min-width: 4px; transition: width .4s; }}
    .proto-count {{ width: 40px; text-align: right; color: var(--muted); font-size: .85rem; }}

    table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
    td {{ padding: .45rem .6rem; border-bottom: 1px solid var(--border); }}
    .rank {{ color: var(--muted); width: 36px; }}
    .cnt  {{ text-align: right; color: var(--accent); font-weight: 600; }}
    .mini-bar {{ background: var(--card2); border-radius: 99px; height: 6px; overflow: hidden; width: 120px; }}
    .mini-bar div {{ height: 100%; background: var(--green); border-radius: 99px; min-width: 3px; }}

    .lat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(110px,1fr)); gap: .8rem; }}
    .lat-item {{ background: var(--card2); border-radius: 10px; padding: .8rem 1rem; text-align: center; }}
    .lat-item .lv {{ font-size: 1.4rem; font-weight: 700; color: var(--amber); }}
    .lat-item .ll {{ font-size: .75rem; color: var(--muted); margin-top: .2rem; }}

    .files-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px,1fr)); gap: .8rem; }}
    .file-card {{ background: var(--card2); border: 1px solid var(--border); border-radius: 12px;
                  padding: 1rem; display: flex; flex-direction: column; gap: .5rem; }}
    .file-label {{ font-size: .9rem; font-weight: 500; }}
    .file-count  {{ font-size: 1.6rem; font-weight: 700; color: var(--accent); }}
    .copy-btn {{ display: inline-block; background: var(--accent); color: #fff; border: none;
                 border-radius: 8px; padding: .45rem .9rem; font-size: .82rem; cursor: pointer;
                 text-decoration: none; text-align: center; transition: opacity .15s; }}
    .copy-btn:hover {{ opacity: .85; }}
    .copy-btn.copied {{ background: var(--green); }}

    footer {{ text-align: center; color: var(--muted); font-size: .8rem; margin-top: 3rem; }}
    @media(max-width:480px) {{ header h1{{ font-size:1.5rem }} .stat-card .val{{font-size:1.7rem}} }}
  </style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🔄 VPN Collector</h1>
    <p>Автоматически собирает и тестирует рабочие VPN-серверы каждый час</p>
    <span class="badge">🕐 Обновлено: {updated} MSK</span>
  </header>

  <div class="grid3">
    <div class="stat-card">
      <div class="val">{total}</div>
      <div class="lbl">Рабочих серверов</div>
    </div>
    <div class="stat-card">
      <div class="val">{tls_ok}</div>
      <div class="lbl">TLS подтверждено 🔒</div>
    </div>
    <div class="stat-card">
      <div class="val">{latency.get('avg_ms', 0)}<span style="font-size:1rem">ms</span></div>
      <div class="lbl">Средняя задержка</div>
    </div>
    <div class="stat-card">
      <div class="val">{latency.get('min_ms', 0)}<span style="font-size:1rem">ms</span></div>
      <div class="lbl">Минимальная задержка</div>
    </div>
    <div class="stat-card">
      <div class="val">{latency.get('p50_ms', 0)}<span style="font-size:1rem">ms</span></div>
      <div class="lbl">Медиана (p50)</div>
    </div>
    <div class="stat-card">
      <div class="val">{latency.get('p90_ms', 0)}<span style="font-size:1rem">ms</span></div>
      <div class="lbl">Перцентиль p90</div>
    </div>
  </div>

  <div class="card">
    <h2>📡 По протоколам</h2>
    {proto_rows}
  </div>

  <div class="card">
    <h2>🌍 Топ стран</h2>
    <table><tbody>{country_rows}</tbody></table>
  </div>

  <div class="card">
    <h2>⏱ Задержка (мс)</h2>
    <div class="lat-grid">
      <div class="lat-item"><div class="lv">{latency.get('min_ms',0)}</div><div class="ll">MIN</div></div>
      <div class="lat-item"><div class="lv">{latency.get('avg_ms',0)}</div><div class="ll">AVG</div></div>
      <div class="lat-item"><div class="lv">{latency.get('p50_ms',0)}</div><div class="ll">P50</div></div>
      <div class="lat-item"><div class="lv">{latency.get('p90_ms',0)}</div><div class="ll">P90</div></div>
      <div class="lat-item"><div class="lv">{latency.get('max_ms',0)}</div><div class="ll">MAX</div></div>
    </div>
  </div>

  <div class="card">
    <h2>📥 Подписки (нажми — скопирует URL)</h2>
    <div class="files-grid">
      {file_cards}
    </div>
  </div>

  <footer>
    Обновляется автоматически каждый час через GitHub Actions •
    <a href="https://github.com/vit352018/vless-collector" style="color:#6366f1">GitHub</a>
  </footer>
</div>
<script>
function copyUrl(el, url) {{
  navigator.clipboard.writeText(url).then(() => {{
    el.textContent = '✅ Скопировано!';
    el.classList.add('copied');
    setTimeout(() => {{
      el.textContent = '📋 Копировать URL';
      el.classList.remove('copied');
    }}, 2000);
  }});
  return false;
}}
</script>
</body>
</html>"""

    path = OUTPUT_DIR / "index.html"
    path.write_text(html, encoding="utf-8")
    log.info("💾  %-25s  записан", "index.html")
