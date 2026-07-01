# -*- coding: utf-8 -*-
"""
Разовый скрипт: показывает воронки и этапы твоего amoCRM,
чтобы узнать ID воронки и ID этапа для создания сделок.

Запуск (Windows, в командной строке в папке бота):
    set AMO_SUBDOMAIN=archimarakesh
    set AMO_TOKEN=твой_долгосрочный_токен
    python get_pipelines.py

Скрипт НЕ хранит токен — берёт из переменной окружения.
После того как увидишь нужную воронку/этап, скажи их ID — впишем в бота.
"""
import os
import requests

SUBDOMAIN = os.getenv("AMO_SUBDOMAIN", "archimarakesh")
TOKEN = os.getenv("AMO_TOKEN", "")

if not TOKEN:
    print("Не задан AMO_TOKEN. Выполни:  set AMO_TOKEN=твой_токен  и запусти снова.")
    raise SystemExit(1)

BASE = f"https://{SUBDOMAIN}.amocrm.ru/api/v4"
headers = {"Authorization": f"Bearer {TOKEN}"}

# Воронки и этапы
r = requests.get(f"{BASE}/leads/pipelines", headers=headers, timeout=30)
if r.status_code != 200:
    print("Ошибка запроса:", r.status_code)
    print(r.text[:500])
    raise SystemExit(1)

data = r.json()
pipelines = data.get("_embedded", {}).get("pipelines", [])

print("=" * 60)
print("ВОРОНКИ И ЭТАПЫ ТВОЕГО amoCRM")
print("=" * 60)
for p in pipelines:
    print(f"\nВоронка: «{p['name']}»  (ID воронки = {p['id']})")
    statuses = p.get("_embedded", {}).get("statuses", [])
    for s in statuses:
        print(f"    этап: «{s['name']}»  (ID этапа = {s['id']})")

print("\n" + "=" * 60)
print("Скажи мне ID воронки и ID первого этапа (например «Неразобранное»),")
print("куда должны падать заявки от бота — впишу их в бота.")
print("=" * 60)
