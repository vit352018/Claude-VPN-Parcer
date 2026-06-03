"""
html_gen.py — генерирует красивую HTML-страницу статистики.

Простыми словами:
  После каждого запуска бот создаёт файл index.html —
  это веб-страница с графиками и таблицами.
  Её можно открыть бесплатно через GitHub Pages.

  Что показывает страница:
  - Сколько серверов найдено и протестировано
  - Разбивка по протоколам
  - Топ стран
  - График задержек
  - Кнопки «Скопировать URL подписки» для каждого файла
  - Ссылки-инструкции для добавления в Karing/Hiddify
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("html_gen")
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def generate_html(stats: dict):
    total     = stats.get("total_working", 0)
    by_proto  = stats.get("by_protocol", {})
    latency   = stats.get("latency", {})
    countries = stats.get("top_countries", {})
    tls_ok    = stats.get("tls_confirmed", 0)
    raw_base  = stats.get("raw_base", "https://raw.githubusercontent.com/YOUR/repo/main/output")
    updated   = stats.get("updated_msk", "")[:16].replace("T", " ")

    # Процент TLS
    tls_pct = round(tls_ok / total * 100) if total else 0

    # ── Карточки с файлами подписок ──────────────────────────────────────────
    sub_files = [
        ("VLESS_WORKING.txt",   "✅ Все рабочие",             "all",       total),
        ("RU_BYPASS.txt",       "🇷🇺 Обход РКН (Reality)",    "ru_bypass", by_proto.get("ru_bypass", 0)),
        ("VLESS_ONLY.txt",      "🔷 VLESS",                   "vless",     by_proto.get("vless", 0)),
        ("VMESS_ONLY.txt",      "🔶 VMess",                   "vmess",     by_proto.get("vmess", 0)),
        ("TROJAN_ONLY.txt",     "🐴 Trojan",                  "trojan",    by_proto.get("trojan", 0)),
        ("HYSTERIA_ONLY.txt",   "⚡ Hysteria2",               "hysteria",  by_proto.get("hysteria", 0)),
        ("SS_ONLY.txt",         "🔲 Shadowsocks",             "ss",        by_proto.get("ss", 0)),
        ("TOP50.txt",           "🏆 TOP-50 быстрых",          "top",       min(50, total)),
        ("TOP50_RELIABLE.txt",  "🛡 TOP-50 надёжных",         "rel",       min(50, total)),
    ]

    cards_html = ""
    for fname, label, _key, cnt in sub_files:
        if cnt == 0:
            continue
        url = f"{raw_base}/{fname}"
        cards_html += f"""
        <div class="sub-card">
          <div class="sub-label">{label}</div>
          <div class="sub-count">{cnt}</div>
          <button class="copy-btn" onclick="copyUrl(this,'{url}')">📋 Копировать URL</button>
          <div class="sub-url">{url}</div>
        </div>"""

    # ── Строки протоколов ────────────────────────────────────────────────────
    proto_rows = ""
    proto_list = [
        ("VLESS",       "vless",    "#6366f1"),
        ("VMess",       "vmess",    "#f59e0b"),
        ("Trojan",      "trojan",   "#22c55e"),
        ("Hysteria2",   "hysteria", "#ef4444"),
        ("Shadowsocks", "ss",       "#06b6d4"),
        ("Other",       "other",    "#64748b"),
    ]
    for name, key, color in proto_list:
        cnt = by_proto.get(key, 0)
        if cnt == 0:
            continue
        pct = round(cnt / total * 100) if total else 0
        proto_rows += f"""
        <div class="proto-row">
          <span class="proto-name">{name}</span>
          <div class="proto-bar-wrap">
            <div class="proto-bar" style="width:{pct}%;background:{color}"></div>
          </div>
          <span class="proto-pct">{pct}%</span>
          <span class="proto-cnt">{cnt}</span>
        </div>"""

    # ── Топ стран ────────────────────────────────────────────────────────────
    def flag(code):
        code = (code or "").upper().strip()
        if len(code) == 2:
            try:
                return chr(0x1F1E6+ord(code[0])-65)+chr(0x1F1E6+ord(code[1])-65)
            except Exception:
                pass
        return "🌐"

    country_rows = ""
    for i, (cc, cnt) in enumerate(list(countries.items())[:12], 1):
        pct = round(cnt / total * 100) if total else 0
        country_rows += f"""
        <tr>
          <td class="rank">#{i}</td>
          <td>{flag(cc)} {cc}</td>
          <td><div class="mini-bar"><div style="width:{pct}%"></div></div></td>
          <td class="cnt-td">{cnt}</td>
        </tr>"""

    # ── Читаем историю если есть ─────────────────────────────────────────────
    history_block = ""
    hist_file = OUTPUT_DIR / "server_history.json"
    if hist_file.exists():
        try:
            hist = json.loads(hist_file.read_text(encoding="utf-8"))
            total_known = len(hist)
            rated = [h for h in hist.values()
                     if len(h.get("checks",[])) >= 3]
            if rated:
                scores = [
                    sum(1 for c in h["checks"] if c["ok"]) / len(h["checks"])
                    for h in rated
                ]
                avg_rel  = round(sum(scores)/len(scores)*100)
                reliable = sum(1 for s in scores if s >= 0.7)
                history_block = f"""
        <div class="hist-row">
          <span>Серверов в базе</span><strong>{total_known}</strong>
        </div>
        <div class="hist-row">
          <span>Оценено (≥3 проверок)</span><strong>{len(rated)}</strong>
        </div>
        <div class="hist-row">
          <span>Средний uptime</span><strong>{avg_rel}%</strong>
        </div>
        <div class="hist-row">
          <span>Надёжных (uptime ≥70%)</span>
          <strong style="color:var(--green)">{reliable}</strong>
        </div>"""
        except Exception:
            pass

    # ── Инструкция ──────────────────────────────────────────────────────────
    main_url = f"{raw_base}/VLESS_WORKING.txt"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>VPN Collector — Статистика</title>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    :root{{
      --bg:#0f1117;--card:#1a1d27;--card2:#1e2235;--card3:#252a3d;
      --text:#e2e8f0;--muted:#8892a4;--accent:#6366f1;--accent2:#a78bfa;
      --green:#22c55e;--amber:#f59e0b;--red:#ef4444;--cyan:#06b6d4;
      --border:rgba(255,255,255,.06);--radius:14px;
    }}
    body{{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;
         min-height:100vh;padding:2rem 1rem;line-height:1.5}}
    .wrap{{max-width:900px;margin:0 auto}}

    /* Шапка */
    header{{text-align:center;margin-bottom:2.5rem}}
    header h1{{font-size:2rem;font-weight:700;
               background:linear-gradient(90deg,var(--accent),var(--accent2));
               -webkit-background-clip:text;-webkit-text-fill-color:transparent}}
    header p{{color:var(--muted);margin-top:.4rem}}
    .badge{{display:inline-block;background:var(--card2);border:1px solid var(--border);
            border-radius:20px;padding:.25rem .9rem;font-size:.8rem;color:var(--muted);margin-top:.6rem}}

    /* Сетка карточек */
    .grid{{display:grid;gap:1rem;margin-bottom:1.5rem}}
    .grid-3{{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}}
    .grid-2{{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}}

    /* Карточка-цифра */
    .stat-card{{background:var(--card);border:1px solid var(--border);
               border-radius:var(--radius);padding:1.2rem 1.4rem}}
    .stat-card .val{{font-size:2.2rem;font-weight:700;color:var(--accent)}}
    .stat-card .lbl{{font-size:.8rem;color:var(--muted);margin-top:.3rem}}
    .stat-card.green .val{{color:var(--green)}}
    .stat-card.amber .val{{color:var(--amber)}}
    .stat-card.cyan  .val{{color:var(--cyan)}}

    /* Панели */
    .panel{{background:var(--card);border:1px solid var(--border);
            border-radius:var(--radius);padding:1.4rem;margin-bottom:1.5rem}}
    .panel h2{{font-size:1rem;font-weight:600;margin-bottom:1rem;
               display:flex;align-items:center;gap:.5rem}}

    /* Протоколы */
    .proto-row{{display:flex;align-items:center;gap:.75rem;margin-bottom:.6rem;font-size:.9rem}}
    .proto-name{{width:100px;flex-shrink:0;color:var(--muted)}}
    .proto-bar-wrap{{flex:1;background:var(--card3);border-radius:99px;height:8px;overflow:hidden}}
    .proto-bar{{height:100%;border-radius:99px;min-width:4px;transition:width .5s}}
    .proto-pct{{width:36px;text-align:right;color:var(--muted);font-size:.82rem}}
    .proto-cnt{{width:40px;text-align:right;font-weight:600;font-size:.88rem}}

    /* Задержка */
    .lat-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:.7rem}}
    .lat-item{{background:var(--card3);border-radius:10px;padding:.8rem;text-align:center}}
    .lat-item .lv{{font-size:1.4rem;font-weight:700;color:var(--amber)}}
    .lat-item .ll{{font-size:.72rem;color:var(--muted);margin-top:.2rem}}

    /* Таблица стран */
    table{{width:100%;border-collapse:collapse;font-size:.88rem}}
    td{{padding:.45rem .5rem;border-bottom:1px solid var(--border)}}
    .rank{{color:var(--muted);width:32px}}
    .cnt-td{{text-align:right;font-weight:600;color:var(--accent)}}
    .mini-bar{{background:var(--card3);border-radius:99px;height:6px;overflow:hidden;width:100px}}
    .mini-bar div{{height:100%;background:var(--green);border-radius:99px;min-width:3px}}

    /* Карточки подписок */
    .subs-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:.9rem}}
    .sub-card{{background:var(--card2);border:1px solid var(--border);
              border-radius:12px;padding:1rem;display:flex;flex-direction:column;gap:.5rem}}
    .sub-label{{font-size:.9rem;font-weight:500}}
    .sub-count{{font-size:1.7rem;font-weight:700;color:var(--accent)}}
    .copy-btn{{background:var(--accent);color:#fff;border:none;border-radius:8px;
              padding:.45rem .8rem;font-size:.82rem;cursor:pointer;transition:opacity .15s;
              text-align:center}}
    .copy-btn:hover{{opacity:.85}}
    .copy-btn.ok{{background:var(--green)}}
    .sub-url{{font-size:.7rem;color:var(--muted);word-break:break-all;
             font-family:monospace;max-height:2.8em;overflow:hidden}}

    /* История */
    .hist-row{{display:flex;justify-content:space-between;padding:.4rem 0;
              border-bottom:1px solid var(--border);font-size:.9rem}}
    .hist-row:last-child{{border:none}}
    .hist-row span{{color:var(--muted)}}

    /* Инструкция */
    .howto{{background:linear-gradient(135deg,#1e2235,#252a3d);
            border:1px solid var(--border);border-radius:var(--radius);
            padding:1.4rem;margin-bottom:1.5rem}}
    .howto h2{{font-size:1rem;font-weight:600;margin-bottom:.9rem}}
    .step{{display:flex;gap:.75rem;margin-bottom:.7rem;font-size:.88rem}}
    .step-num{{background:var(--accent);color:#fff;border-radius:50%;
              width:22px;height:22px;display:flex;align-items:center;justify-content:center;
              font-size:.75rem;font-weight:700;flex-shrink:0;margin-top:.05rem}}
    .code-box{{background:var(--bg);border:1px solid var(--border);border-radius:8px;
              padding:.5rem .8rem;font-family:monospace;font-size:.78rem;color:var(--accent2);
              word-break:break-all;margin-top:.4rem;cursor:pointer}}
    .code-box:hover{{border-color:var(--accent)}}

    footer{{text-align:center;color:var(--muted);font-size:.8rem;margin-top:2.5rem}}
    a{{color:var(--accent);text-decoration:none}}
    a:hover{{text-decoration:underline}}
    @media(max-width:480px){{
      header h1{{font-size:1.6rem}}
      .stat-card .val{{font-size:1.7rem}}
    }}
  </style>
</head>
<body>
<div class="wrap">

  <header>
    <h1>🔄 VPN Collector</h1>
    <p>Автоматически собирает, тестирует и обновляет рабочие серверы каждый час</p>
    <span class="badge">🕐 Обновлено: {updated} MSK</span>
  </header>

  <!-- Главные цифры -->
  <div class="grid grid-3">
    <div class="stat-card green">
      <div class="val">{total}</div>
      <div class="lbl">Рабочих серверов</div>
    </div>
    <div class="stat-card cyan">
      <div class="val">{tls_ok}</div>
      <div class="lbl">TLS подтверждено 🔒</div>
    </div>
    <div class="stat-card amber">
      <div class="val">{tls_pct}%</div>
      <div class="lbl">Доля TLS-серверов</div>
    </div>
    <div class="stat-card">
      <div class="val">{latency.get('min_ms',0)}<small style="font-size:1rem">мс</small></div>
      <div class="lbl">Минимальная задержка</div>
    </div>
    <div class="stat-card amber">
      <div class="val">{latency.get('avg_ms',0)}<small style="font-size:1rem">мс</small></div>
      <div class="lbl">Средняя задержка</div>
    </div>
    <div class="stat-card">
      <div class="val">{latency.get('p50_ms',0)}<small style="font-size:1rem">мс</small></div>
      <div class="lbl">Медиана (p50)</div>
    </div>
  </div>

  <div class="grid grid-2">

    <!-- Протоколы -->
    <div class="panel">
      <h2>📡 По протоколам</h2>
      {proto_rows}
    </div>

    <!-- История надёжности -->
    <div class="panel">
      <h2>📝 История надёжности</h2>
      {history_block if history_block else
        '<p style="color:var(--muted);font-size:.88rem">Накапливается после нескольких запусков.<br>⭐⭐⭐⭐⭐ — сервер работал стабильно.<br>🆕 — новый сервер, данных пока нет.</p>'}
    </div>

  </div>

  <!-- Задержки -->
  <div class="panel">
    <h2>⏱ Задержка серверов (мс)</h2>
    <div class="lat-grid">
      <div class="lat-item"><div class="lv">{latency.get('min_ms',0)}</div><div class="ll">MIN</div></div>
      <div class="lat-item"><div class="lv">{latency.get('avg_ms',0)}</div><div class="ll">AVG</div></div>
      <div class="lat-item"><div class="lv">{latency.get('p50_ms',0)}</div><div class="ll">P50</div></div>
      <div class="lat-item"><div class="lv">{latency.get('p90_ms',0)}</div><div class="ll">P90</div></div>
      <div class="lat-item"><div class="lv">{latency.get('max_ms',0)}</div><div class="ll">MAX</div></div>
    </div>
  </div>

  <!-- Страны -->
  <div class="panel">
    <h2>🌍 Топ стран</h2>
    <table><tbody>{country_rows}</tbody></table>
  </div>

  <!-- Инструкция -->
  <div class="howto">
    <h2>📲 Как добавить подписку в Karing / Hiddify / v2rayN</h2>
    <div class="step">
      <div class="step-num">1</div>
      <div>Скопируй URL нужного файла (кнопки ниже)</div>
    </div>
    <div class="step">
      <div class="step-num">2</div>
      <div>Открой приложение → «Добавить профиль» → вставь URL</div>
    </div>
    <div class="step">
      <div class="step-num">3</div>
      <div>Дай название → сохрани → подключайся</div>
    </div>
    <p style="margin-top:.7rem;font-size:.85rem;color:var(--muted)">
      Для большинства случаев достаточно файла <strong>VLESS_WORKING.txt</strong>.
      Если нужна максимальная надёжность — используй <strong>TOP50_RELIABLE.txt</strong>.
    </p>
    <div class="code-box" onclick="copyText(this,'{main_url}')">{main_url}</div>
  </div>

  <!-- Подписки -->
  <div class="panel">
    <h2>📥 Все файлы подписок</h2>
    <div class="subs-grid">
      {cards_html}
    </div>
  </div>

  <footer>
    Обновляется каждый час автоматически через GitHub Actions •
    Все серверы проходят TCP + TLS проверку •
    <a href="https://github.com/{raw_base.split('githubusercontent.com/')[1].split('/main')[0] if 'githubusercontent' in raw_base else '#'}">GitHub</a>
  </footer>

</div>
<script>
function copyUrl(btn, url) {{
  navigator.clipboard.writeText(url).then(() => {{
    btn.textContent = '✅ Скопировано!';
    btn.classList.add('ok');
    setTimeout(() => {{ btn.textContent = '📋 Копировать URL'; btn.classList.remove('ok'); }}, 2000);
  }});
}}
function copyText(el, text) {{
  navigator.clipboard.writeText(text).then(() => {{
    const orig = el.textContent;
    el.textContent = '✅ Скопировано!';
    setTimeout(() => el.textContent = orig, 2000);
  }});
}}
// Авто-обновление страницы каждые 5 минут
setTimeout(() => location.reload(), 5 * 60 * 1000);
</script>
</body>
</html>"""

    path = OUTPUT_DIR / "index.html"
    path.write_text(html, encoding="utf-8")
    log.info("  💾 %-26s записан", "index.html")
