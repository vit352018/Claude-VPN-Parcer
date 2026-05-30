# 🔄 VLESS Collector

Автоматически собирает, тестирует и обновляет рабочие VPN-конфиги каждый час через **GitHub Actions** — бесплатно, без сервера.

## Как работает

```
Каждый час GitHub Actions:
  1. Скачивает конфиги из 10+ GitHub-репозиториев
  2. Парсит публичные Telegram-каналы
  3. Дедуплицирует (убирает дубли)
  4. Тестирует TCP-доступность каждого сервера
  5. Сортирует по задержке (лучшие — первыми)
  6. Сохраняет в output/VLESS_WORKING.txt
  7. Делает git commit → файл обновляется в репозитории
```

## Быстрый старт

### 1. Fork этого репозитория

Нажми **Fork** в правом верхнем углу → создастся копия у тебя.

### 2. Включить Actions

Перейди во вкладку **Actions** → нажми **"I understand my workflows, enable them"**.

### 3. Первый запуск вручную

**Actions** → **"Collect & Test VPN Configs"** → **Run workflow** → **Run workflow** (зелёная кнопка).

Дождись выполнения (~10–15 минут). После этого в папке `output/` появится файл `VLESS_WORKING.txt`.

### 4. Добавить подписку в Karing / Hiddify / v2rayN

Ссылка на твой файл подписки:
```
https://raw.githubusercontent.com/YOUR_USERNAME/vless-collector/main/output/VLESS_WORKING.txt
```

Замени `YOUR_USERNAME` на своё имя пользователя GitHub.

---

## Структура проекта

```
vless-collector/
├── .github/
│   └── workflows/
│       └── collect.yml        # GitHub Actions — запуск каждый час
├── src/
│   ├── main.py                # Точка входа
│   ├── collector.py           # Сбор из GitHub + TCP-тест
│   └── tg_scraper.py          # Парсинг Telegram-каналов
├── output/
│   └── VLESS_WORKING.txt      # Результат (обновляется автоматически)
├── requirements.txt
└── README.md
```

---

## Настройка

### Добавить/убрать источники

Отредактируй список `SOURCES` в `src/collector.py`:

```python
SOURCES = [
    {
        "name": "Мой источник",
        "url": "https://raw.githubusercontent.com/.../configs.txt",
        "type": "raw",   # или "base64"
    },
    ...
]
```

### Добавить Telegram-каналы

Отредактируй список `PUBLIC_CHANNELS` в `src/tg_scraper.py`:

```python
PUBLIC_CHANNELS = [
    "имя_канала",   # без @
    ...
]
```

### Изменить частоту обновления

В `.github/workflows/collect.yml`:

```yaml
schedule:
  - cron: "0 * * * *"    # каждый час (по умолчанию)
  - cron: "*/30 * * * *" # каждые 30 минут
  - cron: "0 */2 * * *"  # каждые 2 часа
```

### Параметры тестирования

В `src/collector.py`:

```python
TCP_TIMEOUT  = 5.0   # секунд на TCP-проверку
MAX_WORKERS  = 80    # параллельных проверок
MAX_LATENCY  = 4000  # мс — порог «рабочий/нерабочий»
```

---

## Формат выходного файла

```
# profile-title: ✅ Working Servers | Auto-collected | 2026-05-29 18:00 MSK
# profile-update-interval: 1
# Date/Time: 2026-05-29 / 18:00 (Moscow)
# Количество: 87

vless://uuid@host:443?security=reality&...#🇩🇪 Germany | 142ms
vless://uuid@host:443?security=tls&...#🇫🇮 Finland | 198ms
vmess://base64...#🇳🇱 Netherlands | 231ms
```

Полностью совместим с Karing, Hiddify, v2rayN, Clash Verge Rev, NekoBox.

---

## Ограничения

- **TCP-тест ≠ полная проверка туннеля.** Тест проверяет, что порт открыт и сервер отвечает. Он не гарантирует, что сервер реально пробивает блокировки — для этого нужен запущенный VPN-клиент.
- GitHub Actions бесплатен для публичных репозиториев (2000 минут/месяц для приватных).
- Telegram-парсер работает только с **публичными** каналами через веб-интерфейс.

---

## Локальный запуск

```bash
git clone https://github.com/YOUR_USERNAME/vless-collector
cd vless-collector
pip install -r requirements.txt
python src/main.py
```

Результат появится в `output/VLESS_WORKING.txt`.
