import requests
import time
import os
from datetime import datetime

# ================= НАСТРОЙКИ =================
GITHUB_TOKEN = os.getenv("GH_PAT")
REPO_OWNER = "vit352018"           # ← измени
REPO_NAME = "Claude-VPN-Parcer" # ← измени
WORKFLOW_FILE = "collect.yml"          # имя твоего workflow файла

def trigger_workflow():
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {"ref": "main"}

    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code == 204:
        print(f"[{datetime.now()}] ✅ Workflow успешно запущен")
        return True
    else:
        print(f"[{datetime.now()}] ❌ Ошибка {response.status_code}: {response.text}")
        return False

if __name__ == "__main__":
    print("Запуск Runner...")
    while True:
        trigger_workflow()
        time.sleep(900)  # 900 секунд = 15 минут
