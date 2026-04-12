"""
Telegram Quiz Bot — полная рабочая версия
Python + aiogram 3 + aiosqlite
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent, PollAnswer
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ============================================================
# НАСТРОЙКИ
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8634239927:AAG2KLGHGvGMOkeDQyymMKzKOluUjqaxWxg")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN.")

BOT_USERNAME = "practicaent_bot"
ADMIN_IDS = [5048547918]
MANAGER_LINK = "@historyentk_bot"
CHANNEL_USERNAME = "@historykazakhkz"
CHANNEL_URL = "https://t.me/historykazakhkz"

DB_PATH = "ent_bot.db"
REFERRAL_BONUS_COUNT = 3
REFERRAL_BONUS_DAYS = 7
QUESTION_TIMEOUT = 30

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ============================================================
# СТРУКТУРА АКТИВНОЙ СЕССИИ ТЕСТА
# ============================================================
@dataclass
class QuizSession:
    user_id: int
    chat_id: int
    quiz_id: int
    quiz_title: str
    questions: list
    current_index: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    missed_count: int = 0
    consecutive_missed: int = 0
    wrong_questions: list = field(default_factory=list)
    missed_questions: list = field(default_factory=list)
    current_poll_id: Optional[str] = None
    control_message_id: Optional[int] = None
    active: bool = True
    paused: bool = False
    finished: bool = False
    answer_event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def answered_count(self):
        return self.correct_count + self.wrong_count + self.missed_count

    @property
    def unanswered_remaining(self):
        return len(self.questions) - self.answered_count

    @property
    def percent(self):
        total = self.answered_count
        return round(self.correct_count / total * 100) if total else 0


active_sessions: dict[int, QuizSession] = {}

# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================
class QuizStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_data = State()

class PremiumStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()

class ChannelStates(StatesGroup):
    waiting_for_channel = State()

# ============================================================
# БАЗА ДАННЫХ
# ============================================================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_subscribed INTEGER DEFAULT 0,
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                invited_by INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                data TEXT,
                is_paid INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS results (
                user_id INTEGER,
                quiz_id INTEGER,
                score INTEGER,
                total INTEGER,
                wrong INTEGER DEFAULT 0,
                missed INTEGER DEFAULT 0,
                percent REAL,
                completed_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(user_id, quiz_id)
            );

            CREATE TABLE IF NOT EXISTS referrals (
                inviter_id INTEGER,
                invited_user_id INTEGER PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS subscription_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username TEXT UNIQUE,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscription', 'true')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO subscription_channels (channel_username) VALUES (?)",
            (CHANNEL_USERNAME,)
        )
        await db.commit()

# ============================================================
# ПАРСЕР ТЕСТОВ
# ============================================================
def clean_option(text: str) -> str:
    """Убирает * из варианта ответа."""
    return text.lstrip('*').strip()

def parse_quiz_data(text: str) -> tuple[list, str]:
    """Парсит текст с вопросами. Возвращает (вопросы, ошибка)."""
    questions = []
    blocks = text.strip().split('\n\n')

    for block_num, block in enumerate(blocks, 1):
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3:
            continue

        question_text = lines[0]
        opts = []
        correct_index = None

        for line in lines[1:]:
            is_correct = line.startswith('*')
            cleaned = clean_option(line)
            if not cleaned:
                continue
            if is_correct:
                if correct_index is not None:
                    return [], f"Блок {block_num}: более одного правильного ответа."
                correct_index = len(opts)
            opts.append(cleaned)

        if len(opts) < 2:
            return [], f"Блок {block_num}: минимум 2 варианта ответа."
        if correct_index is None:
            return [], f"Блок {block_num}: нет правильного ответа (поставьте * перед ним)."

        questions.append({"q": question_text, "opts": opts, "correct": correct_index})

    if not questions:
        return [], "Не удалось распознать ни одного вопроса. Проверьте формат."

    return questions, ""

def clean_quiz_data(data: list) -> list:
    """Очищает * из уже сохранённых данных (миграция старых записей)."""
    for q in data:
        q['opts'] = [clean_option(o) for o in q['opts']]
    return data

# ============================================================
# УТИЛИТЫ — ПОЛЬЗОВАТЕЛИ
# ============================================================
async def register_user(user: types.User, invited_by: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,)) as c:
            exists = await c.fetchone()
        if not exists:
            await db.execute(
                "INSERT INTO users (user_id, username, first_name, invited_by) VALUES (?, ?, ?, ?)",
                (user.id, user.username, user.first_name, invited_by)
            )
            if invited_by and invited_by != user.id:
                await db.execute(
                    "INSERT OR IGNORE INTO referrals (inviter_id, invited_user_id) VALUES (?, ?)",
                    (invited_by, user.id)
                )
                async with db.execute(
                    "SELECT COUNT(*) FROM referrals WHERE inviter_id = ?", (invited_by,)
                ) as c2:
                    ref_count = (await c2.fetchone())[0]
                if ref_count > 0 and ref_count % REFERRAL_BONUS_COUNT == 0:
                    await _grant_premium_db(db, invited_by, REFERRAL_BONUS_DAYS)
                    try:
                        await bot.send_message(
                            invited_by,
                            f"🎁 Вы пригласили <b>{ref_count}</b> друзей и получили "
                            f"<b>{REFERRAL_BONUS_DAYS} дней Премиума</b> бесплатно!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
            await db.commit()

async def _grant_premium_db(db, user_id: int, days: int):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    await db.execute(
        "UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?",
        (until, user_id)
    )

async def grant_premium(user_id: int, days: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await _grant_premium_db(db, user_id, days)
        await db.commit()

async def check_premium(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT is_premium, premium_until FROM users WHERE user_id = ?", (user_id,)
        ) as c:
            row = await c.fetchone()
    if not row or not row[0]:
        return False
    if row[1]:
        if datetime.now() > datetime.fromisoformat(row[1]):
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET is_premium = 0 WHERE user_id = ?", (user_id,))
                await db.commit()
            return False
    return True

# ============================================================
# УТИЛИТЫ — КАНАЛЫ И ПОДПИСКА
# ============================================================
async def get_required_channels() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_username FROM subscription_channels") as c:
            return [r[0] for r in await c.fetchall()]

async def is_force_subscription_enabled() -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'force_subscription'") as c:
            row = await c.fetchone()
    return row and row[0].lower() == 'true'

async def check_user_subscriptions(user_id: int) -> tuple[bool, list[str]]:
    """Возвращает (все_подписаны, список_каналов_без_подписки)."""
    channels = await get_required_channels()
    not_subscribed = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status not in ("member", "administrator", "creator"):
                not_subscribed.append(ch)
        except Exception as e:
            logger.warning(f"Не удалось проверить подписку {user_id} на {ch}: {e}")
            not_subscribed.append(ch)
    return len(not_subscribed) == 0, not_subscribed

async def show_subscription_screen(target, channels: list[str]):
    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.row(InlineKeyboardButton(
            text=f"📢 {ch}", url=f"https://t.me/{ch.lstrip('@')}"
        ))
    builder.row(InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription"))
    text = (
        "📢 <b>Для доступа к бесплатным тестам</b> подпишитесь на все каналы ниже, "
        "затем нажмите «✅ Я подписался»."
    )
    if isinstance(target, types.Message):
        await target.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    else:
        await target.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ============================================================
# УТИЛИТЫ — ТЕСТЫ
# ============================================================
async def get_quiz(q_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, data, is_paid FROM quizzes WHERE id = ?", (q_id,)
        ) as c:
            return await c.fetchone()

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📚 Выбрать тест", callback_data="menu_tests"))
    builder.row(InlineKeyboardButton(text="📊 Мои результаты", callback_data="menu_results"))
    builder.row(InlineKeyboardButton(text="👥 Пригласить друзей", callback_data="menu_referral"))
    builder.row(
        InlineKeyboardButton(text="ℹ️ Помощь", callback_data="menu_help"),
        InlineKeyboardButton(
            text="👨‍💼 Менеджер",
            url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
        )
    )
    if is_admin:
        builder.row(InlineKeyboardButton(text="⚙️ Админка", callback_data="admin_panel"))
    return builder.as_markup()

def quiz_control_kb(paused: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if paused:
        builder.row(InlineKeyboardButton(text="▶️ Продолжить", callback_data="quiz_resume"))
        builder.row(InlineKeyboardButton(text="⛔ Завершить тест", callback_data="quiz_finish"))
    else:
        builder.row(
            InlineKeyboardButton(text="⏸ Приостановить", callback_data="quiz_pause"),
            InlineKeyboardButton(text="⛔ Завершить тест", callback_data="quiz_finish")
        )
    return builder.as_markup()

def missed_choice_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="▶️ Продолжить", callback_data="quiz_resume"))
    builder.row(InlineKeyboardButton(text="⛔ Завершить тест", callback_data="quiz_finish"))
    return builder.as_markup()

# ============================================================
# ПОКАЗ ГЛАВНОГО МЕНЮ
# ============================================================
async def show_main_menu(target, user_id: int, edit: bool = False):
    is_admin = user_id in ADMIN_IDS
    text = "🏠 <b>Главное меню</b>\n\nВыберите раздел:"
    kb = main_menu_kb(is_admin)
    if edit and isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    elif isinstance(target, types.Message):
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.message.answer(text, reply_markup=kb, parse_mode="HTML")

# ============================================================
# /start
# ============================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    args = message.text.split()
    invited_by = None

    if len(args) > 1:
        param = args[1]
        if param.startswith("ref_"):
            try:
                invited_by = int(param.split("_")[1])
            except (IndexError, ValueError):
                pass
        elif param.startswith("quiz_"):
            await register_user(message.from_user)
            try:
                q_id = int(param.split("_")[1])
                await launch_quiz(message.chat.id, message.from_user.id, q_id)
            except (IndexError, ValueError):
                pass
            return

    await register_user(message.from_user, invited_by)
    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    await message.answer(
        f"👋 Привет, <b>{name}</b>!\n"
        f"Рад, что ты с нами практикуешься!\n\n"
        f"Здесь ты можешь проходить тесты, тренировать знания и улучшать результаты.\n"
        f"Начни практику прямо сейчас 🚀",
        parse_mode="HTML"
    )

    force = await is_force_subscription_enabled()
    if force:
        channels = await get_required_channels()
        if channels:
            all_ok, not_sub = await check_user_subscriptions(message.from_user.id)
            if not all_ok:
                await show_subscription_screen(message, not_sub)
                return

    await show_main_menu(message, message.from_user.id)

@dp.callback_query(F.data == "to_main")
async def to_main(callback: types.CallbackQuery):
    await show_main_menu(callback, callback.from_user.id, edit=True)

# ============================================================
# ПРОВЕРКА ПОДПИСКИ
# ============================================================
@dp.callback_query(F.data == "check_subscription")
async def check_subscription(callback: types.CallbackQuery):
    all_ok, not_sub = await check_user_subscriptions(callback.from_user.id)
    if all_ok:
        await callback.message.edit_text(
            "✅ <b>Спасибо за подписку!</b>\n\nТеперь вам доступны бесплатные тесты.",
            parse_mode="HTML"
        )
        await show_main_menu(callback, callback.from_user.id)
    else:
        channels_text = "\n".join(f"• {ch}" for ch in not_sub)
        await callback.answer(
            f"Вы ещё не подписаны на:\n{channels_text}\n\nПодпишитесь и нажмите снова.",
            show_alert=True
        )

# ============================================================
# СПИСОК ТЕСТОВ
# ============================================================
@dp.callback_query(F.data == "menu_tests")
async def menu_tests(callback: types.CallbackQuery):
    force = await is_force_subscription_enabled()
    channels = await get_required_channels()
    if force and channels:
        all_ok, not_sub = await check_user_subscriptions(callback.from_user.id)
        if not all_ok:
            await show_subscription_screen(callback, not_sub)
            return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT quiz_id FROM results WHERE user_id = ?", (callback.from_user.id,)
        ) as c:
            done = {r[0] for r in await c.fetchall()}
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            quizzes = await c.fetchall()

    if not quizzes:
        await callback.answer("Тестов пока нет", show_alert=True)
        return

    is_premium = await check_premium(callback.from_user.id)
    builder = InlineKeyboardBuilder()
    for q_id, title, is_paid in quizzes:
        mark = "✅ " if q_id in done else ("🔒 " if is_paid and not is_premium else "📖 ")
        builder.row(InlineKeyboardButton(text=f"{mark}{title}", callback_data=f"info_{q_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))

    await callback.message.edit_text(
        "📚 <b>Список тестов</b>\n\n✅ — пройден | 🔒 — Премиум | 📖 — бесплатно",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# КАРТОЧКА ТЕСТА
# ============================================================
@dp.callback_query(F.data.startswith("info_"))
async def quiz_info(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    row = await get_quiz(q_id)
    if not row:
        return await callback.answer("Тест не найден", show_alert=True)

    _, title, data_json, is_paid = row
    questions = clean_quiz_data(json.loads(data_json))
    is_premium = await check_premium(callback.from_user.id)
    lock_text = "🔒 Премиум" if is_paid else "🆓 Бесплатно"

    builder = InlineKeyboardBuilder()
    if is_paid and not is_premium:
        builder.row(InlineKeyboardButton(text="💳 Купить доступ", callback_data="buy_premium"))
        builder.row(InlineKeyboardButton(
            text="👨‍💼 Связаться с менеджером",
            url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
        ))
    else:
        builder.row(InlineKeyboardButton(text="▶️ Начать тест", callback_data=f"run_{q_id}"))

    builder.row(InlineKeyboardButton(
        text="📤 Поделиться тестом", switch_inline_query=f"quiz_{q_id}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_tests"))

    await callback.message.edit_text(
        f"🎯 <b>{title}</b>\n\n"
        f"📝 Вопросов: <b>{len(questions)}</b>\n"
        f"⏱ Время на вопрос: <b>{QUESTION_TIMEOUT} сек</b>\n"
        f"💰 Доступ: {lock_text}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# ПОКУПКА ПРЕМИУМА
# ============================================================
@dp.callback_query(F.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="👨‍💼 Связаться с менеджером",
        url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_tests"))
    await callback.message.edit_text(
        "💎 <b>Премиум доступ</b>\n\n"
        "✔ Доступ ко всем платным тестам\n"
        "✔ Подробная статистика\n"
        "✔ Разбор ошибок\n"
        "✔ Новые материалы\n\n"
        "📅 Варианты:\n"
        "• 7 дней\n"
        "• 30 дней\n"
        "• Навсегда\n\n"
        "Для оплаты свяжитесь с менеджером:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# ЗАПУСК ТЕСТА
# ============================================================
@dp.callback_query(F.data.startswith("run_"))
async def start_quiz_callback(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    row = await get_quiz(q_id)
    if not row:
        return await callback.answer("Тест не найден", show_alert=True)

    _, _, _, is_paid = row
    is_premium = await check_premium(callback.from_user.id)
    if is_paid and not is_premium:
        return await callback.answer("❌ Нужен Премиум доступ!", show_alert=True)

    if callback.from_user.id in active_sessions:
        return await callback.answer(
            "У вас уже идёт тест. Завершите его перед началом нового.", show_alert=True
        )

    await callback.message.delete()
    await launch_quiz(callback.message.chat.id, callback.from_user.id, q_id)

async def launch_quiz(chat_id: int, user_id: int, q_id: int):
    row = await get_quiz(q_id)
    if not row:
        await bot.send_message(chat_id, "❌ Тест не найден.")
        return

    _, title, data_json, is_paid = row
    is_premium = await check_premium(user_id)
    if is_paid and not is_premium:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="💳 Купить доступ", callback_data="buy_premium"))
        await bot.send_message(
            chat_id, "🔒 Этот тест доступен только для Премиум пользователей.",
            reply_markup=builder.as_markup()
        )
        return

    questions = clean_quiz_data(json.loads(data_json))
    session = QuizSession(
        user_id=user_id, chat_id=chat_id, quiz_id=q_id,
        quiz_title=title, questions=questions
    )
    active_sessions[user_id] = session

    await bot.send_message(
        chat_id,
        f"🚀 Начинаем тест <b>«{title}»</b>!\n"
        f"📝 {len(questions)} вопросов · ⏱ {QUESTION_TIMEOUT} сек на вопрос\n\nУдачи! 🍀",
        parse_mode="HTML"
    )
    asyncio.create_task(run_quiz_loop(session))

async def run_quiz_loop(session: QuizSession):
    """Основной цикл теста с asyncio.Event для мгновенного перехода после ответа."""
    while session.current_index < len(session.questions) and session.active:
        # Ждём пока тест на паузе
        while session.paused and session.active:
            await asyncio.sleep(0.3)

        if not session.active:
            break

        q = session.questions[session.current_index]
        opts = [clean_option(o) for o in q['opts']]
        session.answer_event.clear()

        # Отправляем вопрос
        try:
            poll_msg = await bot.send_poll(
                chat_id=session.chat_id,
                question=f"[{session.current_index + 1}/{len(session.questions)}] {q['q']}",
                options=opts,
                type='quiz',
                correct_option_id=q['correct'],
                open_period=QUESTION_TIMEOUT,
                is_anonymous=False,
                protect_content=True
            )
            session.current_poll_id = poll_msg.poll.id
        except Exception as e:
            logger.error(f"Ошибка отправки poll: {e}")
            session.active = False
            break

        # Кнопки управления под вопросом
        try:
            ctrl_msg = await bot.send_message(
                session.chat_id, "⏱ Выберите действие:",
                reply_markup=quiz_control_kb(paused=False)
            )
            session.control_message_id = ctrl_msg.message_id
        except Exception:
            pass

        # Ждём ответ или таймаут
        try:
            await asyncio.wait_for(
                asyncio.shield(session.answer_event.wait()),
                timeout=QUESTION_TIMEOUT
            )
        except asyncio.TimeoutError:
            # Пропуск
            if session.active and not session.paused:
                session.missed_count += 1
                session.consecutive_missed += 1
                session.missed_questions.append(q)
                session.current_index += 1
                await _delete_control_message(session)

                # 2 пропуска подряд → пауза с выбором
                if session.consecutive_missed >= 2:
                    session.paused = True
                    session.answer_event.clear()
                    try:
                        await bot.send_message(
                            session.chat_id,
                            "⚠️ Вы пропустили 2 вопроса подряд.\nЧто делаем дальше?",
                            reply_markup=missed_choice_kb()
                        )
                    except Exception:
                        pass
            continue

        await _delete_control_message(session)

        if not session.active:
            break

    if session.active:
        session.active = False
        session.finished = True
        await finish_quiz(session)

async def _delete_control_message(session: QuizSession):
    if session.control_message_id:
        try:
            await bot.delete_message(session.chat_id, session.control_message_id)
        except Exception:
            pass
        session.control_message_id = None

# ============================================================
# УПРАВЛЕНИЕ ТЕСТОМ
# ============================================================
@dp.callback_query(F.data == "quiz_pause")
async def quiz_pause(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in active_sessions:
        return await callback.answer("Нет активного теста", show_alert=True)
    session = active_sessions[uid]
    if session.paused:
        return await callback.answer("Тест уже приостановлен", show_alert=True)
    session.paused = True
    await callback.message.edit_text(
        "⏸ <b>Тест приостановлен.</b>\n\nКогда будете готовы, нажмите «▶️ Продолжить».",
        reply_markup=quiz_control_kb(paused=True),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "quiz_resume")
async def quiz_resume(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in active_sessions:
        return await callback.answer("Нет активного теста", show_alert=True)
    session = active_sessions[uid]
    session.paused = False
    session.consecutive_missed = 0
    await callback.message.edit_text("▶️ Продолжаем тест...", reply_markup=None)
    await callback.answer()

@dp.callback_query(F.data == "quiz_finish")
async def quiz_finish_early(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in active_sessions:
        return await callback.answer("Нет активного теста", show_alert=True)
    session = active_sessions[uid]
    session.active = False
    session.paused = False
    session.answer_event.set()
    await callback.message.edit_text("⛔ Завершение теста...", reply_markup=None)
    await callback.answer()
    await asyncio.sleep(0.5)
    await finish_quiz(session, early=True)

# ============================================================
# ОТСЛЕЖИВАНИЕ ОТВЕТОВ
# ============================================================
@dp.poll_answer()
async def handle_poll_answer(answer: PollAnswer):
    uid = answer.user.id
    if uid not in active_sessions:
        return
    session = active_sessions[uid]
    if not session.active or session.paused:
        return

    q = session.questions[session.current_index]
    user_answer = answer.option_ids[0] if answer.option_ids else -1

    if user_answer == q['correct']:
        session.correct_count += 1
        session.consecutive_missed = 0
    else:
        session.wrong_count += 1
        session.consecutive_missed = 0
        session.wrong_questions.append(q)

    session.current_index += 1
    session.answer_event.set()  # мгновенный переход к следующему вопросу

# ============================================================
# РЕЗУЛЬТАТ ТЕСТА
# ============================================================
async def finish_quiz(session: QuizSession, early: bool = False):
    active_sessions.pop(session.user_id, None)

    total = len(session.questions)
    remaining = total - session.answered_count
    percent = session.percent

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO results
               (user_id, quiz_id, score, total, wrong, missed, percent, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (session.user_id, session.quiz_id,
             session.correct_count, total,
             session.wrong_count, session.missed_count, percent)
        )
        await db.commit()

    emoji = "🏆" if percent >= 80 else ("👍" if percent >= 50 else "📚")

    if early:
        result_text = (
            f"⛔ <b>Тест завершён досрочно.</b>\n\n"
            f"📘 Тест: <b>{session.quiz_title}</b>\n"
            f"📝 Всего вопросов: <b>{total}</b>\n"
            f"✅ Правильных: <b>{session.correct_count}</b>\n"
            f"❌ Неправильных: <b>{session.wrong_count}</b>\n"
            f"⏭ Пропущенных: <b>{session.missed_count}</b>\n"
            f"📌 Не завершено: <b>{remaining}</b>\n\n"
            f"📊 Текущий результат: <b>{percent}%</b>"
        )
    else:
        result_text = (
            f"{emoji} <b>Тест «{session.quiz_title}» завершён!</b>\n\n"
            f"✅ Правильных: <b>{session.correct_count}</b>\n"
            f"❌ Неправильных: <b>{session.wrong_count}</b>\n"
            f"⏭ Пропущенных: <b>{session.missed_count}</b>\n\n"
            f"📊 Результат: <b>{percent}%</b>"
        )

    # Разбор ошибок
    is_premium = await check_premium(session.user_id)
    error_block = ""
    if is_premium and (session.wrong_questions or session.missed_questions):
        error_block = "\n\n📋 <b>Разбор ошибок:</b>"
        for i, q in enumerate(session.wrong_questions[:5], 1):
            error_block += f"\n{i}. {q['q']}\n✅ <b>{q['opts'][q['correct']]}</b>"
        if session.missed_questions:
            error_block += "\n\n⏭ <b>Пропущенные:</b>"
            for i, q in enumerate(session.missed_questions[:3], 1):
                error_block += f"\n{i}. {q['q']}\n✅ <b>{q['opts'][q['correct']]}</b>"
    elif not is_premium and (session.wrong_questions or session.missed_questions):
        error_block = "\n\n🔒 <i>Разбор ошибок доступен в Премиуме</i>"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="🔄 Пройти снова", callback_data=f"run_{session.quiz_id}"
    ))
    builder.row(InlineKeyboardButton(text="📚 К тестам", callback_data="menu_tests"))
    builder.row(InlineKeyboardButton(
        text="📤 Поделиться", switch_inline_query=f"quiz_{session.quiz_id}"
    ))

    await bot.send_message(
        session.chat_id,
        result_text + error_block,
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# МОИ РЕЗУЛЬТАТЫ
# ============================================================
@dp.callback_query(F.data == "menu_results")
async def menu_results(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT q.title, r.score, r.total, r.wrong, r.missed, r.percent
            FROM results r JOIN quizzes q ON r.quiz_id = q.id
            WHERE r.user_id = ? ORDER BY r.percent DESC
        """, (callback.from_user.id,)) as c:
            results = await c.fetchall()

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))

    if not results:
        return await callback.message.edit_text(
            "📊 У вас пока нет результатов.\n\nПройдите первый тест! 📚",
            reply_markup=builder.as_markup()
        )

    best = max(results, key=lambda x: x[5])
    avg = round(sum(r[5] for r in results) / len(results))
    text = (
        f"📊 <b>Мои результаты</b>\n\n"
        f"📝 Тестов пройдено: <b>{len(results)}</b>\n"
        f"🏅 Лучший результат: <b>{best[5]:.0f}%</b> — {best[0]}\n"
        f"📈 Средний результат: <b>{avg}%</b>\n\n{'─' * 25}\n\n"
    )
    for title, score, total, wrong, missed, percent in results:
        emoji = "🏆" if percent >= 80 else ("👍" if percent >= 50 else "📚")
        text += (
            f"{emoji} <b>{title}</b>\n"
            f"   ✅ {score} | ❌ {wrong} | ⏭ {missed} из {total} · <b>{percent:.0f}%</b>\n\n"
        )

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

# ============================================================
# РЕФЕРАЛЬНАЯ СИСТЕМА
# ============================================================
@dp.callback_query(F.data == "menu_referral")
async def menu_referral(callback: types.CallbackQuery):
    uid = callback.from_user.id
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id = ?", (uid,)) as c:
            ref_count = (await c.fetchone())[0]

    next_bonus = REFERRAL_BONUS_COUNT - (ref_count % REFERRAL_BONUS_COUNT)
    bonus_text = (
        f"🎁 Ещё <b>{next_bonus}</b> приглашений → <b>{REFERRAL_BONUS_DAYS} дней Премиума</b>!"
        if next_bonus != REFERRAL_BONUS_COUNT
        else "🎉 Вы получили бонус за приглашения!"
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="📤 Поделиться ссылкой",
        url=f"https://t.me/share/url?url={ref_link}&text=Готовься к ЕНТ вместе со мной! 📚"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))

    await callback.message.edit_text(
        f"👥 <b>Пригласить друзей</b>\n\n"
        f"Ваша реферальная ссылка:\n<code>{ref_link}</code>\n\n"
        f"👥 Приглашено: <b>{ref_count}</b>\n\n"
        f"{bonus_text}\n\n"
        f"<i>За каждые {REFERRAL_BONUS_COUNT} друга — {REFERRAL_BONUS_DAYS} дней Премиума!</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# ПОМОЩЬ
# ============================================================
@dp.callback_query(F.data == "menu_help")
async def menu_help(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="👨‍💼 Связаться с менеджером",
        url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
    ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text(
        "ℹ️ <b>Помощь</b>\n\n"
        "📚 <b>Как пройти тест?</b>\n"
        "Выберите тест и нажмите «Начать». На каждый вопрос 30 секунд. "
        "Ответили раньше — следующий вопрос придёт сразу.\n\n"
        "⏸ <b>Пауза</b>\n"
        "Нажмите «Приостановить» чтобы остановить тест и продолжить позже.\n\n"
        "💎 <b>Что даёт Премиум?</b>\n"
        "• Все платные тесты\n"
        "• Разбор ошибок\n"
        "• Расширенная статистика\n\n"
        "👥 <b>Реферальная программа</b>\n"
        f"Пригласи {REFERRAL_BONUS_COUNT} друзей — получи {REFERRAL_BONUS_DAYS} дней Премиума!\n\n"
        "По всем вопросам:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# INLINE MODE
# ============================================================
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    results = []

    async def make_card(q_id, title, count):
        deep_link = f"https://t.me/{BOT_USERNAME}?start=quiz_{q_id}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Пройти тест", url=deep_link)],
            [InlineKeyboardButton(text="📤 Отправить в группу", switch_inline_query=f"quiz_{q_id}")],
            [InlineKeyboardButton(
                text="↗️ Поделиться",
                url=f"https://t.me/share/url?url={deep_link}&text=Пройди тест «{title}»!"
            )],
        ])
        return InlineQueryResultArticle(
            id=str(q_id),
            title=f"🎲 Тест «{title}»",
            description=f"📝 {count} вопросов · ⏱ {QUESTION_TIMEOUT} сек",
            input_message_content=InputTextMessageContent(
                message_text=(
                    f"🎲 Тест <b>«{title}»</b>\n\n"
                    f"📝 {count} вопросов · ⏱ {QUESTION_TIMEOUT} сек на вопрос\n\n"
                    f"👇 Нажми кнопку ниже, чтобы начать!"
                ),
                parse_mode="HTML"
            ),
            reply_markup=kb,
            thumbnail_url="https://img.icons8.com/color/96/test-passed.png"
        )

    if query.query.startswith("quiz_"):
        try:
            q_id = int(query.query.split("_")[1])
            row = await get_quiz(q_id)
            if row:
                questions = json.loads(row[2])
                results.append(await make_card(row[0], row[1], len(questions)))
        except (IndexError, ValueError):
            pass
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id, title, data FROM quizzes") as c:
                all_quizzes = await c.fetchall()
        for q_id, title, data_json in all_quizzes:
            results.append(await make_card(q_id, title, len(json.loads(data_json))))

    await query.answer(results, cache_time=5)

# ============================================================
# АДМИНКА
# ============================================================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет доступа", show_alert=True)

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить тест", callback_data="adm_add"))
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить тест", callback_data="adm_del"),
        InlineKeyboardButton(text="📋 Список тестов", callback_data="adm_list")
    )
    builder.row(InlineKeyboardButton(text="💰 Платный / Бесплатный", callback_data="adm_toggle"))
    builder.row(InlineKeyboardButton(text="🎁 Выдать Премиум", callback_data="adm_premium"))
    builder.row(InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"))
    builder.row(InlineKeyboardButton(text="📢 Каналы подписки", callback_data="adm_channels"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))

    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "adm_add")
async def adm_add(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("📝 Введите <b>название</b> теста:", parse_mode="HTML")
    await state.set_state(QuizStates.waiting_for_title)

@dp.message(QuizStates.waiting_for_title)
async def adm_get_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer(
        "📋 Отправь вопросы в формате:\n\n"
        "<code>Вопрос?\nA) Вариант\n*B) Правильный\nC) Вариант\n\nСледующий вопрос?</code>\n\n"
        "<i>Блоки разделяй пустой строкой. * перед правильным ответом.</i>",
        parse_mode="HTML"
    )
    await state.set_state(QuizStates.waiting_for_data)

@dp.message(QuizStates.waiting_for_data)
async def adm_save_quiz(message: types.Message, state: FSMContext):
    fsm_data = await state.get_data()
    title = fsm_data.get("title", "Без названия")
    questions, error = parse_quiz_data(message.text)
    if error:
        return await message.answer(f"❌ Ошибка: {error}\n\nПроверь формат и попробуй снова.")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO quizzes (title, data) VALUES (?, ?)",
            (title, json.dumps(questions, ensure_ascii=False))
        )
        await db.commit()
    await message.answer(
        f"✅ Тест <b>«{title}»</b> добавлен!\n📝 Вопросов: <b>{len(questions)}</b>",
        parse_mode="HTML"
    )
    await state.clear()

@dp.callback_query(F.data == "adm_list")
async def adm_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT q.id, q.title, q.is_paid, q.data,
                   COUNT(DISTINCT r.user_id) as unique_users,
                   COUNT(r.user_id) as attempts,
                   AVG(r.percent) as avg_pct,
                   MAX(r.percent) as best_pct
            FROM quizzes q LEFT JOIN results r ON q.id = r.quiz_id
            GROUP BY q.id
        """) as c:
            quizzes = await c.fetchall()

    if not quizzes:
        return await callback.answer("Тестов нет", show_alert=True)

    text = "📋 <b>Все тесты:</b>\n\n"
    for q_id, title, is_paid, data_json, unique, attempts, avg_pct, best_pct in quizzes:
        count = len(json.loads(data_json))
        mark = "🔒" if is_paid else "🆓"
        text += (
            f"<b>#{q_id}</b> {mark} {title}\n"
            f"   📝 {count} вопр | 👥 {unique or 0} польз | 🔄 {attempts or 0} раз\n"
            f"   📈 Средний: {avg_pct:.0f}% | 🏆 Лучший: {best_pct:.0f}%\n\n"
            if avg_pct else
            f"<b>#{q_id}</b> {mark} {title}\n"
            f"   📝 {count} вопр | Ещё не проходили\n\n"
        )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "adm_del")
async def adm_del_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, title FROM quizzes") as c:
            quizzes = await c.fetchall()
    if not quizzes:
        return await callback.answer("Нет тестов для удаления", show_alert=True)
    builder = InlineKeyboardBuilder()
    for q_id, title in quizzes:
        builder.row(InlineKeyboardButton(text=f"🗑 {title}", callback_data=f"del_{q_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("🗑 Выберите тест:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del_"))
async def adm_delete(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM quizzes WHERE id = ?", (q_id,))
        await db.execute("DELETE FROM results WHERE quiz_id = ?", (q_id,))
        await db.commit()
    await callback.answer("✅ Тест удалён", show_alert=True)
    await adm_del_list(callback)

@dp.callback_query(F.data == "adm_toggle")
async def adm_toggle_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            quizzes = await c.fetchall()
    if not quizzes:
        return await callback.answer("Нет тестов", show_alert=True)
    builder = InlineKeyboardBuilder()
    for q_id, title, is_paid in quizzes:
        mark = "🔒" if is_paid else "🆓"
        builder.row(InlineKeyboardButton(text=f"{mark} {title}", callback_data=f"toggle_{q_id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("💰 Нажмите тест для смены статуса:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("toggle_"))
async def adm_toggle(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT is_paid FROM quizzes WHERE id = ?", (q_id,)) as c:
            row = await c.fetchone()
        new_status = 0 if row[0] else 1
        await db.execute("UPDATE quizzes SET is_paid = ? WHERE id = ?", (new_status, q_id))
        await db.commit()
    await callback.answer(f"Статус: {'🔒 Платный' if new_status else '🆓 Бесплатный'}", show_alert=True)
    await adm_toggle_list(callback)

@dp.callback_query(F.data == "adm_premium")
async def adm_give_premium(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("🎁 Введите <b>ID пользователя</b>:", parse_mode="HTML")
    await state.set_state(PremiumStates.waiting_for_user_id)

@dp.message(PremiumStates.waiting_for_user_id)
async def adm_premium_get_id(message: types.Message, state: FSMContext):
    try:
        await state.update_data(target_user_id=int(message.text.strip()))
        await message.answer("📅 На сколько <b>дней</b>?", parse_mode="HTML")
        await state.set_state(PremiumStates.waiting_for_days)
    except ValueError:
        await message.answer("❌ Введите числовой ID")

@dp.message(PremiumStates.waiting_for_days)
async def adm_premium_get_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        fsm_data = await state.get_data()
        uid = fsm_data["target_user_id"]
        await grant_premium(uid, days)
        await message.answer(
            f"✅ Премиум на <b>{days} дней</b> выдан пользователю <b>{uid}</b>",
            parse_mode="HTML"
        )
        try:
            await bot.send_message(
                uid,
                f"🎉 Вам выдан <b>Премиум на {days} дней</b>!\n\nДоступны все тесты и разбор ошибок.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число дней")

@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1") as c:
            premium_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM quizzes") as c:
            total_quizzes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM results") as c:
            total_results = (await c.fetchone())[0]
        async with db.execute("SELECT AVG(percent) FROM results") as c:
            avg_pct = (await c.fetchone())[0] or 0
        async with db.execute("SELECT COUNT(*) FROM referrals") as c:
            total_refs = (await c.fetchone())[0]

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"💎 Премиум: <b>{premium_users}</b>\n"
        f"📚 Тестов: <b>{total_quizzes}</b>\n"
        f"📝 Прохождений: <b>{total_results}</b>\n"
        f"📈 Средний результат: <b>{avg_pct:.1f}%</b>\n"
        f"👥 Рефералов: <b>{total_refs}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# КАНАЛЫ ПОДПИСКИ
# ============================================================
@dp.callback_query(F.data == "adm_channels")
async def adm_channels(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    force = await is_force_subscription_enabled()
    channels = await get_required_channels()
    status_text = "✅ включена" if force else "❌ выключена"
    ch_text = "\n".join(f"{i+1}. {ch}" for i, ch in enumerate(channels)) if channels else "Каналов нет"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить канал", callback_data="ch_add"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить канал", callback_data="ch_del"))
    builder.row(InlineKeyboardButton(text="📋 Список каналов", callback_data="ch_list"))
    if force:
        builder.row(InlineKeyboardButton(
            text="❌ Выключить подписку", callback_data="ch_disable"
        ))
    else:
        builder.row(InlineKeyboardButton(
            text="✅ Включить подписку", callback_data="ch_enable"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))

    await callback.message.edit_text(
        f"📢 <b>Каналы подписки</b>\n\n"
        f"Обязательная подписка: <b>{status_text}</b>\n\n"
        f"Каналы:\n{ch_text}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "ch_add")
async def ch_add(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer(
        "📢 Введите username канала (например: <code>@historykazakhkz</code>):",
        parse_mode="HTML"
    )
    await state.set_state(ChannelStates.waiting_for_channel)

@dp.message(ChannelStates.waiting_for_channel)
async def ch_save(message: types.Message, state: FSMContext):
    ch = message.text.strip()
    if not ch.startswith("@"):
        ch = "@" + ch
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO subscription_channels (channel_username) VALUES (?)", (ch,)
            )
            await db.commit()
            await message.answer(f"✅ Канал <b>{ch}</b> добавлен!", parse_mode="HTML")
        except Exception:
            await message.answer(f"⚠️ Канал <b>{ch}</b> уже есть в списке.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "ch_del")
async def ch_del_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    channels = await get_required_channels()
    if not channels:
        return await callback.answer("Каналов нет", show_alert=True)
    builder = InlineKeyboardBuilder()
    for ch in channels:
        builder.row(InlineKeyboardButton(text=f"🗑 {ch}", callback_data=f"ch_remove_{ch}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_channels"))
    await callback.message.edit_text("Выберите канал для удаления:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("ch_remove_"))
async def ch_remove(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    ch = callback.data.replace("ch_remove_", "")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscription_channels WHERE channel_username = ?", (ch,))
        await db.commit()
    await callback.answer(f"✅ Канал {ch} удалён", show_alert=True)
    await ch_del_list(callback)

@dp.callback_query(F.data == "ch_list")
async def ch_list(callback: types.CallbackQuery):
    channels = await get_required_channels()
    force = await is_force_subscription_enabled()
    status = "✅ включена" if force else "❌ выключена"
    ch_text = "\n".join(f"{i+1}. {ch}" for i, ch in enumerate(channels)) if channels else "Каналов нет"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_channels"))
    await callback.message.edit_text(
        f"📋 <b>Обязательные каналы:</b>\n\n{ch_text}\n\nПодписка: <b>{status}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "ch_enable")
async def ch_enable(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE settings SET value = 'true' WHERE key = 'force_subscription'")
        await db.commit()
    await callback.answer("✅ Обязательная подписка включена", show_alert=True)
    await adm_channels(callback)

@dp.callback_query(F.data == "ch_disable")
async def ch_disable(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE settings SET value = 'false' WHERE key = 'force_subscription'")
        await db.commit()
    await callback.answer("❌ Обязательная подписка выключена", show_alert=True)
    await adm_channels(callback)

# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    await init_db()
    logger.info("✅ База данных инициализирована. Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
