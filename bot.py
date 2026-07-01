# -*- coding: utf-8 -*-
"""
Telegram-бот БытСтрой Сервис — приём заявок на бытовки.
Сценарий:
  /start → приветствие → сбор контактов (имя, телефон)
  → 2 кнопки: «Выбрать конфигурацию» и «Нужна консультация»
     • Консультация  → создаётся сделка в amoCRM
     • Конфигурация → опрос (использование, планировка, размер, срок)
                      → создаётся сделка в amoCRM
Заявки уходят ТОЛЬКО в amoCRM (создаётся сделка + контакт,
конфигурация — в примечании к сделке).
Технологии: aiogram 3 + amoCRM API v4 (долгосрочный токен).
Настройки — в переменных окружения (Railway → Variables).
"""
import os
import time
import asyncio
import logging

import aiohttp

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)

logging.basicConfig(level=logging.INFO)

# ──────────────────────────────────────────────────────────────
#  Настройки (Railway → Variables)
# ──────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# amoCRM
AMO_SUBDOMAIN = os.getenv("AMO_SUBDOMAIN", "archimarakesh")   # archimarakesh.amocrm.ru
AMO_TOKEN = os.getenv("AMO_TOKEN", "")                         # долгосрочный токен
AMO_PIPELINE_ID = os.getenv("AMO_PIPELINE_ID", "")            # ID воронки (число)
AMO_STATUS_ID = os.getenv("AMO_STATUS_ID", "")               # ID этапа (число)
# Контакты для показа клиенту
SHOP_PHONE = os.getenv("SHOP_PHONE", "")

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения (Railway → Variables).")
if not AMO_TOKEN:
    logging.warning("AMO_TOKEN не задан — заявки не будут уходить в amoCRM.")

AMO_BASE = f"https://{AMO_SUBDOMAIN}.amocrm.ru/api/v4"

# ID кастомных полей СДЕЛКИ в amoCRM (archimarakesh)
FIELD_DATE = 1855671        # Дата заказа (тип date — unix timestamp)
FIELD_SOURCE = 1857195      # Источник (text)
FIELD_PURPOSE = 1857199     # Назначение (text)
FIELD_LAYOUT = 1857201      # Планировка (text)
FIELD_SIZE = 1857203        # Размер (text)
FIELD_INSTALL = 1857205     # Установка (text)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ──────────────────────────────────────────────────────────────
#  Состояния диалога (FSM)
# ──────────────────────────────────────────────────────────────
class Form(StatesGroup):
    name = State()          # ждём имя
    phone = State()         # ждём телефон
    menu = State()          # показали 2 кнопки
    use = State()           # как использовать
    layout = State()        # планировка
    size = State()          # размер
    term = State()          # срок установки


# ──────────────────────────────────────────────────────────────
#  Варианты ответов (кнопки конфигурации)
# ──────────────────────────────────────────────────────────────
USE_OPTIONS = ["Только лето", "Демисезон", "Круглый год", "Для хранения"]
LAYOUT_OPTIONS = ["Стандарт", "С перегородкой", "Распашонка",
                  "С крыльцом", "Душ и туалет", "Индивидуальная"]
SIZE_OPTIONS = ["3×2,4 — 7.2 м²", "4×2,4 — 9.6 м²", "5×2,4 — 12 м²",
                "6×2,4 — 14.4 м²", "7×2,4 — 16.8 м²", "8×2,4 — 19.2 м²",
                "Индивидуальный размер"]
TERM_OPTIONS = ["В течении 2-3 недель", "В течении месяца",
                "Через 1-3 месяца", "Пока просто смотрю"]


def kb_from(options, prefix):
    """Строит inline-клавиатуру из списка: по 1-2 в ряд, callback = prefix|индекс."""
    rows, row = [], []
    for i, opt in enumerate(options):
        row.append(InlineKeyboardButton(text=opt, callback_data=f"{prefix}|{i}"))
        # длинные варианты — по одному в ряд, короткие — по два
        if len(opt) > 18 or len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ──────────────────────────────────────────────────────────────
#  /start → приветствие и запрос имени
# ──────────────────────────────────────────────────────────────
@dp.message(F.text == "/fields")
async def cmd_fields(message: Message):
    """Показывает кастомные поля СДЕЛОК с их ID (для настройки записи в поля)."""
    if not AMO_TOKEN:
        await message.answer("AMO_TOKEN не задан.")
        return
    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"{AMO_BASE}/leads/custom_fields?limit=250",
                                headers=headers, timeout=30) as r:
                if r.status != 200:
                    await message.answer(f"Ошибка amoCRM: {r.status}")
                    return
                data = await r.json()
    except Exception as e:
        await message.answer(f"Ошибка запроса: {e}")
        return

    fields = data.get("_embedded", {}).get("custom_fields", [])
    if not fields:
        await message.answer("Кастомных полей сделки не найдено. Сначала создай их в amoCRM.")
        return
    lines = []
    for f in fields:
        lines.append(f"• «{f['name']}» — ID <b>{f['id']}</b> (тип: {f['type']})")
        # для списков покажем варианты с их ID
        for en in (f.get("enums") or []):
            lines.append(f"      – {en['value']} → enum_id {en['id']}")
    # разбиваем на части, если длинно
    text = "Поля сделки:\n" + "\n".join(lines)
    for i in range(0, len(text), 3500):
        await message.answer(text[i:i+3500])


@dp.message(F.text == "/pipelines")
async def cmd_pipelines(message: Message):
    """Показывает воронки и этапы с их ID (чтобы узнать ID нужного этапа)."""
    if not AMO_TOKEN:
        await message.answer("AMO_TOKEN не задан.")
        return
    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"{AMO_BASE}/leads/pipelines",
                                headers=headers, timeout=30) as r:
                if r.status != 200:
                    await message.answer(f"Ошибка amoCRM: {r.status}")
                    return
                data = await r.json()
    except Exception as e:
        await message.answer(f"Ошибка запроса: {e}")
        return

    pipelines = data.get("_embedded", {}).get("pipelines", [])
    lines = []
    for p in pipelines:
        lines.append(f"\n🔹 Воронка «{p['name']}» — ID {p['id']}")
        for s in p.get("_embedded", {}).get("statuses", []):
            lines.append(f"    • «{s['name']}» — ID этапа <b>{s['id']}</b>")
    await message.answer(
        "Воронки и этапы:\n" + "\n".join(lines) +
        "\n\nВпиши ID нужного этапа в переменную AMO_STATUS_ID на Railway."
        if lines else "Воронки не найдены."
    )


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здравствуйте! 👋\n\n"
        "Вы обратились в <b>БытСтрой Сервис</b> — производство и продажа бытовок.\n\n"
        "Чтобы подобрать вариант и рассчитать стоимость, давайте познакомимся.\n\n"
        "<b>Как вас зовут?</b>",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Form.name)


@dp.message(Form.name, F.text)
async def got_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    # просим телефон — кнопкой «поделиться контактом» или ввод вручную
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    await message.answer(
        f"Приятно познакомиться, {message.text.strip()}!\n\n"
        "<b>Оставьте номер телефона</b> — нажмите кнопку ниже или впишите вручную.",
        reply_markup=kb,
    )
    await state.set_state(Form.phone)


@dp.message(Form.phone, F.contact)
async def got_phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await show_menu(message, state)


@dp.message(Form.phone, F.text)
async def got_phone_text(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await show_menu(message, state)


# ──────────────────────────────────────────────────────────────
#  Меню: 2 кнопки
# ──────────────────────────────────────────────────────────────
async def show_menu(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏗 Выбрать конфигурацию", callback_data="menu|config")],
        [InlineKeyboardButton(text="💬 Нужна консультация", callback_data="menu|consult")],
    ])
    await message.answer(
        "Спасибо! Данные записал.\n\nЧто вас интересует?",
        reply_markup=kb,
    )
    await state.set_state(Form.menu)


@dp.callback_query(Form.menu, F.data == "menu|consult")
async def choose_consult(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup(reply_markup=None)
    await state.update_data(kind="Консультация")
    await send_lead(cb.message, state, consult=True)
    await cb.answer()


@dp.callback_query(Form.menu, F.data == "menu|config")
async def choose_config(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup(reply_markup=None)
    await state.update_data(kind="Конфигурация")
    await cb.message.answer(
        "<b>Как планируете использовать бытовку?</b>",
        reply_markup=kb_from(USE_OPTIONS, "use"),
    )
    await state.set_state(Form.use)
    await cb.answer()


# ── Опрос конфигурации ──
@dp.callback_query(Form.use, F.data.startswith("use|"))
async def q_use(cb: CallbackQuery, state: FSMContext):
    idx = int(cb.data.split("|")[1])
    await state.update_data(use=USE_OPTIONS[idx])
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        "<b>Какую планировку хотите?</b>",
        reply_markup=kb_from(LAYOUT_OPTIONS, "layout"),
    )
    await state.set_state(Form.layout)
    await cb.answer()


@dp.callback_query(Form.layout, F.data.startswith("layout|"))
async def q_layout(cb: CallbackQuery, state: FSMContext):
    idx = int(cb.data.split("|")[1])
    await state.update_data(layout=LAYOUT_OPTIONS[idx])
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        "<b>Какой нужен размер?</b>",
        reply_markup=kb_from(SIZE_OPTIONS, "size"),
    )
    await state.set_state(Form.size)
    await cb.answer()


@dp.callback_query(Form.size, F.data.startswith("size|"))
async def q_size(cb: CallbackQuery, state: FSMContext):
    idx = int(cb.data.split("|")[1])
    await state.update_data(size=SIZE_OPTIONS[idx])
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(
        "<b>Когда планируете установку?</b>",
        reply_markup=kb_from(TERM_OPTIONS, "term"),
    )
    await state.set_state(Form.term)
    await cb.answer()


@dp.callback_query(Form.term, F.data.startswith("term|"))
async def q_term(cb: CallbackQuery, state: FSMContext):
    idx = int(cb.data.split("|")[1])
    await state.update_data(term=TERM_OPTIONS[idx])
    await cb.message.edit_reply_markup(reply_markup=None)
    await send_lead(cb.message, state, consult=False)
    await cb.answer()


# ──────────────────────────────────────────────────────────────
#  Отправка заявки менеджеру (+ задел под CRM)
# ──────────────────────────────────────────────────────────────
async def send_lead(message: Message, state: FSMContext, consult: bool):
    data = await state.get_data()
    name = data.get("name", "—")
    phone = data.get("phone", "—")

    # Поля сделки: Дата заказа (сейчас), Источник — всегда.
    fields = {
        FIELD_DATE: int(time.time()),          # date-поле amoCRM = unix timestamp
        FIELD_SOURCE: "Бот Телеграмм",
    }

    if consult:
        title = f"Заявка (консультация) — {name}"
        # для консультации конфигурации нет — поля назначения и т.д. не заполняем
    else:
        title = f"Заявка (конфигурация) — {name}"
        fields[FIELD_PURPOSE] = data.get("use", "")
        fields[FIELD_LAYOUT] = data.get("layout", "")
        fields[FIELD_SIZE] = data.get("size", "")
        fields[FIELD_INSTALL] = data.get("term", "")

    ok = await create_amo_lead(title=title, name=name, phone=phone, fields=fields)

    if ok:
        contact_line = f"\n\n📞 Наш телефон: {SHOP_PHONE}" if SHOP_PHONE else ""
        await message.answer(
            "Спасибо! ✅\n\n"
            "Ваша заявка принята — менеджер свяжется с вами в ближайшее время."
            f"{contact_line}\n\n"
            "Чтобы оставить новую заявку — нажмите /start",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer(
            "Спасибо! Заявку записал.\n\n"
            "Если в течение дня с вами не свяжутся — напишите нам ещё раз.\n"
            "Новая заявка — /start",
            reply_markup=ReplyKeyboardRemove(),
        )
    await state.clear()


async def create_amo_lead(title: str, name: str, phone: str, fields: dict) -> bool:
    """
    Создаёт сделку в amoCRM через API v4 (метод «сложное добавление»):
    сделка + контакт с телефоном + кастомные поля сделки одним запросом.
    fields: {field_id: value}. Возвращает True при успехе.
    """
    if not AMO_TOKEN:
        logging.error("amoCRM: нет AMO_TOKEN — заявка не отправлена.")
        return False

    headers = {
        "Authorization": f"Bearer {AMO_TOKEN}",
        "Content-Type": "application/json",
    }

    # Сделка с встроенным контактом (complex create)
    lead = {"name": title}
    if AMO_PIPELINE_ID:
        try:
            lead["pipeline_id"] = int(AMO_PIPELINE_ID)
        except ValueError:
            pass
    if AMO_STATUS_ID:
        try:
            lead["status_id"] = int(AMO_STATUS_ID)
        except ValueError:
            pass

    # Кастомные поля сделки (Дата заказа, Источник, Назначение, Планировка, Размер, Установка)
    cfv = []
    for fid, val in fields.items():
        if val is None or val == "":
            continue
        cfv.append({"field_id": int(fid), "values": [{"value": val}]})
    if cfv:
        lead["custom_fields_values"] = cfv

    # Контакт с телефоном (поле PHONE — стандартное, code=PHONE)
    contact_embedded = {
        "name": name,
        "custom_fields_values": [
            {
                "field_code": "PHONE",
                "values": [{"value": phone, "enum_code": "WORK"}],
            }
        ],
    }
    lead["_embedded"] = {"contacts": [contact_embedded]}

    payload = [lead]  # API v4 ждёт массив сделок

    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(f"{AMO_BASE}/leads/complex",
                                 headers=headers, json=payload, timeout=30) as r:
                text = await r.text()
                if r.status not in (200, 201):
                    logging.error("amoCRM leads/complex %s: %s", r.status, text[:400])
                    return False
            return True
    except Exception as e:
        logging.error("amoCRM ошибка: %s", e)
        return False


# ──────────────────────────────────────────────────────────────
#  Запуск
# ──────────────────────────────────────────────────────────────
async def main():
    logging.info("БытСтрой Сервис бот запущен.")
    # Сбрасываем webhook (если был установлен ранее) — иначе polling
    # конфликтует: "can't use getUpdates while webhook is active".
    # drop_pending_updates=True — не тащим накопившиеся старые апдейты.
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
