# -*- coding: utf-8 -*-
"""
Telegram-бот БытСтрой Сервис — приём заявок на бытовки.
Сценарий:
  /start → приветствие → сбор контактов (имя, телефон)
  → 2 кнопки: «Выбрать конфигурацию» и «Нужна консультация»
     • Консультация  → заявка сразу уходит менеджеру
     • Конфигурация → опрос (использование, планировка, размер, срок)
                      → заявка уходит менеджеру
Технологии: aiogram 3, деплой на Railway (как другие проекты).
Настройки берутся из переменных окружения (Railway → Variables).
"""
import os
import asyncio
import logging

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
# Куда слать заявки: ID менеджера или группы (напр. -1001234567890 для группы).
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID", "")
# Контакты для кнопки «Связаться» / показа клиенту
SHOP_PHONE = os.getenv("SHOP_PHONE", "+7 (000) 000-00-00")
SHOP_TELEGRAM = os.getenv("SHOP_TELEGRAM", "")  # напр. https://t.me/username

if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения (Railway → Variables).")

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

    if consult:
        lead_text = (
            "🔔 <b>Новая заявка — КОНСУЛЬТАЦИЯ</b>\n\n"
            f"👤 Имя: {name}\n"
            f"📱 Телефон: {phone}\n\n"
            "Клиент просит связаться для консультации."
        )
    else:
        lead_text = (
            "🔔 <b>Новая заявка — КОНФИГУРАЦИЯ</b>\n\n"
            f"👤 Имя: {name}\n"
            f"📱 Телефон: {phone}\n\n"
            f"🗓 Использование: {data.get('use', '—')}\n"
            f"📐 Планировка: {data.get('layout', '—')}\n"
            f"📏 Размер: {data.get('size', '—')}\n"
            f"⏱ Срок установки: {data.get('term', '—')}"
        )

    # 1) шлём менеджеру/в группу
    if MANAGER_CHAT_ID:
        try:
            await bot.send_message(int(MANAGER_CHAT_ID), lead_text)
        except Exception as e:
            logging.error("Не удалось отправить заявку менеджеру: %s", e)

    # 2) ЗАДЕЛ ПОД CRM — когда определишься с amo/Битрикс, впиши сюда отправку.
    await send_to_crm(data, consult)

    # 3) подтверждение клиенту
    contact_line = f"\n\n📞 Наш телефон: {SHOP_PHONE}" if SHOP_PHONE else ""
    await message.answer(
        "Спасибо! ✅\n\n"
        "Ваша заявка принята — менеджер свяжется с вами в ближайшее время."
        f"{contact_line}\n\n"
        "Чтобы оставить новую заявку — нажмите /start",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()


async def send_to_crm(data: dict, consult: bool):
    """
    ЗАГЛУШКА под CRM. Когда выберешь amoCRM или Битрикс24 —
    сюда добавим отправку заявки через их вебхук/API.
    Пример для вебхука (псевдокод):
        async with aiohttp.ClientSession() as s:
            await s.post(CRM_WEBHOOK_URL, json={
                "name": data.get("name"), "phone": data.get("phone"), ...
            })
    Пока просто логируем.
    """
    logging.info("CRM (заглушка): %s", data)


# ──────────────────────────────────────────────────────────────
#  Запуск
# ──────────────────────────────────────────────────────────────
async def main():
    logging.info("БытСтрой Сервис бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
