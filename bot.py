"""
Telegram Quiz Bot — полная версия v3
Python + aiogram 3 + aiosqlite

Новое в v3:
- Экран Премиума после подписки
- Добавление тестов через пересланные Quiz Poll
- Накопительный буфер вопросов (несколько сообщений до "Сохранить")
- Продажа тестов за Telegram Stars
- Типы доступа: free / premium / stars / private
- Приватные тесты с доступом по user_id
- Аналитика активности пользователей в админке
- Исправлен баг зависшей сессии при завершении теста
- Платные тесты нельзя шарить в группы
- Групповой режим (базовая архитектура + карточка + старт)
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
    InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice,
    InlineQueryResultArticle, InputTextMessageContent, PollAnswer,
    PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ============================================================
# НАСТРОЙКИ
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8634239927:AAG2KLGHGvGMOkeDQyymMKzKOluUjqaxWxg")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

BOT_USERNAME   = "practicaent_bot"
ADMIN_IDS      = [5048547918]
MANAGER_LINK   = "@historyentk_bot"
CHANNEL_USERNAME = "@historykazakhkz"

DB_PATH              = "ent_bot.db"
REFERRAL_BONUS_COUNT = 3
REFERRAL_BONUS_DAYS  = 7
QUESTION_TIMEOUT     = 30
GROUP_MIN_PLAYERS    = 2   # минимум участников для группового теста

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# СТРУКТУРА АКТИВНОЙ СЕССИИ
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
    wrong_questions: list  = field(default_factory=list)
    missed_questions: list = field(default_factory=list)
    current_poll_id: Optional[str] = None
    control_message_id: Optional[int] = None
    active: bool  = True
    paused: bool  = False
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
        t = self.answered_count
        return round(self.correct_count / t * 100) if t else 0


# Активные индивидуальные сессии
active_sessions: dict[int, QuizSession] = {}

# Групповые сессии: {chat_id: {"quiz_id":int, "players":[uid,...], "started":bool}}
group_sessions: dict[int, dict] = {}

# Буфер вопросов при создании теста: {admin_id: {"title":str, "parts":[str,...], "polls":[dict,...]}}
quiz_buffers: dict[int, dict] = {}

# ============================================================
# FSM
# ============================================================
class QuizStates(StatesGroup):
    waiting_for_title    = State()
    collecting_questions = State()   # новый режим накопления

class PremiumStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days    = State()

class ChannelStates(StatesGroup):
    waiting_for_channel = State()

class StarsStates(StatesGroup):
    waiting_for_quiz_id = State()
    waiting_for_price   = State()

class PrivateAccessStates(StatesGroup):
    waiting_for_quiz_id = State()
    waiting_for_user_id = State()

class RevokeAccessStates(StatesGroup):
    waiting_for_quiz_id = State()
    waiting_for_user_id = State()

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
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                invited_by INTEGER,
                last_activity TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                data TEXT,
                access_type TEXT DEFAULT 'free',
                stars_price INTEGER DEFAULT 0,
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
                finished INTEGER DEFAULT 1,
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

            CREATE TABLE IF NOT EXISTS purchased_tests (
                user_id INTEGER,
                quiz_id INTEGER,
                purchased_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(user_id, quiz_id)
            );

            CREATE TABLE IF NOT EXISTS private_test_access (
                user_id INTEGER,
                quiz_id INTEGER,
                granted_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(user_id, quiz_id)
            );

            CREATE TABLE IF NOT EXISTS attempt_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                quiz_id INTEGER,
                action TEXT,
                detail TEXT,
                created_at TEXT DEFAULT (datetime('now'))
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
# ПАРСЕР
# ============================================================
def clean_option(text: str) -> str:
    return text.lstrip('*').strip()

def parse_quiz_data(text: str) -> tuple[list, str]:
    questions, blocks = [], text.strip().split('\n\n')
    for n, block in enumerate(blocks, 1):
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3:
            continue
        opts, correct = [], None
        for line in lines[1:]:
            is_ok = line.startswith('*')
            cleaned = clean_option(line)
            if not cleaned:
                continue
            if is_ok:
                if correct is not None:
                    return [], f"Блок {n}: более одного правильного ответа."
                correct = len(opts)
            opts.append(cleaned)
        if len(opts) < 2:
            return [], f"Блок {n}: минимум 2 варианта."
        if correct is None:
            return [], f"Блок {n}: нет правильного ответа (*)."
        questions.append({"q": lines[0], "opts": opts, "correct": correct})
    if not questions:
        return [], "Ни одного вопроса не распознано."
    return questions, ""

def clean_quiz_data(data: list) -> list:
    for q in data:
        q['opts'] = [clean_option(o) for o in q['opts']]
    return data

def count_questions_in_text(text: str) -> int:
    return len([b for b in text.strip().split('\n\n') if len([l for l in b.split('\n') if l.strip()]) >= 3])

# ============================================================
# УТИЛИТЫ — ПОЛЬЗОВАТЕЛИ
# ============================================================
async def register_user(user: types.User, invited_by: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,)) as c:
            exists = await c.fetchone()
        now = datetime.now().isoformat()
        if not exists:
            await db.execute(
                "INSERT INTO users (user_id,username,first_name,invited_by,last_activity) VALUES(?,?,?,?,?)",
                (user.id, user.username, user.first_name, invited_by, now)
            )
            if invited_by and invited_by != user.id:
                await db.execute(
                    "INSERT OR IGNORE INTO referrals (inviter_id,invited_user_id) VALUES(?,?)",
                    (invited_by, user.id)
                )
                async with db.execute(
                    "SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (invited_by,)
                ) as c2:
                    cnt = (await c2.fetchone())[0]
                if cnt > 0 and cnt % REFERRAL_BONUS_COUNT == 0:
                    await _grant_premium_db(db, invited_by, REFERRAL_BONUS_DAYS)
                    try:
                        await bot.send_message(
                            invited_by,
                            f"🎁 Вы пригласили <b>{cnt}</b> друзей — получили "
                            f"<b>{REFERRAL_BONUS_DAYS} дней Премиума</b>!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
        else:
            await db.execute(
                "UPDATE users SET last_activity=? WHERE user_id=?", (now, user.id)
            )
        await db.commit()

async def touch_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_activity=? WHERE user_id=?",
            (datetime.now().isoformat(), user_id)
        )
        await db.commit()

async def _grant_premium_db(db, user_id: int, days: int):
    until = (datetime.now() + timedelta(days=days)).isoformat()
    await db.execute(
        "UPDATE users SET is_premium=1, premium_until=? WHERE user_id=?", (until, user_id)
    )

async def grant_premium(user_id: int, days: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await _grant_premium_db(db, user_id, days)
        await db.commit()

async def check_premium(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT is_premium, premium_until FROM users WHERE user_id=?", (user_id,)
        ) as c:
            row = await c.fetchone()
    if not row or not row[0]:
        return False
    if row[1] and datetime.now() > datetime.fromisoformat(row[1]):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET is_premium=0 WHERE user_id=?", (user_id,))
            await db.commit()
        return False
    return True

# ============================================================
# УТИЛИТЫ — ДОСТУП К ТЕСТАМ
# ============================================================
async def has_quiz_access(user_id: int, quiz_id: int,
                           access_type: str, stars_price: int) -> bool:
    """Проверяет, может ли пользователь запустить тест."""
    if access_type == 'free':
        return True
    if access_type == 'premium':
        return await check_premium(user_id)
    if access_type == 'stars':
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM purchased_tests WHERE user_id=? AND quiz_id=?",
                (user_id, quiz_id)
            ) as c:
                bought = await c.fetchone()
        return bool(bought) or await check_premium(user_id)
    if access_type == 'private':
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM private_test_access WHERE user_id=? AND quiz_id=?",
                (user_id, quiz_id)
            ) as c:
                priv = await c.fetchone()
        return bool(priv)
    return False

async def get_visible_quizzes(user_id: int) -> list:
    """Возвращает тесты, видимые пользователю (без приватных, к которым нет доступа)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, access_type, stars_price FROM quizzes"
        ) as c:
            all_q = await c.fetchall()
        async with db.execute(
            "SELECT quiz_id FROM private_test_access WHERE user_id=?", (user_id,)
        ) as c:
            priv_access = {r[0] for r in await c.fetchall()}

    result = []
    for q_id, title, access_type, stars_price in all_q:
        if access_type == 'private' and q_id not in priv_access:
            continue
        result.append((q_id, title, access_type, stars_price))
    return result

# ============================================================
# УТИЛИТЫ — КАНАЛЫ
# ============================================================
async def get_required_channels() -> list[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT channel_username FROM subscription_channels") as c:
            return [r[0] for r in await c.fetchall()]

async def is_force_subscription_enabled() -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key='force_subscription'") as c:
            row = await c.fetchone()
    return row and row[0].lower() == 'true'

async def check_user_subscriptions(user_id: int) -> tuple[bool, list[str]]:
    channels, not_sub = await get_required_channels(), []
    for ch in channels:
        try:
            m = await bot.get_chat_member(ch, user_id)
            if m.status not in ("member", "administrator", "creator"):
                not_sub.append(ch)
        except Exception as e:
            logger.warning(f"Ошибка проверки подписки {user_id}@{ch}: {e}")
            not_sub.append(ch)
    return len(not_sub) == 0, not_sub

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
            "SELECT id, title, data, access_type, stars_price FROM quizzes WHERE id=?", (q_id,)
        ) as c:
            return await c.fetchone()

async def log_attempt(user_id: int, quiz_id: int, action: str, detail: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO attempt_logs (user_id,quiz_id,action,detail) VALUES(?,?,?,?)",
            (user_id, quiz_id, action, detail)
        )
        await db.commit()

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📚 Выбрать тест",      callback_data="menu_tests"))
    b.row(InlineKeyboardButton(text="📊 Мои результаты",    callback_data="menu_results"))
    b.row(InlineKeyboardButton(text="👥 Пригласить друзей", callback_data="menu_referral"))
    b.row(
        InlineKeyboardButton(text="ℹ️ Помощь",     callback_data="menu_help"),
        InlineKeyboardButton(text="👨‍💼 Менеджер", url=f"https://t.me/{MANAGER_LINK.lstrip('@')}")
    )
    if is_admin:
        b.row(InlineKeyboardButton(text="⚙️ Админка", callback_data="admin_panel"))
    return b.as_markup()

def quiz_control_kb(paused: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if paused:
        b.row(InlineKeyboardButton(text="▶️ Продолжить",    callback_data="quiz_resume"))
        b.row(InlineKeyboardButton(text="⛔ Завершить тест", callback_data="quiz_finish"))
    else:
        b.row(
            InlineKeyboardButton(text="⏸ Приостановить",   callback_data="quiz_pause"),
            InlineKeyboardButton(text="⛔ Завершить тест",  callback_data="quiz_finish")
        )
    return b.as_markup()

def missed_choice_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="▶️ Продолжить",    callback_data="quiz_resume"))
    b.row(InlineKeyboardButton(text="⛔ Завершить тест", callback_data="quiz_finish"))
    return b.as_markup()

def collecting_kb() -> InlineKeyboardMarkup:
    """Кнопки при накоплении вопросов."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💾 Сохранить тест", callback_data="quiz_buf_save"))
    b.row(
        InlineKeyboardButton(text="🗑 Очистить всё", callback_data="quiz_buf_clear"),
        InlineKeyboardButton(text="❌ Отмена",        callback_data="quiz_buf_cancel")
    )
    return b.as_markup()

# ============================================================
# ПОКАЗ ГЛАВНОГО МЕНЮ
# ============================================================
async def show_main_menu(target, user_id: int, edit: bool = False):
    is_admin = user_id in ADMIN_IDS
    text = "🏠 <b>Главное меню</b>\n\nВыберите раздел:"
    kb   = main_menu_kb(is_admin)
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
        elif param.startswith("group_"):
            # Групповой запуск: /start group_CHATID_QUIZID
            try:
                _, group_chat_id, q_id = param.split("_")
                group_chat_id = int(group_chat_id)
                q_id = int(q_id)
                await register_group_player(message.from_user.id, group_chat_id, q_id, message)
            except Exception:
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

    force    = await is_force_subscription_enabled()
    channels = await get_required_channels()
    if force and channels:
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
        # Показываем экран про Премиум после подписки
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="💎 О Премиуме",           callback_data="buy_premium"))
        b.row(InlineKeyboardButton(text="📚 К бесплатным тестам",  callback_data="menu_tests"))
        b.row(InlineKeyboardButton(
            text="👨‍💼 Связаться с менеджером",
            url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
        ))
        await callback.message.edit_text(
            "✅ <b>Спасибо за подписку!</b>\n\n"
            "Бесплатные тесты уже доступны.\n\n"
            "💎 <b>Хотите большего?</b> Подключите Премиум и получите:\n"
            "• Все платные тесты\n"
            "• Разбор ошибок\n"
            "• Приватные материалы\n"
            "• Расширенную статистику",
            reply_markup=b.as_markup(),
            parse_mode="HTML"
        )
    else:
        ch_text = "\n".join(f"• {ch}" for ch in not_sub)
        await callback.answer(
            f"Вы ещё не подписаны на:\n{ch_text}\n\nПодпишитесь и нажмите снова.",
            show_alert=True
        )

# ============================================================
# СПИСОК ТЕСТОВ
# ============================================================
@dp.callback_query(F.data == "menu_tests")
async def menu_tests(callback: types.CallbackQuery):
    uid   = callback.from_user.id
    force = await is_force_subscription_enabled()
    chs   = await get_required_channels()
    if force and chs:
        all_ok, not_sub = await check_user_subscriptions(uid)
        if not all_ok:
            await show_subscription_screen(callback, not_sub)
            return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT quiz_id FROM results WHERE user_id=?", (uid,)) as c:
            done = {r[0] for r in await c.fetchall()}
        async with db.execute(
            "SELECT quiz_id FROM purchased_tests WHERE user_id=?", (uid,)
        ) as c:
            bought = {r[0] for r in await c.fetchall()}

    quizzes    = await get_visible_quizzes(uid)
    is_premium = await check_premium(uid)

    if not quizzes:
        return await callback.answer("Тестов пока нет", show_alert=True)

    b = InlineKeyboardBuilder()
    for q_id, title, access_type, stars_price in quizzes:
        if q_id in done:
            mark = "✅ "
        elif access_type == 'free':
            mark = "📖 "
        elif access_type == 'premium' and not is_premium:
            mark = "🔒 "
        elif access_type == 'stars' and q_id not in bought and not is_premium:
            mark = f"⭐ "
        elif access_type == 'private':
            mark = "🔐 "
        else:
            mark = "📖 "
        b.row(InlineKeyboardButton(text=f"{mark}{title}", callback_data=f"info_{q_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))

    await callback.message.edit_text(
        "📚 <b>Список тестов</b>\n\n"
        "✅ — пройден | 📖 — бесплатно | 🔒 — Премиум | ⭐ — Stars | 🔐 — приватный",
        reply_markup=b.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# КАРТОЧКА ТЕСТА
# ============================================================
@dp.callback_query(F.data.startswith("info_"))
async def quiz_info(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    q_id = int(callback.data.split("_")[1])
    row  = await get_quiz(q_id)
    if not row:
        return await callback.answer("Тест не найден", show_alert=True)

    _, title, data_json, access_type, stars_price = row
    questions  = clean_quiz_data(json.loads(data_json))
    is_premium = await check_premium(uid)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM purchased_tests WHERE user_id=? AND quiz_id=?", (uid, q_id)
        ) as c:
            bought = await c.fetchone()

    access_label = {
        'free':    "🆓 Бесплатно",
        'premium': "🔒 Премиум",
        'stars':   f"⭐ {stars_price} Stars",
        'private': "🔐 Приватный"
    }.get(access_type, "🆓 Бесплатно")

    b = InlineKeyboardBuilder()
    can_run = await has_quiz_access(uid, q_id, access_type, stars_price)

    if can_run:
        b.row(InlineKeyboardButton(text="▶️ Начать тест", callback_data=f"run_{q_id}"))
        # Кнопку шаринга только для бесплатных
        if access_type == 'free':
            b.row(InlineKeyboardButton(text="📤 Поделиться тестом",
                                        switch_inline_query=f"quiz_{q_id}"))
            b.row(InlineKeyboardButton(text="👥 Отправить в группу",
                                        switch_inline_query_chosen_chat=types.SwitchInlineQueryChosenChat(
                                            query=f"quiz_{q_id}", allow_group_chats=True
                                        )))
    elif access_type == 'premium':
        b.row(InlineKeyboardButton(text="💎 Купить Премиум", callback_data="buy_premium"))
    elif access_type == 'stars' and not bought and not is_premium:
        b.row(InlineKeyboardButton(
            text=f"⭐ Купить за {stars_price} Stars",
            callback_data=f"buy_stars_{q_id}"
        ))
    elif access_type == 'private':
        b.row(InlineKeyboardButton(
            text="👨‍💼 Запросить доступ",
            url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
        ))

    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_tests"))

    await callback.message.edit_text(
        f"🎯 <b>{title}</b>\n\n"
        f"📝 Вопросов: <b>{len(questions)}</b>\n"
        f"⏱ Время на вопрос: <b>{QUESTION_TIMEOUT} сек</b>\n"
        f"💰 Доступ: {access_label}",
        reply_markup=b.as_markup(),
        parse_mode="HTML"
    )

# ============================================================
# ПОКУПКА ПРЕМИУМА
# ============================================================
@dp.callback_query(F.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="👨‍💼 Связаться с менеджером",
        url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
    ))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu_tests"))
    await callback.message.edit_text(
        "💎 <b>Премиум доступ</b>\n\n"
        "✔ Все платные тесты\n"
        "✔ Разбор ошибок\n"
        "✔ Приватные материалы\n"
        "✔ Расширенная статистика\n\n"
        "📅 Варианты: 7 дней · 30 дней · Навсегда\n\n"
        "Для оплаты — менеджеру:",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

# ============================================================
# ПОКУПКА ЗА TELEGRAM STARS
# ============================================================
@dp.callback_query(F.data.startswith("buy_stars_"))
async def buy_stars(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[2])
    row  = await get_quiz(q_id)
    if not row:
        return await callback.answer("Тест не найден", show_alert=True)
    _, title, _, _, stars_price = row
    if not stars_price:
        return await callback.answer("Цена не установлена", show_alert=True)

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Тест «{title}»",
        description=f"Разовый доступ к тесту «{title}»",
        payload=f"quiz_{q_id}",
        currency="XTR",       # Telegram Stars
        prices=[LabeledPrice(label=f"Тест «{title}»", amount=stars_price)]
    )
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    await pcq.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("quiz_"):
        q_id = int(payload.split("_")[1])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO purchased_tests (user_id,quiz_id) VALUES(?,?)",
                (message.from_user.id, q_id)
            )
            await db.commit()
        row = await get_quiz(q_id)
        title = row[1] if row else "тест"
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="▶️ Начать тест", callback_data=f"run_{q_id}"))
        await message.answer(
            f"✅ <b>Оплата прошла!</b>\n\nТест «{title}» теперь доступен.",
            reply_markup=b.as_markup(), parse_mode="HTML"
        )

# ============================================================
# ЗАПУСК ТЕСТА
# ============================================================
@dp.callback_query(F.data.startswith("run_"))
async def start_quiz_callback(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    q_id = int(callback.data.split("_")[1])
    row  = await get_quiz(q_id)
    if not row:
        return await callback.answer("Тест не найден", show_alert=True)

    _, _, _, access_type, stars_price = row
    can_run = await has_quiz_access(uid, q_id, access_type, stars_price)
    if not can_run:
        return await callback.answer("❌ Нет доступа!", show_alert=True)
    if uid in active_sessions:
        return await callback.answer(
            "У вас уже идёт тест. Завершите его перед началом нового.", show_alert=True
        )

    await callback.message.delete()
    await launch_quiz(callback.message.chat.id, uid, q_id)

async def launch_quiz(chat_id: int, user_id: int, q_id: int):
    row = await get_quiz(q_id)
    if not row:
        await bot.send_message(chat_id, "❌ Тест не найден.")
        return

    _, title, data_json, access_type, stars_price = row
    can_run = await has_quiz_access(user_id, q_id, access_type, stars_price)
    if not can_run:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="💎 Купить Премиум", callback_data="buy_premium"))
        await bot.send_message(chat_id, "🔒 Нет доступа к этому тесту.",
                               reply_markup=b.as_markup())
        return

    questions = clean_quiz_data(json.loads(data_json))
    session   = QuizSession(user_id=user_id, chat_id=chat_id,
                             quiz_id=q_id, quiz_title=title, questions=questions)
    active_sessions[user_id] = session
    await touch_user(user_id)
    await log_attempt(user_id, q_id, "start")

    await bot.send_message(
        chat_id,
        f"🚀 Начинаем тест <b>«{title}»</b>!\n"
        f"📝 {len(questions)} вопросов · ⏱ {QUESTION_TIMEOUT} сек\n\nУдачи! 🍀",
        parse_mode="HTML"
    )
    asyncio.create_task(run_quiz_loop(session))

async def run_quiz_loop(session: QuizSession):
    """Основной цикл теста с asyncio.Event."""
    try:
        while session.current_index < len(session.questions) and session.active:
            while session.paused and session.active:
                await asyncio.sleep(0.3)
            if not session.active:
                break

            q    = session.questions[session.current_index]
            opts = [clean_option(o) for o in q['opts']]
            session.answer_event.clear()

            try:
                poll_msg = await bot.send_poll(
                    chat_id=session.chat_id,
                    question=f"[{session.current_index+1}/{len(session.questions)}] {q['q']}",
                    options=opts,
                    type='quiz',
                    correct_option_id=q['correct'],
                    open_period=QUESTION_TIMEOUT,
                    is_anonymous=False,
                    protect_content=True
                )
                session.current_poll_id = poll_msg.poll.id
            except Exception as e:
                logger.error(f"Ошибка poll: {e}")
                session.active = False
                break

            try:
                ctrl = await bot.send_message(
                    session.chat_id, "⏱ Выберите действие:",
                    reply_markup=quiz_control_kb()
                )
                session.control_message_id = ctrl.message_id
            except Exception:
                pass

            try:
                await asyncio.wait_for(
                    asyncio.shield(session.answer_event.wait()),
                    timeout=QUESTION_TIMEOUT
                )
            except asyncio.TimeoutError:
                if session.active and not session.paused:
                    session.missed_count      += 1
                    session.consecutive_missed += 1
                    session.missed_questions.append(q)
                    session.current_index     += 1
                    await _delete_control_message(session)
                    if session.consecutive_missed >= 2:
                        session.paused = True
                        session.answer_event.clear()
                        try:
                            await bot.send_message(
                                session.chat_id,
                                "⚠️ Вы пропустили 2 вопроса подряд. Что делаем дальше?",
                                reply_markup=missed_choice_kb()
                            )
                        except Exception:
                            pass
                continue

            await _delete_control_message(session)
            if not session.active:
                break
    except Exception as e:
        logger.error(f"Ошибка в quiz_loop uid={session.user_id}: {e}")
    finally:
        if session.active:
            session.active   = False
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
    s = active_sessions[uid]
    if s.paused:
        return await callback.answer("Тест уже на паузе", show_alert=True)
    s.paused = True
    await callback.message.edit_text(
        "⏸ <b>Тест приостановлен.</b>\n\nНажмите «▶️ Продолжить» когда будете готовы.",
        reply_markup=quiz_control_kb(paused=True), parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "quiz_resume")
async def quiz_resume(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid not in active_sessions:
        return await callback.answer("Нет активного теста", show_alert=True)
    s = active_sessions[uid]
    s.paused             = False
    s.consecutive_missed = 0
    await callback.message.edit_text("▶️ Продолжаем...", reply_markup=None)
    await callback.answer()

@dp.callback_query(F.data == "quiz_finish")
async def quiz_finish_early(callback: types.CallbackQuery):
    uid = callback.from_user.id
    session = active_sessions.get(uid)
    if not session:
        return await callback.answer("Нет активного теста", show_alert=True)

    # ИСПРАВЛЕНИЕ БАГА: гарантированно чистим и показываем результат
    session.active = False
    session.paused = False
    session.answer_event.set()

    try:
        await callback.message.edit_text("⛔ Завершение теста...", reply_markup=None)
    except Exception:
        pass
    await callback.answer()

    # Убираем из активных СРАЗУ, чтобы не зависала сессия
    active_sessions.pop(uid, None)
    await finish_quiz(session, early=True)

# ============================================================
# ОТВЕТЫ НА ОПРОСЫ
# ============================================================
@dp.poll_answer()
async def handle_poll_answer(answer: PollAnswer):
    uid = answer.user.id
    if uid not in active_sessions:
        return
    s = active_sessions[uid]
    if not s.active or s.paused:
        return

    q = s.questions[s.current_index]
    chosen = answer.option_ids[0] if answer.option_ids else -1

    if chosen == q['correct']:
        s.correct_count      += 1
        s.consecutive_missed  = 0
    else:
        s.wrong_count        += 1
        s.consecutive_missed  = 0
        s.wrong_questions.append(q)

    s.current_index += 1
    s.answer_event.set()   # мгновенный переход

# ============================================================
# РЕЗУЛЬТАТ ТЕСТА
# ============================================================
async def finish_quiz(session: QuizSession, early: bool = False):
    active_sessions.pop(session.user_id, None)   # двойная чистка на всякий случай

    total     = len(session.questions)
    remaining = total - session.answered_count
    percent   = session.percent

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR REPLACE INTO results
               (user_id,quiz_id,score,total,wrong,missed,percent,finished,completed_at)
               VALUES(?,?,?,?,?,?,?,?,datetime('now'))""",
            (session.user_id, session.quiz_id,
             session.correct_count, total,
             session.wrong_count, session.missed_count,
             percent, 0 if early else 1)
        )
        await db.commit()
    await log_attempt(session.user_id, session.quiz_id,
                      "finish_early" if early else "finish",
                      f"score={session.correct_count}/{total} pct={percent}")

    emoji = "🏆" if percent >= 80 else ("👍" if percent >= 50 else "📚")

    if early:
        text = (
            f"⛔ <b>Тест завершён досрочно.</b>\n\n"
            f"📘 {session.quiz_title}\n"
            f"📝 Всего вопросов: <b>{total}</b>\n"
            f"✅ Правильных: <b>{session.correct_count}</b>\n"
            f"❌ Неправильных: <b>{session.wrong_count}</b>\n"
            f"⏭ Пропущенных: <b>{session.missed_count}</b>\n"
            f"📌 Не завершено: <b>{remaining}</b>\n\n"
            f"📊 Результат: <b>{percent}%</b>"
        )
    else:
        text = (
            f"{emoji} <b>Тест «{session.quiz_title}» завершён!</b>\n\n"
            f"✅ Правильных: <b>{session.correct_count}</b>\n"
            f"❌ Неправильных: <b>{session.wrong_count}</b>\n"
            f"⏭ Пропущенных: <b>{session.missed_count}</b>\n\n"
            f"📊 Результат: <b>{percent}%</b>"
        )

    is_premium = await check_premium(session.user_id)
    err_block  = ""
    if is_premium and (session.wrong_questions or session.missed_questions):
        err_block = "\n\n📋 <b>Разбор ошибок:</b>"
        for i, q in enumerate(session.wrong_questions[:5], 1):
            err_block += f"\n{i}. {q['q']}\n✅ <b>{q['opts'][q['correct']]}</b>"
        if session.missed_questions:
            err_block += "\n\n⏭ <b>Пропущенные:</b>"
            for i, q in enumerate(session.missed_questions[:3], 1):
                err_block += f"\n{i}. {q['q']}\n✅ <b>{q['opts'][q['correct']]}</b>"
    elif not is_premium and (session.wrong_questions or session.missed_questions):
        err_block = "\n\n🔒 <i>Разбор ошибок доступен в Премиуме</i>"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 Пройти снова", callback_data=f"run_{session.quiz_id}"))
    b.row(InlineKeyboardButton(text="📚 К тестам",     callback_data="menu_tests"))
    b.row(InlineKeyboardButton(text="📤 Поделиться",
                                switch_inline_query=f"quiz_{session.quiz_id}"))

    await bot.send_message(
        session.chat_id, text + err_block,
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

# ============================================================
# МОИ РЕЗУЛЬТАТЫ
# ============================================================
@dp.callback_query(F.data == "menu_results")
async def menu_results(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT q.title, r.score, r.total, r.wrong, r.missed, r.percent, r.finished
            FROM results r JOIN quizzes q ON r.quiz_id=q.id
            WHERE r.user_id=? ORDER BY r.percent DESC
        """, (callback.from_user.id,)) as c:
            results = await c.fetchall()

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    if not results:
        return await callback.message.edit_text(
            "📊 У вас пока нет результатов. Пройдите первый тест! 📚",
            reply_markup=b.as_markup()
        )

    best = max(results, key=lambda x: x[5])
    avg  = round(sum(r[5] for r in results) / len(results))
    text = (
        f"📊 <b>Мои результаты</b>\n\n"
        f"📝 Тестов пройдено: <b>{len(results)}</b>\n"
        f"🏅 Лучший: <b>{best[5]:.0f}%</b> — {best[0]}\n"
        f"📈 Средний: <b>{avg}%</b>\n\n{'─'*25}\n\n"
    )
    for title, score, total, wrong, missed, percent, finished in results:
        em = "🏆" if percent >= 80 else ("👍" if percent >= 50 else "📚")
        flag = " ⚠️ прерван" if not finished else ""
        text += (
            f"{em} <b>{title}</b>{flag}\n"
            f"   ✅ {score} | ❌ {wrong} | ⏭ {missed} / {total} · <b>{percent:.0f}%</b>\n\n"
        )
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

# ============================================================
# РЕФЕРАЛЬНАЯ СИСТЕМА
# ============================================================
@dp.callback_query(F.data == "menu_referral")
async def menu_referral(callback: types.CallbackQuery):
    uid      = callback.from_user.id
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (uid,)) as c:
            cnt = (await c.fetchone())[0]

    next_b = REFERRAL_BONUS_COUNT - (cnt % REFERRAL_BONUS_COUNT)
    bonus  = (
        f"🎁 Ещё <b>{next_b}</b> → <b>{REFERRAL_BONUS_DAYS} дней Премиума</b>!"
        if next_b != REFERRAL_BONUS_COUNT else "🎉 Вы получили бонус!"
    )
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="📤 Поделиться ссылкой",
        url=f"https://t.me/share/url?url={ref_link}&text=Готовься к ЕНТ вместе со мной! 📚"
    ))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text(
        f"👥 <b>Пригласить друзей</b>\n\n"
        f"Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        f"👥 Приглашено: <b>{cnt}</b>\n\n{bonus}\n\n"
        f"<i>За каждые {REFERRAL_BONUS_COUNT} друга — {REFERRAL_BONUS_DAYS} дней Премиума!</i>",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

# ============================================================
# ПОМОЩЬ
# ============================================================
@dp.callback_query(F.data == "menu_help")
async def menu_help(callback: types.CallbackQuery):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="👨‍💼 Связаться с менеджером",
        url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
    ))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text(
        "ℹ️ <b>Помощь</b>\n\n"
        "📚 На каждый вопрос 30 сек. Ответили раньше — следующий приходит сразу.\n"
        "⏸ Можно приостановить и продолжить позже.\n"
        "💎 Премиум: все тесты + разбор ошибок + статистика.\n"
        "⭐ Отдельные тесты можно купить за Telegram Stars.\n"
        f"👥 {REFERRAL_BONUS_COUNT} друга = {REFERRAL_BONUS_DAYS} дней Премиума бесплатно!",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

# ============================================================
# INLINE MODE (только бесплатные тесты)
# ============================================================
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    results = []

    async def make_card(q_id, title, count):
        deep_link = f"https://t.me/{BOT_USERNAME}?start=quiz_{q_id}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Пройти тест", url=deep_link)],
            [InlineKeyboardButton(
                text="👥 Пройти в группе",
                url=deep_link          # группа через deep link
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
                    f"👇 Нажми кнопку, чтобы начать!"
                ),
                parse_mode="HTML"
            ),
            reply_markup=kb,
            thumbnail_url="https://img.icons8.com/color/96/test-passed.png"
        )

    if query.query.startswith("quiz_"):
        try:
            q_id = int(query.query.split("_")[1])
            row  = await get_quiz(q_id)
            # Шарить можно только бесплатные тесты
            if row and row[3] == 'free':
                qs = json.loads(row[2])
                results.append(await make_card(row[0], row[1], len(qs)))
        except (IndexError, ValueError):
            pass
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            # Показываем только бесплатные
            async with db.execute(
                "SELECT id, title, data FROM quizzes WHERE access_type='free'"
            ) as c:
                quizzes = await c.fetchall()
        for q_id, title, data_json in quizzes:
            results.append(await make_card(q_id, title, len(json.loads(data_json))))

    await query.answer(results, cache_time=5)

# ============================================================
# ГРУППОВОЙ РЕЖИМ
# ============================================================
async def register_group_player(user_id: int, group_chat_id: int, q_id: int,
                                 message: types.Message):
    """Регистрирует участника группового теста."""
    if group_chat_id not in group_sessions:
        group_sessions[group_chat_id] = {
            "quiz_id": q_id, "players": [], "started": False
        }

    gs = group_sessions[group_chat_id]
    if gs["started"]:
        return await message.answer("⚠️ Тест уже начался.")
    if user_id in gs["players"]:
        return await message.answer("✅ Вы уже зарегистрированы!")

    gs["players"].append(user_id)
    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    cnt  = len(gs["players"])

    await message.answer(f"✅ {name} готов! Участников: {cnt}/{GROUP_MIN_PLAYERS}")

    try:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text=f"▶️ Начать ({cnt}/{GROUP_MIN_PLAYERS})",
                                    callback_data=f"group_start_{group_chat_id}_{q_id}"))
        await bot.send_message(
            group_chat_id,
            f"👤 {name} присоединился! Участников: <b>{cnt}/{GROUP_MIN_PLAYERS}</b>",
            reply_markup=b.as_markup() if cnt >= GROUP_MIN_PLAYERS else None,
            parse_mode="HTML"
        )
    except Exception:
        pass

    if cnt >= GROUP_MIN_PLAYERS:
        await message.answer(
            f"🎯 Набрано {cnt} участников! Можно начинать.",
        )

@dp.callback_query(F.data.startswith("group_start_"))
async def group_start(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    group_chat_id = int(parts[2])
    q_id = int(parts[3])

    gs = group_sessions.get(group_chat_id)
    if not gs or gs["started"]:
        return await callback.answer("Тест уже начался или не найден", show_alert=True)

    gs["started"] = True
    row = await get_quiz(q_id)
    if not row:
        return

    _, title, data_json, _, _ = row
    questions = clean_quiz_data(json.loads(data_json))
    players   = gs["players"]

    await bot.send_message(
        group_chat_id,
        f"🚀 <b>Групповой тест «{title}»</b> начинается!\n"
        f"👥 Участников: <b>{len(players)}</b>\n"
        f"📝 {len(questions)} вопросов · ⏱ {QUESTION_TIMEOUT} сек",
        parse_mode="HTML"
    )

    # Запускаем вопросы в группе
    for i, q in enumerate(questions):
        opts = [clean_option(o) for o in q['opts']]
        try:
            await bot.send_poll(
                chat_id=group_chat_id,
                question=f"[{i+1}/{len(questions)}] {q['q']}",
                options=opts,
                type='quiz',
                correct_option_id=q['correct'],
                open_period=QUESTION_TIMEOUT,
                is_anonymous=False
            )
        except Exception as e:
            logger.error(f"Групповой poll: {e}")
        await asyncio.sleep(QUESTION_TIMEOUT + 2)

    await bot.send_message(group_chat_id, "🏁 Групповой тест завершён! Спасибо всем участникам.")
    group_sessions.pop(group_chat_id, None)
    await callback.answer()

# ============================================================
# АДМИНКА
# ============================================================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет доступа", show_alert=True)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Добавить тест",      callback_data="adm_add"))
    b.row(
        InlineKeyboardButton(text="🗑 Удалить",     callback_data="adm_del"),
        InlineKeyboardButton(text="📋 Список",      callback_data="adm_list")
    )
    b.row(InlineKeyboardButton(text="💰 Тип доступа",        callback_data="adm_access"))
    b.row(InlineKeyboardButton(text="⭐ Цена Stars",          callback_data="adm_stars"))
    b.row(InlineKeyboardButton(text="🔐 Приватный доступ",   callback_data="adm_private"))
    b.row(InlineKeyboardButton(text="🎁 Выдать Премиум",     callback_data="adm_premium"))
    b.row(InlineKeyboardButton(text="📊 Статистика",         callback_data="adm_stats"))
    b.row(InlineKeyboardButton(text="👥 Активность",         callback_data="adm_activity"))
    b.row(InlineKeyboardButton(text="📢 Каналы подписки",    callback_data="adm_channels"))
    b.row(InlineKeyboardButton(text="🔙 Назад",              callback_data="to_main"))
    await callback.message.edit_text("⚙️ <b>Админ-панель</b>",
                                      reply_markup=b.as_markup(), parse_mode="HTML")

# --- ДОБАВЛЕНИЕ ТЕСТА (накопительный буфер) ---
@dp.callback_query(F.data == "adm_add")
async def adm_add(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("📝 Введите <b>название</b> теста:", parse_mode="HTML")
    await state.set_state(QuizStates.waiting_for_title)

@dp.message(QuizStates.waiting_for_title)
async def adm_get_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    await state.update_data(title=title)
    quiz_buffers[message.from_user.id] = {"title": title, "parts": [], "polls": []}
    await message.answer(
        f"✅ Название: <b>{title}</b>\n\n"
        "Теперь отправляй вопросы:\n"
        "• Текстом (несколько сообщений)\n"
        "• Пересылай Quiz Poll из других чатов\n\n"
        "<code>Вопрос?\nA) Вариант\n*B) Правильный\nC) Вариант</code>\n\n"
        "Когда всё готово — нажми «💾 Сохранить тест».",
        reply_markup=collecting_kb(),
        parse_mode="HTML"
    )
    await state.set_state(QuizStates.collecting_questions)

@dp.message(QuizStates.collecting_questions, F.forward_from_chat | F.forward_date)
async def adm_collect_poll(message: types.Message, state: FSMContext):
    """Получение пересланного Quiz Poll от админа."""
    uid = message.from_user.id
    if uid not in quiz_buffers:
        return

    # Проверяем, это poll?
    if message.poll and message.poll.type == 'quiz':
        poll = message.poll
        opts = [o.text for o in poll.options]
        q    = {
            "q":       poll.question,
            "opts":    opts,
            "correct": poll.correct_option_id
        }
        quiz_buffers[uid]["polls"].append(q)
        total_q = len(quiz_buffers[uid]["polls"]) + sum(
            count_questions_in_text(p) for p in quiz_buffers[uid]["parts"]
        )
        await message.answer(
            f"✅ Quiz Poll добавлен!\n\n"
            f"Всего вопросов предварительно: <b>{total_q}</b>\n\n"
            f"Продолжайте или нажмите «💾 Сохранить тест».",
            reply_markup=collecting_kb(),
            parse_mode="HTML"
        )
    else:
        await message.answer("⚠️ Это не Quiz Poll. Перешлите именно quiz-вопрос.")

@dp.message(QuizStates.collecting_questions, F.poll)
async def adm_collect_poll_direct(message: types.Message, state: FSMContext):
    """Получение Quiz Poll напрямую."""
    uid = message.from_user.id
    if uid not in quiz_buffers:
        return
    poll = message.poll
    if poll.type != 'quiz':
        return await message.answer("⚠️ Это не Quiz Poll.")
    opts = [o.text for o in poll.options]
    q    = {"q": poll.question, "opts": opts, "correct": poll.correct_option_id}
    quiz_buffers[uid]["polls"].append(q)
    total_q = len(quiz_buffers[uid]["polls"]) + sum(
        count_questions_in_text(p) for p in quiz_buffers[uid]["parts"]
    )
    await message.answer(
        f"✅ Poll добавлен! Всего: <b>{total_q}</b>",
        reply_markup=collecting_kb(), parse_mode="HTML"
    )

@dp.message(QuizStates.collecting_questions)
async def adm_collect_text(message: types.Message, state: FSMContext):
    """Получение текстовых вопросов в буфер."""
    uid = message.from_user.id
    if uid not in quiz_buffers:
        return
    quiz_buffers[uid]["parts"].append(message.text)
    text_q = sum(count_questions_in_text(p) for p in quiz_buffers[uid]["parts"])
    poll_q = len(quiz_buffers[uid]["polls"])
    total  = text_q + poll_q
    await message.answer(
        f"✅ Часть добавлена!\n\n"
        f"Частей текста: <b>{len(quiz_buffers[uid]['parts'])}</b>\n"
        f"Poll вопросов: <b>{poll_q}</b>\n"
        f"Предварительно вопросов: <b>{total}</b>\n\n"
        f"Продолжайте или нажмите «💾 Сохранить тест».",
        reply_markup=collecting_kb(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "quiz_buf_save")
async def quiz_buf_save(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in quiz_buffers:
        return await callback.answer("Буфер пуст", show_alert=True)

    buf   = quiz_buffers[uid]
    title = buf["title"]

    # Собираем вопросы из текстовых частей
    all_text = "\n\n".join(buf["parts"])
    text_qs, error = parse_quiz_data(all_text) if all_text.strip() else ([], "")
    if error:
        return await callback.message.answer(f"❌ Ошибка в тексте: {error}")

    # Добавляем poll-вопросы
    all_questions = text_qs + buf["polls"]
    if not all_questions:
        return await callback.message.answer("❌ Вопросов нет. Добавьте хотя бы один.")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO quizzes (title, data) VALUES(?,?)",
            (title, json.dumps(all_questions, ensure_ascii=False))
        )
        await db.commit()

    quiz_buffers.pop(uid, None)
    await state.clear()
    await callback.message.answer(
        f"✅ Тест <b>«{title}»</b> сохранён!\n📝 Вопросов: <b>{len(all_questions)}</b>",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "quiz_buf_clear")
async def quiz_buf_clear(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in quiz_buffers:
        title = quiz_buffers[uid]["title"]
        quiz_buffers[uid]["parts"] = []
        quiz_buffers[uid]["polls"] = []
    await callback.message.answer(
        "🗑 Все вопросы очищены. Продолжайте добавлять.",
        reply_markup=collecting_kb()
    )

@dp.callback_query(F.data == "quiz_buf_cancel")
async def quiz_buf_cancel(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    quiz_buffers.pop(uid, None)
    await state.clear()
    await callback.message.answer("❌ Создание теста отменено.")

# --- СПИСОК ТЕСТОВ В АДМИНКЕ ---
@dp.callback_query(F.data == "adm_list")
async def adm_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT q.id, q.title, q.access_type, q.stars_price, q.data,
                   COUNT(DISTINCT r.user_id) AS users,
                   COUNT(r.user_id) AS attempts,
                   AVG(r.percent) AS avg_pct,
                   MAX(r.percent) AS best_pct
            FROM quizzes q LEFT JOIN results r ON q.id=r.quiz_id
            GROUP BY q.id
        """) as c:
            rows = await c.fetchall()

    if not rows:
        return await callback.answer("Тестов нет", show_alert=True)

    text = "📋 <b>Все тесты:</b>\n\n"
    for q_id, title, atype, sp, data_json, users, attempts, avg_pct, best_pct in rows:
        cnt  = len(json.loads(data_json))
        mark = {"free":"🆓","premium":"🔒","stars":f"⭐{sp}","private":"🔐"}.get(atype,"🆓")
        text += f"<b>#{q_id}</b> {mark} {title} | 📝{cnt}\n"
        if attempts:
            text += f"   👥{users} | 🔄{attempts} | 📈{avg_pct:.0f}% | 🏆{best_pct:.0f}%\n"
        text += "\n"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

# --- УДАЛИТЬ ТЕСТ ---
@dp.callback_query(F.data == "adm_del")
async def adm_del_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, title FROM quizzes") as c:
            quizzes = await c.fetchall()
    if not quizzes:
        return await callback.answer("Тестов нет", show_alert=True)
    b = InlineKeyboardBuilder()
    for q_id, title in quizzes:
        b.row(InlineKeyboardButton(text=f"🗑 {title}", callback_data=f"del_{q_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("🗑 Выберите тест:", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("del_"))
async def adm_delete(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM quizzes WHERE id=?", (q_id,))
        await db.execute("DELETE FROM results WHERE quiz_id=?", (q_id,))
        await db.execute("DELETE FROM purchased_tests WHERE quiz_id=?", (q_id,))
        await db.execute("DELETE FROM private_test_access WHERE quiz_id=?", (q_id,))
        await db.commit()
    await callback.answer("✅ Тест удалён", show_alert=True)
    await adm_del_list(callback)

# --- ТИП ДОСТУПА ---
@dp.callback_query(F.data == "adm_access")
async def adm_access_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, title, access_type FROM quizzes") as c:
            quizzes = await c.fetchall()
    if not quizzes:
        return await callback.answer("Тестов нет", show_alert=True)
    b = InlineKeyboardBuilder()
    for q_id, title, atype in quizzes:
        mark = {"free":"🆓","premium":"🔒","stars":"⭐","private":"🔐"}.get(atype,"🆓")
        b.row(InlineKeyboardButton(text=f"{mark} {title}", callback_data=f"setaccess_{q_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("💰 Выберите тест для смены типа доступа:",
                                      reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("setaccess_"))
async def adm_access_choose(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    b = InlineKeyboardBuilder()
    for atype, label in [("free","🆓 Бесплатно"),("premium","🔒 Премиум"),
                          ("stars","⭐ Stars"),("private","🔐 Приватный")]:
        b.row(InlineKeyboardButton(text=label, callback_data=f"applyaccess_{q_id}_{atype}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_access"))
    await callback.message.edit_text("Выберите тип доступа:", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("applyaccess_"))
async def adm_access_apply(callback: types.CallbackQuery):
    _, q_id_s, atype = callback.data.split("_")
    q_id = int(q_id_s)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE quizzes SET access_type=? WHERE id=?", (atype, q_id))
        await db.commit()
    await callback.answer(f"✅ Тип изменён на {atype}", show_alert=True)
    await adm_access_list(callback)

# --- ЦЕНА STARS ---
@dp.callback_query(F.data == "adm_stars")
async def adm_stars_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("⭐ Введите <b>ID теста</b> для установки цены Stars:", parse_mode="HTML")
    await state.set_state(StarsStates.waiting_for_quiz_id)

@dp.message(StarsStates.waiting_for_quiz_id)
async def adm_stars_get_id(message: types.Message, state: FSMContext):
    try:
        q_id = int(message.text.strip())
        row  = await get_quiz(q_id)
        if not row:
            return await message.answer("❌ Тест не найден")
        await state.update_data(quiz_id=q_id)
        await message.answer(f"Тест: <b>{row[1]}</b>\n\nВведите <b>цену в Stars</b> (целое число):",
                             parse_mode="HTML")
        await state.set_state(StarsStates.waiting_for_price)
    except ValueError:
        await message.answer("❌ Введите числовой ID")

@dp.message(StarsStates.waiting_for_price)
async def adm_stars_set(message: types.Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        d     = await state.get_data()
        q_id  = d["quiz_id"]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE quizzes SET stars_price=?, access_type='stars' WHERE id=?",
                (price, q_id)
            )
            await db.commit()
        await message.answer(f"✅ Цена <b>{price} Stars</b> установлена.", parse_mode="HTML")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число")

# --- ПРИВАТНЫЙ ДОСТУП ---
@dp.callback_query(F.data == "adm_private")
async def adm_private_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Выдать доступ",  callback_data="priv_grant"))
    b.row(InlineKeyboardButton(text="➖ Забрать доступ", callback_data="priv_revoke"))
    b.row(InlineKeyboardButton(text="📋 Список доступов", callback_data="priv_list"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("🔐 <b>Приватный доступ</b>",
                                      reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "priv_grant")
async def priv_grant_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите <b>ID теста</b> (приватного):", parse_mode="HTML")
    await state.set_state(PrivateAccessStates.waiting_for_quiz_id)

@dp.message(PrivateAccessStates.waiting_for_quiz_id)
async def priv_grant_quiz(message: types.Message, state: FSMContext):
    try:
        q_id = int(message.text.strip())
        await state.update_data(quiz_id=q_id)
        await message.answer("Введите <b>user_id</b> пользователя:", parse_mode="HTML")
        await state.set_state(PrivateAccessStates.waiting_for_user_id)
    except ValueError:
        await message.answer("❌ Введите числовой ID теста")

@dp.message(PrivateAccessStates.waiting_for_user_id)
async def priv_grant_user(message: types.Message, state: FSMContext):
    try:
        uid  = int(message.text.strip())
        d    = await state.get_data()
        q_id = d["quiz_id"]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO private_test_access (user_id,quiz_id) VALUES(?,?)",
                (uid, q_id)
            )
            await db.execute("UPDATE quizzes SET access_type='private' WHERE id=?", (q_id,))
            await db.commit()
        await message.answer(f"✅ Доступ к тесту #{q_id} выдан пользователю {uid}.")
        try:
            row = await get_quiz(q_id)
            await bot.send_message(
                uid,
                f"🔐 Вам открыт приватный тест <b>«{row[1]}»</b>!",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите числовой user_id")

@dp.callback_query(F.data == "priv_revoke")
async def priv_revoke_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите <b>ID теста</b>:", parse_mode="HTML")
    await state.set_state(RevokeAccessStates.waiting_for_quiz_id)

@dp.message(RevokeAccessStates.waiting_for_quiz_id)
async def priv_revoke_quiz(message: types.Message, state: FSMContext):
    try:
        q_id = int(message.text.strip())
        await state.update_data(quiz_id=q_id)
        await message.answer("Введите <b>user_id</b>:", parse_mode="HTML")
        await state.set_state(RevokeAccessStates.waiting_for_user_id)
    except ValueError:
        await message.answer("❌ Введите числовой ID")

@dp.message(RevokeAccessStates.waiting_for_user_id)
async def priv_revoke_user(message: types.Message, state: FSMContext):
    try:
        uid  = int(message.text.strip())
        d    = await state.get_data()
        q_id = d["quiz_id"]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM private_test_access WHERE user_id=? AND quiz_id=?", (uid, q_id)
            )
            await db.commit()
        await message.answer(f"✅ Доступ к тесту #{q_id} у {uid} отозван.")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите числовой user_id")

@dp.callback_query(F.data == "priv_list")
async def priv_list(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT p.quiz_id, q.title, p.user_id, u.username
            FROM private_test_access p
            JOIN quizzes q ON p.quiz_id=q.id
            LEFT JOIN users u ON p.user_id=u.user_id
            ORDER BY p.quiz_id
        """) as c:
            rows = await c.fetchall()
    if not rows:
        return await callback.answer("Нет приватных доступов", show_alert=True)
    text = "🔐 <b>Приватные доступы:</b>\n\n"
    for q_id, title, uid, uname in rows:
        ustr = f"@{uname}" if uname else str(uid)
        text += f"#{q_id} «{title}» → {ustr}\n"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_private"))
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

# --- ВЫДАТЬ ПРЕМИУМ ---
@dp.callback_query(F.data == "adm_premium")
async def adm_give_premium(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("🎁 Введите <b>ID пользователя</b>:", parse_mode="HTML")
    await state.set_state(PremiumStates.waiting_for_user_id)

@dp.message(PremiumStates.waiting_for_user_id)
async def adm_premium_id(message: types.Message, state: FSMContext):
    try:
        await state.update_data(target_uid=int(message.text.strip()))
        await message.answer("📅 На сколько <b>дней</b>?", parse_mode="HTML")
        await state.set_state(PremiumStates.waiting_for_days)
    except ValueError:
        await message.answer("❌ Числовой ID")

@dp.message(PremiumStates.waiting_for_days)
async def adm_premium_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        d    = await state.get_data()
        uid  = d["target_uid"]
        await grant_premium(uid, days)
        await message.answer(
            f"✅ Премиум на <b>{days} дней</b> выдан <b>{uid}</b>", parse_mode="HTML"
        )
        try:
            await bot.send_message(
                uid,
                f"🎉 Вам выдан <b>Премиум на {days} дней</b>!\nВсе тесты и разбор ошибок доступны.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число дней")

# --- СТАТИСТИКА ---
@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_u = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_premium=1") as c:
            prem_u  = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM quizzes") as c:
            total_q = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM results") as c:
            total_r = (await c.fetchone())[0]
        async with db.execute("SELECT AVG(percent) FROM results") as c:
            avg_pct = (await c.fetchone())[0] or 0
        async with db.execute("SELECT COUNT(*) FROM referrals") as c:
            total_ref = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM purchased_tests") as c:
            total_pur = (await c.fetchone())[0]

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: <b>{total_u}</b>\n"
        f"💎 Премиум: <b>{prem_u}</b>\n"
        f"📚 Тестов: <b>{total_q}</b>\n"
        f"📝 Прохождений: <b>{total_r}</b>\n"
        f"📈 Средний %: <b>{avg_pct:.1f}%</b>\n"
        f"👥 Рефералов: <b>{total_ref}</b>\n"
        f"⭐ Покупок Stars: <b>{total_pur}</b>",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

# --- АКТИВНОСТЬ ПОЛЬЗОВАТЕЛЕЙ ---
@dp.callback_query(F.data == "adm_activity")
async def adm_activity(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        # Последние 10 активных пользователей
        async with db.execute("""
            SELECT u.user_id, u.username, u.first_name, u.last_activity,
                   r.quiz_id, q.title, r.score, r.total, r.wrong, r.missed, r.finished
            FROM users u
            LEFT JOIN results r ON u.user_id=r.user_id
            LEFT JOIN quizzes q ON r.quiz_id=q.id
            WHERE u.last_activity IS NOT NULL
            ORDER BY u.last_activity DESC
            LIMIT 10
        """) as c:
            rows = await c.fetchall()

    if not rows:
        return await callback.answer("Нет данных об активности", show_alert=True)

    text = "👥 <b>Последние активные пользователи:</b>\n\n"
    for uid, uname, fname, last_act, q_id, qtitle, score, total, wrong, missed, fin in rows:
        ustr = f"@{uname}" if uname else (fname or str(uid))
        t    = last_act[:16] if last_act else "—"
        text += f"👤 <b>{ustr}</b> · {t}\n"
        if qtitle:
            flag = "✅" if fin else "⚠️ прерван"
            text += f"   📘 {qtitle} — {score}/{total} {flag}\n"
        text += "\n"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

# ============================================================
# КАНАЛЫ ПОДПИСКИ
# ============================================================
@dp.callback_query(F.data == "adm_channels")
async def adm_channels(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    force    = await is_force_subscription_enabled()
    channels = await get_required_channels()
    status   = "✅ включена" if force else "❌ выключена"
    ch_text  = "\n".join(f"{i+1}. {ch}" for i, ch in enumerate(channels)) if channels else "Каналов нет"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Добавить", callback_data="ch_add"))
    b.row(
        InlineKeyboardButton(text="🗑 Удалить",   callback_data="ch_del"),
        InlineKeyboardButton(text="📋 Список",    callback_data="ch_list")
    )
    if force:
        b.row(InlineKeyboardButton(text="❌ Выключить подписку", callback_data="ch_disable"))
    else:
        b.row(InlineKeyboardButton(text="✅ Включить подписку",  callback_data="ch_enable"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(
        f"📢 <b>Каналы подписки</b>\n\nСтатус: <b>{status}</b>\n\n{ch_text}",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data == "ch_add")
async def ch_add(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("📢 Username канала (например: <code>@channel</code>):",
                                   parse_mode="HTML")
    await state.set_state(ChannelStates.waiting_for_channel)

@dp.message(ChannelStates.waiting_for_channel)
async def ch_save(message: types.Message, state: FSMContext):
    ch = message.text.strip()
    if not ch.startswith("@"):
        ch = "@" + ch
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO subscription_channels (channel_username) VALUES(?)", (ch,))
            await db.commit()
            await message.answer(f"✅ Канал <b>{ch}</b> добавлен!", parse_mode="HTML")
        except Exception:
            await message.answer(f"⚠️ Канал <b>{ch}</b> уже есть.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "ch_del")
async def ch_del_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    channels = await get_required_channels()
    if not channels:
        return await callback.answer("Каналов нет", show_alert=True)
    b = InlineKeyboardBuilder()
    for ch in channels:
        b.row(InlineKeyboardButton(text=f"🗑 {ch}", callback_data=f"ch_remove_{ch}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_channels"))
    await callback.message.edit_text("Выберите канал:", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("ch_remove_"))
async def ch_remove(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    ch = callback.data.replace("ch_remove_", "")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subscription_channels WHERE channel_username=?", (ch,))
        await db.commit()
    await callback.answer(f"✅ {ch} удалён", show_alert=True)
    await ch_del_list(callback)

@dp.callback_query(F.data == "ch_list")
async def ch_list(callback: types.CallbackQuery):
    channels = await get_required_channels()
    force    = await is_force_subscription_enabled()
    ch_text  = "\n".join(f"{i+1}. {ch}" for i, ch in enumerate(channels)) if channels else "Нет"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_channels"))
    await callback.message.edit_text(
        f"📋 <b>Обязательные каналы:</b>\n\n{ch_text}\n\n"
        f"Подписка: <b>{'✅ включена' if force else '❌ выключена'}</b>",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data == "ch_enable")
async def ch_enable(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE settings SET value='true' WHERE key='force_subscription'")
        await db.commit()
    await callback.answer("✅ Подписка включена", show_alert=True)
    await adm_channels(callback)

@dp.callback_query(F.data == "ch_disable")
async def ch_disable(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE settings SET value='false' WHERE key='force_subscription'")
        await db.commit()
    await callback.answer("❌ Подписка выключена", show_alert=True)
    await adm_channels(callback)

# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    await init_db()
    logger.info("✅ Бот запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
