# 🔄 VLESS Collector

Бот который каждый час автоматически:
- Собирает бесплатные VPN-серверы из 15+ источников (GitHub + Telegram)
- Проверяет какие реально работают (TCP + TLS тест)
- Сохраняет по файлам — все протоколы, **отдельно для обхода РКН**
- Загружает на **Яндекс Диск** с прямыми ссылками для Karing
- Показывает страницу статистики через GitHub Pages
- Отправляет отчёт в **Telegram**

Работает **бесплатно** на серверах GitHub — твой компьютер не нужен.

---

## 🚀 Быстрый старт

### 1. Создай новый репозиторий

> ⚠️ Именно **новый**, не Fork — в форках расписание не работает!

GitHub → кнопка «+» → **New repository** → название `vless-collector` → **Public** → Create

Загрузи файлы из ZIP:
```bash
git clone https://github.com/ТВО_ИМЯ/vless-collector
cd vless-collector
# скопируй все файлы из ZIP в эту папку
git add .
git commit -m "init"
git push
```

### 2. Включи Actions

Вкладка **Actions** → **"I understand my workflows, enable them"**

### 3. Включи GitHub Pages

**Settings → Pages → Source → GitHub Actions → Save**

### 4. Добавь секреты

**Settings → Secrets and variables → Actions → New repository secret**

| Имя | Значение | Зачем |
|---|---|---|
| `YANDEX_TOKEN` | OAuth-токен | Прямые ссылки для Karing ✅ |
| `TG_BOT_TOKEN` | токен от @BotFather | Уведомления в Telegram |
| `TG_CHAT_ID` | твой числовой ID | Куда слать уведомления |

> `YANDEX_LOGIN` и `YANDEX_PASS` — запасной вариант если нет токена.

### 5. Запусти первый раз вручную

**Actions → "Collect and Test VPN Configs" → Run workflow**

---

## 📥 Как добавить в Karing / Hiddify / v2rayN

```
https://raw.githubusercontent.com/ТВО_ИМЯ/vless-collector/main/output/VLESS_WORKING.txt
https://raw.githubusercontent.com/ТВО_ИМЯ/vless-collector/main/output/RU_BYPASS.txt
```

---

## 📁 Выходные файлы

| Файл | Содержимое |
|---|---|
| `VLESS_WORKING.txt` | Все рабочие серверы |
| `RU_BYPASS.txt` | **🇷🇺 Только для обхода РКН/ТСПУ** (VLESS Reality + XTLS) |
| `VLESS_ONLY.txt` | Только VLESS |
| `VMESS_ONLY.txt` | Только VMess |
| `TROJAN_ONLY.txt` | Только Trojan |
| `HYSTERIA_ONLY.txt` | Только Hysteria2 |
| `TOP50.txt` | Топ-50 самых быстрых |
| `TOP50_RELIABLE.txt` | Топ-50 самых надёжных (по истории) |
| `stats.json` | Статистика в JSON |
| `index.html` | Дашборд (GitHub Pages) |

---

## ☁️ Как получить OAuth-токен для Яндекс Диска

Токен нужен чтобы Karing мог читать файлы напрямую с диска.

1. [oauth.yandex.ru](https://oauth.yandex.ru/) → "Зарегистрировать приложение"
2. Название: `vless-collector`, платформа: "Веб-сервисы"
3. Redirect URI: `https://oauth.yandex.ru/verification_code`
4. Права: "Яндекс Диск" → "Запись в любом месте диска"
5. Создать → скопируй **CLIENT_ID**
6. Открой в браузере (подставь свой CLIENT_ID):
   ```
   https://oauth.yandex.ru/authorize?response_type=token&client_id=ТВОЙ_CLIENT_ID
   ```
7. Разреши → скопируй токен из адресной строки (после `access_token=` до `&`)
8. Добавь как секрет `YANDEX_TOKEN` в GitHub

---

## 💻 Локальный запуск

```bash
pip install -r requirements.txt
cp .env.example .env   # заполни своими данными
python run.py          # полный запуск
python run.py --stats  # статистика
python run.py --upload # загрузить на Яндекс Диск
```

---

## 📂 Структура

```
vless-collector/
├── src/
│   ├── main.py              ← главный файл (10 шагов)
│   ├── collector.py         ← сбор с GitHub + фильтр RU Bypass
│   ├── tg_scraper.py        ← парсинг Telegram-каналов
│   ├── tester.py            ← TCP + TLS тест серверов
│   ├── geoip.py             ← определение страны
│   ├── writer.py            ← запись файлов по протоколам
│   ├── html_gen.py          ← HTML-дашборд
│   ├── yandex_upload.py     ← загрузка на Яндекс Диск (OAuth API)
│   ├── tg_notify.py         ← Telegram-уведомления
│   ├── tg_bot.py            ← Telegram-бот с командами
│   ├── history.py           ← история надёжности серверов
│   └── source_discovery.py  ← автопоиск новых источников
├── .github/workflows/
│   └── collect.yml          ← запуск каждый час + GitHub Pages
├── output/                  ← сюда сохраняются готовые файлы
├── config.py                ← все настройки
├── run.py                   ← локальный запуск
├── requirements.txt
└── .env.example             ← шаблон настроек
```
