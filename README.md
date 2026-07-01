# Telegram-бот БытСтрой Сервис → amoCRM

Приём заявок на бытовки: приветствие → контакты → 2 кнопки
(«Выбрать конфигурацию» / «Нужна консультация») → **сделка в amoCRM**.

## Шаг 1. Узнать ID воронки и этапа (разово)

В командной строке в этой папке:
```
set AMO_SUBDOMAIN=archimarakesh
set AMO_TOKEN=твой_долгосрочный_токен
python get_pipelines.py
```
Скрипт покажет твои воронки и этапы с их ID. Запиши:
- ID воронки (куда падают заявки)
- ID первого этапа (напр. «Неразобранное»)

## Шаг 2. Создать Telegram-бота

@BotFather → /newbot → получи **BOT_TOKEN**.

## Шаг 3. Деплой на Railway

1. Залей папку в репозиторий GitHub.
2. Railway → New Project → Deploy from GitHub.
3. В Railway → **Variables** добавь:
   - `BOT_TOKEN` = токен от BotFather
   - `AMO_SUBDOMAIN` = archimarakesh
   - `AMO_TOKEN` = долгосрочный токен amoCRM
   - `AMO_PIPELINE_ID` = ID воронки (из шага 1)
   - `AMO_STATUS_ID` = ID этапа (из шага 1)
   - `SHOP_PHONE` = телефон для клиента (необязательно)
4. Railway соберёт и запустит (Procfile: worker: python bot.py).

## Что делает бот

1. /start → приветствие
2. Спрашивает имя → телефон
3. Две кнопки:
   - «Нужна консультация» → сделка в amoCRM (тип: консультация)
   - «Выбрать конфигурацию» → 4 вопроса (использование, планировка,
     размер, срок) → сделка в amoCRM с конфигурацией в примечании
4. В amoCRM создаётся: сделка + контакт (с телефоном) + примечание
   со всеми данными заявки.

## Безопасность

Токен amoCRM и токен бота хранятся ТОЛЬКО в переменных Railway,
не в коде. Никому не показывай долгосрочный токен — это ключ к твоей CRM.

## Локальная проверка

```
pip install -r requirements.txt
set BOT_TOKEN=...
set AMO_TOKEN=...
set AMO_SUBDOMAIN=archimarakesh
set AMO_PIPELINE_ID=...
set AMO_STATUS_ID=...
python bot.py
```
