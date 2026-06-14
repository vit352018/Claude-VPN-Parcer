import asyncio
import os
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ================= НАСТРОЙКИ =================
TELEGRAM_TOKEN = os.getenv("TG_BOT_TOKENR")
GITHUB_TOKEN = os.getenv("GH_PAT")

REPO_OWNER = "vit352018"              # ←←← ИЗМЕНИ НА СВОЙ GitHub username
REPO_NAME = "Claude-VPN-Parcer"    # ←←← ИЗМЕНИ НА ТОЧНОЕ имя репозитория
WORKFLOW_FILE = "collect.yml"             # ←←← Если workflow называется иначе — измени

# ============================================

async def trigger_workflow():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
    }
    data = {"ref": "main"}

    try:
        response = requests.post(url, headers=headers, json=data, timeout=15)
        if response.status_code == 204:
            print(f"[{datetime.now()}] ✅ Workflow успешно запущен")
            return True
        else:
            print(f"❌ Ошибка {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"Ошибка: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот запущен!\n\n"
        "Команды:\n"
        "/run — запустить сборщик вручную\n"
        "/status — проверить статус"
    )

async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Запускаю сборщик серверов...")
    success = await trigger_workflow()
    if success:
        await update.message.reply_text("✅ Сборщик успешно запущен!")
    else:
        await update.message.reply_text("❌ Не удалось запустить. Проверь токены.")

async def scheduled_run(context: ContextTypes.DEFAULT_TYPE):
    print(f"[{datetime.now()}] Автозапуск по расписанию...")
    await trigger_workflow()

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("run", run_command))

    # Автозапуск каждые 15 минут
    app.job_queue.run_repeating(scheduled_run, interval=900, first=10)

    print(f"[{datetime.now()}] Бот успешно запущен и работает...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
