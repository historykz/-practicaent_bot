"""
ENT Quiz Bot — полная платформа v4
Python + aiogram 3 + aiosqlite

Новое в v4:
- Разделы предметов (динамические, из БД)
- Мультиязычность RU / KK
- Роли: super_admin, section_admin, user
- Подписка на канал по каждому разделу
- Система апелляций
- Ограниченные попытки для приватных тестов
- Групповой режим через Inline Mode
- Покупка за Telegram Stars
- Полный разбор ошибок и статистика
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
    raise ValueError("BOT_TOKEN не задан! Установите переменную окружения BOT_TOKEN.")

BOT_USERNAME     = "practicaent_bot"
SUPER_ADMIN_IDS  = [5048547918]
MANAGER_LINK     = "@historyentk_bot"

DB_PATH              = "ent_bot.db"
QUESTION_TIMEOUT     = 30
GROUP_MIN_PLAYERS    = 2
PRIVATE_MAX_ATTEMPTS = 2
REFERRAL_BONUS_COUNT = 3
REFERRAL_BONUS_DAYS  = 7

bot = Bot(token=BOT_TOKEN)
dp  = Dispatcher()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# ПЕРЕВОДЫ (i18n)
# ============================================================
TEXTS = {
    "choose_lang": {
        "ru": "🌐 Выберите язык / Тілді таңдаңыз",
        "kk": "🌐 Выберите язык / Тілді таңдаңыз",
    },
    "welcome": {
        "ru": "👋 Привет, <b>{name}</b>!\nРад, что ты с нами практикуешься!\n\nЗдесь ты можешь проходить тесты, тренировать знания и улучшать результаты. 🚀",
        "kk": "👋 Сәлем, <b>{name}</b>!\nБізбен жаттығып жатқаның жақсы!\n\nМұнда сіз тест тапсырып, білімді жетілдіре аласыз. 🚀",
    },
    "main_menu": {
        "ru": "🏠 <b>Главное меню</b>\n\nВыберите раздел:",
        "kk": "🏠 <b>Басты мәзір</b>\n\nБөлімді таңдаңыз:",
    },
    "btn_sections":   {"ru": "📚 Разделы",          "kk": "📚 Бөлімдер"},
    "btn_results":    {"ru": "📊 Мои результаты",    "kk": "📊 Менің нәтижелерім"},
    "btn_invite":     {"ru": "👥 Пригласить друзей", "kk": "👥 Достарды шақыру"},
    "btn_help":       {"ru": "ℹ️ Помощь",            "kk": "ℹ️ Көмек"},
    "btn_collab":     {"ru": "🤝 Сотрудничать",      "kk": "🤝 Ынтымақтасу"},
    "btn_manager":    {"ru": "👨‍💼 Менеджер",          "kk": "👨‍💼 Менеджер"},
    "btn_admin":      {"ru": "⚙️ Админ-панель",       "kk": "⚙️ Әкімші панелі"},
    "btn_back":       {"ru": "🔙 Назад",              "kk": "🔙 Артқа"},
    "btn_start_test": {"ru": "▶️ Начать тест",        "kk": "▶️ Тест бастау"},
    "btn_share_test": {"ru": "📤 Поделиться",          "kk": "📤 Бөлісу"},
    "btn_group_test": {"ru": "👥 Пройти в группе",    "kk": "👥 Топта өту"},
    "btn_pause":      {"ru": "⏸ Приостановить",       "kk": "⏸ Тоқтата тұру"},
    "btn_finish":     {"ru": "⛔ Завершить тест",      "kk": "⛔ Тестті аяқтау"},
    "btn_appeal":     {"ru": "⚖️ Апелляция",           "kk": "⚖️ Апелляция"},
    "btn_resume":     {"ru": "▶️ Продолжить",          "kk": "▶️ Жалғастыру"},
    "btn_premium":    {"ru": "💎 О Премиуме",          "kk": "💎 Премиум туралы"},
    "btn_to_tests":   {"ru": "📚 К тестам",            "kk": "📚 Тесттерге"},
    "subscribe_required": {
        "ru": "📢 <b>Для доступа к бесплатным тестам</b> подпишитесь на канал раздела, затем нажмите «✅ Я подписался».",
        "kk": "📢 <b>Тегін тесттерге кіру үшін</b> бөлім каналына жазылыңыз, содан кейін «✅ Жазылдым» басыңыз.",
    },
    "btn_subscribed": {"ru": "✅ Я подписался",        "kk": "✅ Жазылдым"},
    "sub_ok": {
        "ru": "✅ <b>Спасибо за подписку!</b>\n\nБесплатные тесты уже доступны.\n\n💎 <b>Хотите большего?</b> Подключите Премиум:\n• Все платные тесты\n• Разбор ошибок\n• Приватные материалы\n• Расширенная статистика",
        "kk": "✅ <b>Жазылғаныңыз үшін рахмет!</b>\n\nТегін тесттер қолжетімді.\n\n💎 <b>Көбірек қалайсыз ба?</b> Премиум қосыңыз:\n• Барлық ақылы тесттер\n• Қателерді талдау\n• Жеке материалдар\n• Кеңейтілген статистика",
    },
    "sub_fail": {
        "ru": "Вы ещё не подписаны. Подпишитесь и нажмите снова.",
        "kk": "Сіз әлі жазылмадыңыз. Жазылып, қайта басыңыз.",
    },
    "no_access": {
        "ru": "🔒 Нет доступа к этому тесту.",
        "kk": "🔒 Бұл тестке қол жетімділік жоқ.",
    },
    "test_start": {
        "ru": "🚀 Начинаем тест <b>«{title}»</b>!\n📝 {total} вопросов · ⏱ {timeout} сек\n\nУдачи! 🍀",
        "kk": "🚀 <b>«{title}»</b> тесті басталды!\n📝 {total} сұрақ · ⏱ {timeout} сек\n\nСәттілік! 🍀",
    },
    "test_paused": {
        "ru": "⏸ <b>Тест приостановлен.</b>\n\nНажмите «▶️ Продолжить» когда будете готовы.",
        "kk": "⏸ <b>Тест тоқтатылды.</b>\n\nДайын болғанда «▶️ Жалғастыру» басыңыз.",
    },
    "two_missed": {
        "ru": "⚠️ Вы пропустили 2 вопроса подряд. Что делаем дальше?",
        "kk": "⚠️ Сіз қатарынан 2 сұрақты өткізіп жібердіңіз. Не істейміз?",
    },
    "result_title": {
        "ru": "{emoji} <b>Тест «{title}» завершён!</b>\n\n✅ Правильных: <b>{correct}</b>\n❌ Неправильных: <b>{wrong}</b>\n⏭ Пропущенных: <b>{missed}</b>\n\n📊 Результат: <b>{percent}%</b>",
        "kk": "{emoji} <b>«{title}» тесті аяқталды!</b>\n\n✅ Дұрыс: <b>{correct}</b>\n❌ Қате: <b>{wrong}</b>\n⏭ Өткізілген: <b>{missed}</b>\n\n📊 Нәтиже: <b>{percent}%</b>",
    },
    "result_early": {
        "ru": "⛔ <b>Тест завершён досрочно.</b>\n\n📘 {title}\n📝 Всего: <b>{total}</b>\n✅ Правильных: <b>{correct}</b>\n❌ Неправильных: <b>{wrong}</b>\n⏭ Пропущенных: <b>{missed}</b>\n📌 Не завершено: <b>{remaining}</b>\n\n📊 Результат: <b>{percent}%</b>",
        "kk": "⛔ <b>Тест мерзімінен бұрын аяқталды.</b>\n\n📘 {title}\n📝 Барлығы: <b>{total}</b>\n✅ Дұрыс: <b>{correct}</b>\n❌ Қате: <b>{wrong}</b>\n⏭ Өткізілген: <b>{missed}</b>\n📌 Аяқталмаған: <b>{remaining}</b>\n\n📊 Нәтиже: <b>{percent}%</b>",
    },
    "no_results": {
        "ru": "📊 У вас пока нет результатов. Пройдите первый тест! 📚",
        "kk": "📊 Сізде әзірше нәтиже жоқ. Алғашқы тестті тапсырыңыз! 📚",
    },
    "appeal_prompt": {
        "ru": "⚖️ <b>Апелляция</b>\n\nТест приостановлен. Опишите проблему с вопросом #{num}:",
        "kk": "⚖️ <b>Апелляция</b>\n\nТест тоқтатылды. #{num} сұрақтың мәселесін сипаттаңыз:",
    },
    "appeal_sent": {
        "ru": "✅ Апелляция отправлена администратору. Тест продолжается.",
        "kk": "✅ Апелляция әкімшіге жіберілді. Тест жалғасады.",
    },
    "paid_no_share": {
        "ru": "🔒 Платные тесты доступны только внутри бота.",
        "kk": "🔒 Ақылы тесттер тек ботта ғана қолжетімді.",
    },
    "no_attempts": {
        "ru": "❌ У вас исчерпаны попытки для этого теста. Обратитесь к администратору.",
        "kk": "❌ Бұл тестке сіздің әрекеттеріңіз таусылды. Әкімшіге хабарласыңыз.",
    },
    "sections_list": {
        "ru": "📚 <b>Разделы</b>\n\nВыберите предмет:",
        "kk": "📚 <b>Бөлімдер</b>\n\nПәнді таңдаңыз:",
    },
    "help_text": {
        "ru": (
            "ℹ️ <b>Помощь</b>\n\n"
            "📚 <b>Как проходить тесты?</b>\n"
            "Выберите раздел → тест → нажмите «Начать».\n"
            "На каждый вопрос 30 сек. Ответили раньше — следующий сразу.\n\n"
            "🆓 <b>Как открыть бесплатные тесты?</b>\n"
            "Подпишитесь на канал раздела.\n\n"
            "💎 <b>Как купить платный доступ?</b>\n"
            "Нажмите «О Премиуме» или свяжитесь с менеджером.\n\n"
            "👥 <b>Тест в группе?</b>\n"
            "Только бесплатные тесты. Нажмите «Пройти в группе».\n\n"
            "🤝 <b>Сотрудничество:</b> @historyentk_bot"
        ),
        "kk": (
            "ℹ️ <b>Көмек</b>\n\n"
            "📚 <b>Тестті қалай тапсыруға болады?</b>\n"
            "Бөлімді таңдаңыз → тест → «Бастау» басыңыз.\n"
            "Әр сұраққа 30 сек. Ертерек жауап берсеңіз — келесі бірден келеді.\n\n"
            "🆓 <b>Тегін тесттерді қалай ашуға болады?</b>\n"
            "Бөлім каналына жазылыңыз.\n\n"
            "💎 <b>Ақылы қолжетімділікті сатып алу?</b>\n"
            "«Премиум туралы» немесе менеджерге хабарласыңыз.\n\n"
            "👥 <b>Топтағы тест?</b>\n"
            "Тек тегін тесттер. «Топта өту» басыңыз.\n\n"
            "🤝 <b>Ынтымақтасу:</b> @historyentk_bot"
        ),
    },
}

def t(key: str, lang: str, **kwargs) -> str:
    """Получить перевод строки."""
    text = TEXTS.get(key, {}).get(lang) or TEXTS.get(key, {}).get("ru", key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text

# ============================================================
# СТРУКТУРА АКТИВНОЙ СЕССИИ
# ============================================================
@dataclass
class QuizSession:
    user_id: int
    chat_id: int
    quiz_id: int
    section_id: int
    quiz_title: str
    questions: list
    lang: str = "ru"
    current_index: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    missed_count: int = 0
    consecutive_missed: int = 0
    wrong_questions: list  = field(default_factory=list)
    missed_questions: list = field(default_factory=list)
    current_poll_id: Optional[str] = None
    control_message_id: Optional[int] = None
    active: bool   = True
    paused: bool   = False
    finished: bool = False
    appeal_pending: bool = False
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

active_sessions: dict[int, QuizSession] = {}
group_sessions:  dict[int, dict]        = {}  # {chat_id: {...}}
quiz_buffers:    dict[int, dict]        = {}  # {admin_id: {...}}

# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================
class LangStates(StatesGroup):
    choosing = State()

class QuizStates(StatesGroup):
    waiting_for_title    = State()
    collecting_questions = State()
    fixing_fragment      = State()

class AppealStates(StatesGroup):
    waiting_for_text = State()

class AdminStates(StatesGroup):
    # Секции
    section_title_ru = State()
    section_title_kk = State()
    section_channel  = State()
    # Тесты
    quiz_section     = State()
    quiz_title       = State()
    quiz_collecting  = State()
    quiz_fixing      = State()
    # Доступ
    premium_uid      = State()
    premium_days     = State()
    stars_quiz_id    = State()
    stars_price      = State()
    private_quiz_id  = State()
    private_uid      = State()
    revoke_quiz_id   = State()
    revoke_uid       = State()
    reset_attempts_uid = State()
    section_admin_uid  = State()
    section_admin_sid  = State()
    appeal_reply       = State()
    channel_section_id = State()
    channel_username   = State()
    edit_section_id    = State()
    edit_section_field = State()
    edit_section_value = State()
    edit_quiz_id       = State()

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
                language TEXT DEFAULT 'ru',
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                invited_by INTEGER,
                last_active_at TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title_ru TEXT,
                title_kk TEXT,
                is_active INTEGER DEFAULT 1,
                required_channel_username TEXT,
                require_subscription INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS section_admins (
                user_id INTEGER,
                section_id INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(user_id, section_id)
            );
            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                section_id INTEGER,
                title TEXT,
                data TEXT,
                access_type TEXT DEFAULT 'free',
                stars_price INTEGER DEFAULT 0,
                created_by INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS purchased_tests (
                user_id INTEGER,
                quiz_id INTEGER,
                purchased_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(user_id, quiz_id)
            );
            CREATE TABLE IF NOT EXISTS private_access (
                user_id INTEGER,
                quiz_id INTEGER,
                granted_by INTEGER,
                max_attempts INTEGER DEFAULT 2,
                used_attempts INTEGER DEFAULT 0,
                granted_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY(user_id, quiz_id)
            );
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                quiz_id INTEGER,
                section_id INTEGER,
                attempt_number INTEGER DEFAULT 1,
                score INTEGER,
                total INTEGER,
                wrong INTEGER DEFAULT 0,
                missed INTEGER DEFAULT 0,
                unfinished INTEGER DEFAULT 0,
                percent REAL,
                mode TEXT DEFAULT 'private',
                finished INTEGER DEFAULT 1,
                completed_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS appeals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                quiz_id INTEGER,
                question_index INTEGER,
                message TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                handled_by INTEGER,
                handled_at TEXT
            );
            CREATE TABLE IF NOT EXISTS referrals (
                inviter_id INTEGER,
                invited_user_id INTEGER PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS group_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                quiz_id INTEGER,
                created_by INTEGER,
                status TEXT DEFAULT 'waiting',
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await db.commit()


# ============================================================
# ПАРСЕР ТЕСТОВ
# ============================================================
def clean_option(text: str) -> str:
    return text.lstrip('*').strip()

def parse_quiz_data(text: str) -> tuple[list, str]:
    """Парсит текст вопросов. Возвращает (список, ошибка)."""
    questions, blocks = [], text.strip().split('\n\n')
    for n, block in enumerate(blocks, 1):
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3:
            continue
        opts, correct = [], None
        for line in lines[1:]:
            is_ok   = line.startswith('*')
            cleaned = clean_option(line)
            if not cleaned:
                continue
            if is_ok:
                if correct is not None:
                    return [], f"Блок {n}: более одного правильного ответа."
                correct = len(opts)
            opts.append(cleaned)
        if len(opts) < 2:
            return [], f"Блок {n}: минимум 2 варианта ответа."
        if correct is None:
            return [], f"Блок {n}: нет правильного ответа (поставьте * перед ним)."
        questions.append({"q": lines[0], "opts": opts, "correct": correct})
    if not questions:
        return [], "Ни одного вопроса не распознано. Проверьте формат."
    return questions, ""

def clean_quiz_data(data: list) -> list:
    for q in data:
        q['opts'] = [clean_option(o) for o in q['opts']]
    return data

def count_questions_in_text(text: str) -> int:
    return len([b for b in text.strip().split('\n\n')
                if len([l for l in b.split('\n') if l.strip()]) >= 3])

def detect_error_block(raw: str, error: str) -> str:
    """Возвращает превью проблемного блока для отображения."""
    blocks = raw.strip().split('\n\n')
    for n, block in enumerate(blocks, 1):
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3:
            return f"\n\n📌 Блок {n} слишком короткий:\n<code>{block[:100]}</code>"
        opts = [l for l in lines[1:] if l.strip()]
        correct = [l for l in opts if l.startswith('*')]
        if len(opts) < 2:
            return f"\n\n📌 Блок {n} — меньше 2 вариантов:\n<code>{block[:100]}</code>"
        if not correct:
            return f"\n\n📌 Блок {n} — нет * перед правильным ответом:\n<code>{block[:100]}</code>"
        if len(correct) > 1:
            return f"\n\n📌 Блок {n} — несколько вариантов со *:\n<code>{block[:100]}</code>"
    return ""


# ============================================================
# УТИЛИТЫ — ПОЛЬЗОВАТЕЛИ
# ============================================================
async def register_user(user: types.User, invited_by: int = None) -> str:
    """Регистрирует пользователя если нет, возвращает язык."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT language FROM users WHERE user_id=?", (user.id,)) as c:
            row = await c.fetchone()
        now = datetime.now().isoformat()
        if not row:
            await db.execute(
                "INSERT INTO users (user_id,username,first_name,invited_by,last_active_at) VALUES(?,?,?,?,?)",
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
                            f"🎁 Вы пригласили <b>{cnt}</b> друзей — <b>{REFERRAL_BONUS_DAYS} дней Премиума</b>!",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
            await db.commit()
            return None  # новый пользователь — нужно спросить язык
        else:
            await db.execute("UPDATE users SET last_active_at=? WHERE user_id=?", (now, user.id))
            await db.commit()
            return row[0]

async def get_user_lang(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT language FROM users WHERE user_id=?", (user_id,)) as c:
            row = await c.fetchone()
    return row[0] if row else "ru"

async def set_user_lang(user_id: int, lang: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET language=? WHERE user_id=?", (lang, user_id))
        await db.commit()

async def touch_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_active_at=? WHERE user_id=?",
                         (datetime.now().isoformat(), user_id))
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
    if user_id in SUPER_ADMIN_IDS:
        return True
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
# УТИЛИТЫ — РОЛИ
# ============================================================
async def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS

async def get_admin_sections(user_id: int) -> list[int]:
    """Список section_id, которыми управляет этот admin."""
    if user_id in SUPER_ADMIN_IDS:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT id FROM sections") as c:
                return [r[0] for r in await c.fetchall()]
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT section_id FROM section_admins WHERE user_id=?", (user_id,)
        ) as c:
            return [r[0] for r in await c.fetchall()]

async def is_any_admin(user_id: int) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM section_admins WHERE user_id=?", (user_id,)
        ) as c:
            return bool(await c.fetchone())


# ============================================================
# УТИЛИТЫ — РАЗДЕЛЫ
# ============================================================
async def get_sections(active_only: bool = True) -> list:
    q = "SELECT id,title_ru,title_kk,require_subscription,required_channel_username FROM sections"
    if active_only:
        q += " WHERE is_active=1"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(q) as c:
            return await c.fetchall()

async def get_section(section_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id,title_ru,title_kk,require_subscription,required_channel_username FROM sections WHERE id=?",
            (section_id,)
        ) as c:
            return await c.fetchone()


# ============================================================
# УТИЛИТЫ — ПОДПИСКА
# ============================================================
async def check_section_subscription(user_id: int, section_id: int) -> tuple[bool, str]:
    """Возвращает (подписан, channel_username_or_empty)."""
    row = await get_section(section_id)
    if not row:
        return True, ""
    _, _, _, require_sub, channel = row
    if not require_sub or not channel:
        return True, ""
    try:
        m = await bot.get_chat_member(channel, user_id)
        if m.status in ("member", "administrator", "creator"):
            return True, channel
    except Exception as e:
        logger.warning(f"Проверка подписки {user_id}@{channel}: {e}")
    return False, channel


# ============================================================
# УТИЛИТЫ — ТЕСТЫ И ДОСТУП
# ============================================================
async def get_quiz(q_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id,section_id,title,data,access_type,stars_price,created_by FROM quizzes WHERE id=?",
            (q_id,)
        ) as c:
            return await c.fetchone()

async def get_section_quizzes(section_id: int, user_id: int) -> list:
    """Тесты раздела, видимые пользователю."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id,title,access_type,stars_price FROM quizzes WHERE section_id=? AND is_active=1",
            (section_id,)
        ) as c:
            all_q = await c.fetchall()
        async with db.execute(
            "SELECT quiz_id FROM private_access WHERE user_id=?", (user_id,)
        ) as c:
            priv_access = {r[0] for r in await c.fetchall()}
    result = []
    for q_id, title, atype, sp in all_q:
        if atype == 'private' and q_id not in priv_access:
            continue
        result.append((q_id, title, atype, sp))
    return result

async def has_quiz_access(user_id: int, q_id: int, access_type: str, stars_price: int) -> tuple[bool, str]:
    """Возвращает (доступ, причина_отказа)."""
    if access_type == 'free':
        return True, ""
    is_prem = await check_premium(user_id)
    if access_type == 'premium':
        return is_prem, "premium"
    if access_type == 'stars':
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM purchased_tests WHERE user_id=? AND quiz_id=?", (user_id, q_id)
            ) as c:
                bought = await c.fetchone()
        return bool(bought) or is_prem, "stars"
    if access_type == 'private':
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT max_attempts, used_attempts FROM private_access WHERE user_id=? AND quiz_id=?",
                (user_id, q_id)
            ) as c:
                pa = await c.fetchone()
        if not pa:
            return False, "private_no_access"
        max_a, used_a = pa
        if used_a >= max_a:
            return False, "private_no_attempts"
        return True, ""
    return False, "unknown"

async def increment_private_attempt(user_id: int, quiz_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE private_access SET used_attempts=used_attempts+1 WHERE user_id=? AND quiz_id=?",
            (user_id, quiz_id)
        )
        await db.commit()

async def get_next_attempt_number(user_id: int, quiz_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM results WHERE user_id=? AND quiz_id=?", (user_id, quiz_id)
        ) as c:
            cnt = (await c.fetchone())[0]
    return cnt + 1

async def save_result(session: "QuizSession", finished: bool = True):
    attempt = await get_next_attempt_number(session.user_id, session.quiz_id)
    remaining = session.unanswered_remaining
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO results
               (user_id,quiz_id,section_id,attempt_number,score,total,wrong,missed,
                unfinished,percent,mode,finished,completed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            (session.user_id, session.quiz_id, session.section_id,
             attempt, session.correct_count, len(session.questions),
             session.wrong_count, session.missed_count,
             remaining, session.percent, "private", 1 if finished else 0)
        )
        await db.commit()


# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def lang_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🇷🇺 Русский",   callback_data="lang_ru"))
    b.row(InlineKeyboardButton(text="🇰🇿 Қазақша",   callback_data="lang_kk"))
    return b.as_markup()

def main_menu_kb(lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t("btn_sections", lang),  callback_data="menu_sections"))
    b.row(InlineKeyboardButton(text=t("btn_results",  lang),  callback_data="menu_results"))
    b.row(InlineKeyboardButton(text=t("btn_invite",   lang),  callback_data="menu_invite"))
    b.row(
        InlineKeyboardButton(text=t("btn_help",   lang), callback_data="menu_help"),
        InlineKeyboardButton(text=t("btn_collab", lang), url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"),
    )
    b.row(InlineKeyboardButton(text=t("btn_manager", lang),
                                url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"))
    if is_admin:
        b.row(InlineKeyboardButton(text=t("btn_admin", lang), callback_data="admin_panel"))
    return b.as_markup()

def back_kb(lang: str, cb: str = "to_main") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t("btn_back", lang), callback_data=cb))
    return b.as_markup()

def quiz_control_kb(lang: str, paused: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if paused:
        b.row(InlineKeyboardButton(text=t("btn_resume", lang), callback_data="quiz_resume"))
        b.row(InlineKeyboardButton(text=t("btn_finish", lang), callback_data="quiz_finish"))
    else:
        b.row(
            InlineKeyboardButton(text=t("btn_pause",  lang), callback_data="quiz_pause"),
            InlineKeyboardButton(text=t("btn_finish", lang), callback_data="quiz_finish"),
        )
        b.row(InlineKeyboardButton(text=t("btn_appeal", lang), callback_data="quiz_appeal"))
    return b.as_markup()

def missed_kb(lang: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t("btn_resume", lang), callback_data="quiz_resume"))
    b.row(InlineKeyboardButton(text=t("btn_finish", lang), callback_data="quiz_finish"))
    return b.as_markup()

def collecting_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="💾 Сохранить тест", callback_data="quiz_buf_save"))
    b.row(
        InlineKeyboardButton(text="🗑 Очистить всё", callback_data="quiz_buf_clear"),
        InlineKeyboardButton(text="❌ Отмена",        callback_data="quiz_buf_cancel"),
    )
    return b.as_markup()

def error_fragment_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🗑 Убрать фрагмент",  callback_data="frag_drop"))
    b.row(InlineKeyboardButton(text="✏️ Исправить заново", callback_data="frag_retry"))
    b.row(InlineKeyboardButton(text="➕ Продолжить",        callback_data="frag_continue"))
    b.row(InlineKeyboardButton(text="💾 Сохранить тест",   callback_data="quiz_buf_save"))
    b.row(InlineKeyboardButton(text="❌ Отмена",            callback_data="quiz_buf_cancel"))
    return b.as_markup()

# ============================================================
# /start — ЯЗЫК — МЕНЮ
# ============================================================
async def show_main_menu(target, user_id: int, lang: str, edit: bool = False):
    is_admin = await is_any_admin(user_id)
    text = t("main_menu", lang)
    kb   = main_menu_kb(lang, is_admin)
    if edit and isinstance(target, types.CallbackQuery):
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    elif isinstance(target, types.Message):
        await target.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
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
            lang = await get_user_lang(message.from_user.id)
            await register_user(message.from_user)
            try:
                q_id = int(param.split("_")[1])
                await launch_quiz(message.chat.id, message.from_user.id, q_id, lang)
            except (IndexError, ValueError):
                pass
            return

    lang = await register_user(message.from_user, invited_by)
    if lang is None:
        # Новый пользователь — спрашиваем язык
        await message.answer(t("choose_lang", "ru"), reply_markup=lang_kb())
        await state.set_state(LangStates.choosing)
        return

    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    await message.answer(t("welcome", lang, name=name), parse_mode="HTML")
    await show_main_menu(message, message.from_user.id, lang)

@dp.callback_query(F.data.startswith("lang_"))
async def choose_lang(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    await set_user_lang(callback.from_user.id, lang)
    await state.clear()
    name = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.first_name
    await callback.message.edit_text(t("welcome", lang, name=name), parse_mode="HTML")
    await show_main_menu(callback.message, callback.from_user.id, lang)

@dp.callback_query(F.data == "to_main")
async def to_main(callback: types.CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    await show_main_menu(callback, callback.from_user.id, lang, edit=True)


# ============================================================
# РАЗДЕЛЫ
# ============================================================
@dp.callback_query(F.data == "menu_sections")
async def menu_sections(callback: types.CallbackQuery):
    lang     = await get_user_lang(callback.from_user.id)
    sections = await get_sections()
    if not sections:
        return await callback.answer("Разделов пока нет", show_alert=True)

    b = InlineKeyboardBuilder()
    for s_id, title_ru, title_kk, _, _ in sections:
        title = title_kk if lang == "kk" else title_ru
        b.row(InlineKeyboardButton(text=title, callback_data=f"section_{s_id}"))
    b.row(InlineKeyboardButton(text=t("btn_back", lang), callback_data="to_main"))

    await callback.message.edit_text(t("sections_list", lang),
                                      reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("section_"))
async def section_view(callback: types.CallbackQuery):
    uid      = callback.from_user.id
    lang     = await get_user_lang(uid)
    s_id     = int(callback.data.split("_")[1])
    sec      = await get_section(s_id)
    if not sec:
        return await callback.answer("Раздел не найден", show_alert=True)

    _, title_ru, title_kk, require_sub, channel = sec
    title = title_kk if lang == "kk" else title_ru

    # Проверяем подписку для бесплатных тестов
    if require_sub and channel:
        ok, ch = await check_section_subscription(uid, s_id)
        if not ok:
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(text=f"📢 {ch}", url=f"https://t.me/{ch.lstrip('@')}"))
            b.row(InlineKeyboardButton(text=t("btn_subscribed", lang),
                                        callback_data=f"check_sub_{s_id}"))
            b.row(InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu_sections"))
            await callback.message.edit_text(
                t("subscribe_required", lang),
                reply_markup=b.as_markup(), parse_mode="HTML"
            )
            return

    await show_section_tests(callback.message, uid, s_id, title, lang, edit=True)

async def show_section_tests(msg, uid: int, s_id: int, title: str, lang: str, edit: bool = False):
    quizzes    = await get_section_quizzes(s_id, uid)
    is_prem    = await check_premium(uid)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT DISTINCT quiz_id FROM results WHERE user_id=?", (uid,)
        ) as c:
            done = {r[0] for r in await c.fetchall()}
        async with db.execute(
            "SELECT quiz_id FROM purchased_tests WHERE user_id=?", (uid,)
        ) as c:
            bought = {r[0] for r in await c.fetchall()}

    b = InlineKeyboardBuilder()
    access_icons = {"free": "📖", "premium": "🔒", "stars": "⭐", "private": "🔐"}

    for q_id, qtitle, atype, sp in quizzes:
        icon = "✅" if q_id in done else access_icons.get(atype, "📖")
        label = qtitle
        if atype == "stars" and q_id not in bought and not is_prem:
            label = f"{label} ({sp}⭐)"
        b.row(InlineKeyboardButton(text=f"{icon} {label}", callback_data=f"info_{q_id}"))

    b.row(InlineKeyboardButton(text="🔙 Назад" if lang == "ru" else "🔙 Артқа",
                                callback_data="menu_sections"))

    text = f"📚 <b>{title}</b>\n\n✅ пройден | 📖 бесплатно | 🔒 Премиум | ⭐ Stars | 🔐 приватный"
    if lang == "kk":
        text = f"📚 <b>{title}</b>\n\n✅ өтілген | 📖 тегін | 🔒 Премиум | ⭐ Stars | 🔐 жеке"

    if edit:
        await msg.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")
    else:
        await msg.answer(text, reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("check_sub_"))
async def check_sub(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    lang = await get_user_lang(uid)
    s_id = int(callback.data.split("_")[2])
    ok, ch = await check_section_subscription(uid, s_id)

    if ok:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text=t("btn_premium", lang),  callback_data="buy_premium"))
        b.row(InlineKeyboardButton(text=t("btn_to_tests", lang), callback_data=f"section_{s_id}"))
        b.row(InlineKeyboardButton(text=t("btn_manager",  lang),
                                    url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"))
        await callback.message.edit_text(t("sub_ok", lang),
                                          reply_markup=b.as_markup(), parse_mode="HTML")
    else:
        await callback.answer(t("sub_fail", lang), show_alert=True)


# ============================================================
# КАРТОЧКА ТЕСТА
# ============================================================
@dp.callback_query(F.data.startswith("info_"))
async def quiz_info(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    lang = await get_user_lang(uid)
    q_id = int(callback.data.split("_")[1])
    row  = await get_quiz(q_id)
    if not row:
        return await callback.answer("Тест не найден", show_alert=True)

    q_id, s_id, title, data_json, atype, sp, created_by = row
    questions = clean_quiz_data(json.loads(data_json))
    is_prem   = await check_premium(uid)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM purchased_tests WHERE user_id=? AND quiz_id=?", (uid, q_id)
        ) as c:
            bought = await c.fetchone()
        if atype == "private":
            async with db.execute(
                "SELECT max_attempts, used_attempts FROM private_access WHERE user_id=? AND quiz_id=?",
                (uid, q_id)
            ) as c:
                pa = await c.fetchone()
        else:
            pa = None

    access_labels = {
        "free":    "🆓 Бесплатно" if lang == "ru" else "🆓 Тегін",
        "premium": "🔒 Премиум",
        "stars":   f"⭐ {sp} Stars",
        "private": "🔐 Приватный" if lang == "ru" else "🔐 Жеке",
    }
    alabel = access_labels.get(atype, "🆓")
    if atype == "private" and pa:
        max_a, used_a = pa
        left = max(0, max_a - used_a)
        alabel += f" (осталось попыток: {left})" if lang == "ru" else f" (қалған: {left})"

    can_run, reason = await has_quiz_access(uid, q_id, atype, sp)

    b = InlineKeyboardBuilder()
    if can_run:
        b.row(InlineKeyboardButton(text=t("btn_start_test", lang), callback_data=f"run_{q_id}"))
        if atype == "free":
            b.row(InlineKeyboardButton(text=t("btn_share_test", lang),
                                        switch_inline_query=f"quiz_{q_id}"))
            b.row(InlineKeyboardButton(text=t("btn_group_test", lang),
                                        switch_inline_query_chosen_chat=types.SwitchInlineQueryChosenChat(
                                            query=f"group_{q_id}", allow_group_chats=True
                                        )))
    elif reason == "premium":
        b.row(InlineKeyboardButton(text="💎 Купить Премиум", callback_data="buy_premium"))
    elif reason == "stars":
        b.row(InlineKeyboardButton(text=f"⭐ Купить за {sp} Stars",
                                    callback_data=f"buy_stars_{q_id}"))
    elif reason == "private_no_access":
        b.row(InlineKeyboardButton(text="👨‍💼 Запросить доступ",
                                    url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"))
    elif reason == "private_no_attempts":
        b.row(InlineKeyboardButton(text="👨‍💼 Сбросить попытки",
                                    url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"))

    b.row(InlineKeyboardButton(text=t("btn_back", lang), callback_data=f"section_{s_id}"))

    await callback.message.edit_text(
        f"🎯 <b>{title}</b>\n\n"
        f"📝 Вопросов: <b>{len(questions)}</b>\n"
        f"⏱ Время: <b>{QUESTION_TIMEOUT} сек</b>\n"
        f"💰 Доступ: {alabel}",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )


# ============================================================
# ПОКУПКА ПРЕМИУМА
# ============================================================
@dp.callback_query(F.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t("btn_manager", lang),
                                url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"))
    b.row(InlineKeyboardButton(text=t("btn_back", lang), callback_data="menu_sections"))
    await callback.message.edit_text(
        "💎 <b>Премиум доступ</b>\n\n"
        "✔ Все платные тесты\n✔ Разбор ошибок\n"
        "✔ Приватные материалы\n✔ Расширенная статистика\n\n"
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
    _, _, title, _, _, stars_price, _ = row
    if not stars_price:
        return await callback.answer("Цена не установлена", show_alert=True)
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"Тест «{title}»",
        description=f"Разовый доступ к тесту «{title}»",
        payload=f"quiz_{q_id}",
        currency="XTR",
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
        row   = await get_quiz(q_id)
        title = row[2] if row else "тест"
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="▶️ Начать тест", callback_data=f"run_{q_id}"))
        await message.answer(
            f"✅ <b>Оплата прошла!</b>\n\nТест «{title}» теперь доступен.",
            reply_markup=b.as_markup(), parse_mode="HTML"
        )


# ============================================================
# ПОМОЩЬ / ПРИГЛАСИТЬ / РЕЗУЛЬТАТЫ
# ============================================================
@dp.callback_query(F.data == "menu_help")
async def menu_help(callback: types.CallbackQuery):
    lang = await get_user_lang(callback.from_user.id)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t("btn_back", lang), callback_data="to_main"))
    await callback.message.edit_text(t("help_text", lang),
                                      reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "menu_invite")
async def menu_invite(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    lang = await get_user_lang(uid)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (uid,)) as c:
            cnt = (await c.fetchone())[0]
    next_b = REFERRAL_BONUS_COUNT - (cnt % REFERRAL_BONUS_COUNT)
    bonus  = f"🎁 Ещё {next_b} → {REFERRAL_BONUS_DAYS} дней Премиума!" if next_b != REFERRAL_BONUS_COUNT else "🎉 Вы получили бонус!"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(
        text="📤 Поделиться ссылкой" if lang == "ru" else "📤 Сілтемемен бөлісу",
        url=f"https://t.me/share/url?url={ref_link}&text=Готовься к ЕНТ! 📚"
    ))
    b.row(InlineKeyboardButton(text=t("btn_back", lang), callback_data="to_main"))
    await callback.message.edit_text(
        f"👥 <b>{'Пригласить друзей' if lang == 'ru' else 'Достарды шақыру'}</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"{'Приглашено' if lang == 'ru' else 'Шақырылды'}: <b>{cnt}</b>\n\n{bonus}",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data == "menu_results")
async def menu_results(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    lang = await get_user_lang(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT q.title, r.score, r.total, r.wrong, r.missed, r.percent, r.finished, r.attempt_number
            FROM results r JOIN quizzes q ON r.quiz_id=q.id
            WHERE r.user_id=? ORDER BY r.completed_at DESC LIMIT 20
        """, (uid,)) as c:
            results = await c.fetchall()

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=t("btn_back", lang), callback_data="to_main"))

    if not results:
        return await callback.message.edit_text(t("no_results", lang),
                                                 reply_markup=b.as_markup())

    best = max(results, key=lambda x: x[5])
    avg  = round(sum(r[5] for r in results) / len(results))
    text = (
        f"📊 <b>{'Мои результаты' if lang == 'ru' else 'Менің нәтижелерім'}</b>\n\n"
        f"📝 {'Тестов пройдено' if lang == 'ru' else 'Өтілген тесттер'}: <b>{len(results)}</b>\n"
        f"🏅 {'Лучший' if lang == 'ru' else 'Үздік'}: <b>{best[5]:.0f}%</b> — {best[0]}\n"
        f"📈 {'Средний' if lang == 'ru' else 'Орташа'}: <b>{avg}%</b>\n\n{'─'*20}\n\n"
    )
    for title, score, total, wrong, missed, pct, fin, attempt in results:
        em   = "🏆" if pct >= 80 else ("👍" if pct >= 50 else "📚")
        flag = (" ⚠️" if not fin else "")
        text += f"{em} <b>{title}</b> #{attempt}{flag}\n"
        text += f"   ✅{score} ❌{wrong} ⏭{missed} / {total} · <b>{pct:.0f}%</b>\n\n"

    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

# ============================================================
# ЗАПУСК ТЕСТА
# ============================================================
@dp.callback_query(F.data.startswith("run_"))
async def start_quiz_cb(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    lang = await get_user_lang(uid)
    q_id = int(callback.data.split("_")[1])
    row  = await get_quiz(q_id)
    if not row:
        return await callback.answer("Тест не найден", show_alert=True)

    _, s_id, _, _, atype, sp, _ = row
    can_run, reason = await has_quiz_access(uid, q_id, atype, sp)
    if not can_run:
        msg = t("no_attempts", lang) if "attempts" in reason else t("no_access", lang)
        return await callback.answer(msg, show_alert=True)

    if uid in active_sessions:
        return await callback.answer(
            "У вас уже идёт тест. Завершите его." if lang == "ru"
            else "Сізде тест жүруде. Аяқтаңыз.",
            show_alert=True
        )

    await callback.message.delete()
    await launch_quiz(callback.message.chat.id, uid, q_id, lang)

async def launch_quiz(chat_id: int, user_id: int, q_id: int, lang: str):
    row = await get_quiz(q_id)
    if not row:
        await bot.send_message(chat_id, "❌ Тест не найден.")
        return

    q_id, s_id, title, data_json, atype, sp, _ = row
    can_run, reason = await has_quiz_access(user_id, q_id, atype, sp)
    if not can_run:
        await bot.send_message(chat_id, t("no_access", lang))
        return

    if atype == "private":
        await increment_private_attempt(user_id, q_id)

    questions = clean_quiz_data(json.loads(data_json))
    session = QuizSession(
        user_id=user_id, chat_id=chat_id, quiz_id=q_id,
        section_id=s_id, quiz_title=title, questions=questions, lang=lang
    )
    active_sessions[user_id] = session
    await touch_user(user_id)

    await bot.send_message(
        chat_id,
        t("test_start", lang, title=title, total=len(questions), timeout=QUESTION_TIMEOUT),
        parse_mode="HTML"
    )
    asyncio.create_task(run_quiz_loop(session))

async def run_quiz_loop(session: QuizSession):
    lang = session.lang
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
                    session.chat_id, "⏱",
                    reply_markup=quiz_control_kb(lang)
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
                    await _del_ctrl(session)
                    if session.consecutive_missed >= 2:
                        session.paused = True
                        session.answer_event.clear()
                        try:
                            await bot.send_message(
                                session.chat_id,
                                t("two_missed", lang),
                                reply_markup=missed_kb(lang)
                            )
                        except Exception:
                            pass
                continue

            await _del_ctrl(session)
            if not session.active:
                break

    except Exception as e:
        logger.error(f"Quiz loop error uid={session.user_id}: {e}")
    finally:
        if session.active:
            session.active   = False
            session.finished = True
            await finish_quiz(session)

async def _del_ctrl(session: QuizSession):
    if session.control_message_id:
        try:
            await bot.delete_message(session.chat_id, session.control_message_id)
        except Exception:
            pass
        session.control_message_id = None

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
    s.answer_event.set()


# ============================================================
# УПРАВЛЕНИЕ ТЕСТОМ
# ============================================================
@dp.callback_query(F.data == "quiz_pause")
async def quiz_pause(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    lang = await get_user_lang(uid)
    if uid not in active_sessions:
        return await callback.answer("Нет активного теста", show_alert=True)
    s = active_sessions[uid]
    if s.paused:
        return await callback.answer("Тест уже на паузе", show_alert=True)
    s.paused = True
    await callback.message.edit_text(
        t("test_paused", lang),
        reply_markup=quiz_control_kb(lang, paused=True), parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "quiz_resume")
async def quiz_resume(callback: types.CallbackQuery):
    uid  = callback.from_user.id
    lang = await get_user_lang(uid)
    if uid not in active_sessions:
        return await callback.answer("Нет активного теста", show_alert=True)
    s = active_sessions[uid]
    s.paused             = False
    s.consecutive_missed = 0
    s.appeal_pending     = False
    await callback.message.edit_text(
        "▶️ Продолжаем..." if lang == "ru" else "▶️ Жалғасады...",
        reply_markup=None
    )
    await callback.answer()

@dp.callback_query(F.data == "quiz_finish")
async def quiz_finish_cb(callback: types.CallbackQuery):
    uid     = callback.from_user.id
    session = active_sessions.get(uid)
    if not session:
        return await callback.answer("Нет активного теста", show_alert=True)

    # ИСПРАВЛЕНИЕ БАГА: немедленно вынимаем из active_sessions
    active_sessions.pop(uid, None)
    session.active = False
    session.paused = False
    session.answer_event.set()

    try:
        await callback.message.edit_text("⛔ ...", reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await finish_quiz(session, early=True)


# ============================================================
# АПЕЛЛЯЦИЯ
# ============================================================
@dp.callback_query(F.data == "quiz_appeal")
async def quiz_appeal(callback: types.CallbackQuery, state: FSMContext):
    uid  = callback.from_user.id
    lang = await get_user_lang(uid)
    if uid not in active_sessions:
        return await callback.answer("Нет активного теста", show_alert=True)

    s = active_sessions[uid]
    s.paused         = True
    s.appeal_pending = True
    q_num = s.current_index + 1

    await callback.message.answer(
        t("appeal_prompt", lang, num=q_num), parse_mode="HTML"
    )
    await state.update_data(quiz_id=s.quiz_id, q_index=s.current_index)
    await state.set_state(AppealStates.waiting_for_text)
    await callback.answer()

@dp.message(AppealStates.waiting_for_text)
async def appeal_text(message: types.Message, state: FSMContext):
    uid  = message.from_user.id
    lang = await get_user_lang(uid)
    d    = await state.get_data()
    quiz_id = d.get("quiz_id")
    q_index = d.get("q_index", 0)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO appeals (user_id,quiz_id,question_index,message) VALUES(?,?,?,?)",
            (uid, quiz_id, q_index, message.text)
        )
        await db.commit()

    # Отправляем апелляцию админу раздела или супер-админу
    row = await get_quiz(quiz_id)
    if row:
        s_id = row[1]
        # Ищем adminов раздела
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT user_id FROM section_admins WHERE section_id=?", (s_id,)
            ) as c:
                section_admins = [r[0] for r in await c.fetchall()]

        targets = section_admins or SUPER_ADMIN_IDS
        appeal_text_msg = (
            f"⚖️ <b>Апелляция</b>\n\n"
            f"Тест: {row[2]}\n"
            f"Вопрос #{q_index+1}\n"
            f"От: {message.from_user.mention_html()}\n\n"
            f"<i>{message.text}</i>"
        )
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🗑 Удалить вопрос",
                                    callback_data=f"appeal_del_{quiz_id}_{q_index}"))
        b.row(InlineKeyboardButton(text="❌ Отклонить",
                                    callback_data=f"appeal_reject_{quiz_id}_{q_index}_{uid}"))

        for t_id in targets:
            try:
                await bot.send_message(t_id, appeal_text_msg,
                                        reply_markup=b.as_markup(), parse_mode="HTML")
            except Exception:
                pass

    await message.answer(t("appeal_sent", lang))
    await state.clear()

    # Возобновляем тест
    if uid in active_sessions:
        active_sessions[uid].paused = False

@dp.callback_query(F.data.startswith("appeal_del_"))
async def appeal_del(callback: types.CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    parts   = callback.data.split("_")
    quiz_id = int(parts[2])
    q_index = int(parts[3])
    row     = await get_quiz(quiz_id)
    if not row:
        return
    questions = json.loads(row[3])
    if 0 <= q_index < len(questions):
        questions.pop(q_index)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE quizzes SET data=? WHERE id=?",
                             (json.dumps(questions, ensure_ascii=False), quiz_id))
            await db.commit()
    await callback.message.edit_text("✅ Вопрос удалён из теста.", reply_markup=None)

@dp.callback_query(F.data.startswith("appeal_reject_"))
async def appeal_reject(callback: types.CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    parts   = callback.data.split("_")
    quiz_id = int(parts[2])
    q_index = int(parts[3])
    user_id = int(parts[4])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE appeals SET status='rejected', handled_by=?, handled_at=datetime('now') "
            "WHERE quiz_id=? AND question_index=? AND user_id=?",
            (callback.from_user.id, quiz_id, q_index, user_id)
        )
        await db.commit()
    await callback.message.edit_text("❌ Апелляция отклонена.", reply_markup=None)
    try:
        lang = await get_user_lang(user_id)
        await bot.send_message(
            user_id,
            "❌ Ваша апелляция отклонена." if lang == "ru" else "❌ Сіздің апелляцияңыз қабылданбады."
        )
    except Exception:
        pass


# ============================================================
# РЕЗУЛЬТАТ ТЕСТА
# ============================================================
async def finish_quiz(session: QuizSession, early: bool = False):
    active_sessions.pop(session.user_id, None)
    lang   = session.lang
    total  = len(session.questions)
    remain = session.unanswered_remaining
    pct    = session.percent

    await save_result(session, finished=not early)

    emoji = "🏆" if pct >= 80 else ("👍" if pct >= 50 else "📚")

    if early:
        text = t("result_early", lang,
                 title=session.quiz_title, total=total,
                 correct=session.correct_count, wrong=session.wrong_count,
                 missed=session.missed_count, remaining=remain, percent=pct)
    else:
        text = t("result_title", lang,
                 emoji=emoji, title=session.quiz_title,
                 correct=session.correct_count, wrong=session.wrong_count,
                 missed=session.missed_count, percent=pct)

    # Разбор ошибок (только премиум)
    is_prem   = await check_premium(session.user_id)
    err_block = ""
    if is_prem and (session.wrong_questions or session.missed_questions):
        err_block = "\n\n📋 <b>Разбор ошибок:</b>" if lang == "ru" else "\n\n📋 <b>Қателерді талдау:</b>"
        for i, q in enumerate(session.wrong_questions[:5], 1):
            err_block += f"\n{i}. {q['q']}\n✅ <b>{q['opts'][q['correct']]}</b>"
        if session.missed_questions:
            err_block += "\n\n⏭ <b>Пропущенные:</b>" if lang == "ru" else "\n\n⏭ <b>Өткізілгендер:</b>"
            for i, q in enumerate(session.missed_questions[:3], 1):
                err_block += f"\n{i}. {q['q']}\n✅ <b>{q['opts'][q['correct']]}</b>"
    elif not is_prem and (session.wrong_questions or session.missed_questions):
        err_block = ("\n\n🔒 <i>Разбор ошибок доступен в Премиуме</i>"
                     if lang == "ru" else "\n\n🔒 <i>Қателерді талдау Премиумда</i>")

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 " + ("Пройти снова" if lang == "ru" else "Қайта өту"),
                                callback_data=f"run_{session.quiz_id}"))
    b.row(InlineKeyboardButton(text=t("btn_sections", lang), callback_data="menu_sections"))
    b.row(InlineKeyboardButton(text=t("btn_share_test", lang) if session.questions else "📤",
                                switch_inline_query=f"quiz_{session.quiz_id}"))

    await bot.send_message(
        session.chat_id, text + err_block,
        reply_markup=b.as_markup(), parse_mode="HTML"
    )


# ============================================================
# INLINE MODE (только бесплатные)
# ============================================================
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    results = []

    async def make_card(q_id, title, count, is_group=False):
        if is_group:
            deep = f"https://t.me/{BOT_USERNAME}?startgroup=gquiz_{q_id}"
            kb   = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="▶️ Пройти тест", url=deep)
            ]])
        else:
            deep = f"https://t.me/{BOT_USERNAME}?start=quiz_{q_id}"
            kb   = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Пройти тест", url=deep)],
                [InlineKeyboardButton(text="👥 Запустить в группе",
                                      url=f"https://t.me/{BOT_USERNAME}?startgroup=gquiz_{q_id}")],
            ])
        return InlineQueryResultArticle(
            id=f"{'g' if is_group else ''}{q_id}",
            title=f"{'👥 ' if is_group else '🎲 '}Тест «{title}»",
            description=f"📝 {count} вопросов · ⏱ {QUESTION_TIMEOUT} сек",
            input_message_content=InputTextMessageContent(
                message_text=(
                    f"{'👥 ' if is_group else '🎲 '}Тест <b>«{title}»</b>\n\n"
                    f"📝 {count} вопросов · ⏱ {QUESTION_TIMEOUT} сек\n\n"
                    f"{'Минимум 2 участника. ' if is_group else ''}👇 Нажми чтобы начать!"
                ),
                parse_mode="HTML"
            ),
            reply_markup=kb,
            thumbnail_url="https://img.icons8.com/color/96/test-passed.png"
        )

    q = query.query
    is_group = q.startswith("group_")
    is_quiz  = q.startswith("quiz_")

    if is_quiz or is_group:
        try:
            q_id = int(q.split("_")[1])
            row  = await get_quiz(q_id)
            if row and row[4] == 'free':
                qs = json.loads(row[3])
                results.append(await make_card(row[0], row[2], len(qs), is_group=is_group))
        except (IndexError, ValueError):
            pass
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id,title,data FROM quizzes WHERE access_type='free' AND is_active=1"
            ) as c:
                quizzes = await c.fetchall()
        for q_id, title, data_json in quizzes:
            results.append(await make_card(q_id, title, len(json.loads(data_json))))

    await query.answer(results, cache_time=5)


# ============================================================
# ГРУППОВОЙ РЕЖИМ
# ============================================================
@dp.message(Command("start"))
async def group_quiz_start(message: types.Message):
    """Обрабатывает /start gquiz_ID в группе."""
    if message.chat.type not in ("group", "supergroup"):
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].startswith("gquiz_"):
        return
    try:
        q_id = int(args[1].split("_")[1])
    except (IndexError, ValueError):
        return

    chat_id = message.chat.id
    uid     = message.from_user.id
    row     = await get_quiz(q_id)
    if not row or row[4] != 'free':
        await message.answer("🔒 Только бесплатные тесты можно запускать в группах.")
        return

    if chat_id not in group_sessions:
        group_sessions[chat_id] = {
            "quiz_id": q_id, "players": [], "started": False,
            "created_by": uid, "title": row[2]
        }
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="▶️ Пройти тест", callback_data=f"gjoin_{q_id}"))
        questions = json.loads(row[3])
        await message.answer(
            f"🎲 Тест <b>«{row[2]}»</b>\n📝 {len(questions)} вопросов · ⏱ {QUESTION_TIMEOUT} сек\n\n"
            f"Нажмите «▶️ Пройти тест» чтобы участвовать!\n"
            f"Тест стартует, когда готовы минимум {GROUP_MIN_PLAYERS} участника.",
            reply_markup=b.as_markup(), parse_mode="HTML"
        )
    else:
        await message.answer("Тест уже запущен в этом чате.")

@dp.callback_query(F.data.startswith("gjoin_"))
async def group_join(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    uid     = callback.from_user.id
    q_id    = int(callback.data.split("_")[1])
    gs      = group_sessions.get(chat_id)

    if not gs or gs["started"]:
        return await callback.answer("Тест уже начался.", show_alert=True)
    if uid in gs["players"]:
        return await callback.answer("Вы уже в списке участников.", show_alert=True)

    gs["players"].append(uid)
    cnt  = len(gs["players"])
    name = callback.from_user.first_name or str(uid)
    await callback.answer(f"✅ {name} готов!")

    if cnt >= GROUP_MIN_PLAYERS:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🚀 Начать тест!",
                                    callback_data=f"gstart_{chat_id}_{q_id}"))
        try:
            await callback.message.edit_reply_markup(reply_markup=b.as_markup())
        except Exception:
            pass
        await callback.message.answer(
            f"👥 Участников: <b>{cnt}</b>. Можно начинать!",
            parse_mode="HTML"
        )

@dp.callback_query(F.data.startswith("gstart_"))
async def group_start(callback: types.CallbackQuery):
    parts   = callback.data.split("_")
    chat_id = int(parts[1])
    q_id    = int(parts[2])
    uid     = callback.from_user.id
    gs      = group_sessions.get(chat_id)

    if not gs:
        return await callback.answer("Сессия не найдена", show_alert=True)
    # Только создатель или админ может старт
    if uid != gs.get("created_by") and uid not in SUPER_ADMIN_IDS:
        return await callback.answer("Только создатель теста может его запустить", show_alert=True)
    if gs["started"]:
        return await callback.answer("Уже запущен", show_alert=True)

    gs["started"] = True
    row       = await get_quiz(q_id)
    questions = clean_quiz_data(json.loads(row[3]))

    for count in ["3", "2", "1", "🚀 Старт!"]:
        await bot.send_message(chat_id, count)
        await asyncio.sleep(1)

    await bot.send_message(
        chat_id,
        f"🚀 <b>Тест «{row[2]}»</b>\n👥 Участников: {len(gs['players'])}\n📝 {len(questions)} вопросов",
        parse_mode="HTML"
    )

    for i, q in enumerate(questions):
        # Проверяем что сессия не завершена
        if not group_sessions.get(chat_id, {}).get("started"):
            break
        opts = [clean_option(o) for o in q['opts']]
        try:
            await bot.send_poll(
                chat_id=chat_id,
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

    await bot.send_message(chat_id, "🏁 Групповой тест завершён! Спасибо всем участникам.")
    group_sessions.pop(chat_id, None)
    await callback.answer()

# ============================================================
# ГЛАВНАЯ АДМИН-ПАНЕЛЬ
# ============================================================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not await is_any_admin(uid):
        return await callback.answer("❌ Нет доступа", show_alert=True)

    is_super = await is_super_admin(uid)
    b = InlineKeyboardBuilder()

    if is_super:
        b.row(InlineKeyboardButton(text="📂 Разделы",          callback_data="adm_sections"))
        b.row(InlineKeyboardButton(text="👥 Админы разделов",   callback_data="adm_sec_admins"))
    b.row(InlineKeyboardButton(text="➕ Добавить тест",          callback_data="adm_add_quiz"))
    b.row(
        InlineKeyboardButton(text="📋 Тесты",   callback_data="adm_list_quiz"),
        InlineKeyboardButton(text="🗑 Удалить",  callback_data="adm_del_quiz"),
    )
    b.row(InlineKeyboardButton(text="💰 Тип доступа",           callback_data="adm_access"))
    b.row(InlineKeyboardButton(text="⭐ Цена Stars",             callback_data="adm_stars"))
    b.row(InlineKeyboardButton(text="🔐 Приватный доступ",      callback_data="adm_private"))
    b.row(InlineKeyboardButton(text="🎁 Выдать Премиум",        callback_data="adm_premium"))
    b.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"),
        InlineKeyboardButton(text="⚖️ Апелляции",  callback_data="adm_appeals"),
    )
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))

    await callback.message.edit_text("⚙️ <b>Админ-панель</b>",
                                      reply_markup=b.as_markup(), parse_mode="HTML")


# ============================================================
# УПРАВЛЕНИЕ РАЗДЕЛАМИ (только super_admin)
# ============================================================
@dp.callback_query(F.data == "adm_sections")
async def adm_sections(callback: types.CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Создать раздел", callback_data="adm_sec_create"))
    b.row(InlineKeyboardButton(text="✏️ Редактировать",  callback_data="adm_sec_edit"))
    b.row(InlineKeyboardButton(text="🗑 Удалить раздел", callback_data="adm_sec_del"))
    b.row(InlineKeyboardButton(text="📢 Каналы подписки", callback_data="adm_sec_channels"))
    b.row(InlineKeyboardButton(text="🔙 Назад",          callback_data="admin_panel"))
    await callback.message.edit_text("📂 <b>Управление разделами</b>",
                                      reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "adm_sec_create")
async def adm_sec_create(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите <b>название раздела на русском</b>:", parse_mode="HTML")
    await state.set_state(AdminStates.section_title_ru)

@dp.message(AdminStates.section_title_ru)
async def adm_sec_ru(message: types.Message, state: FSMContext):
    await state.update_data(title_ru=message.text.strip())
    await message.answer("Теперь введите <b>название на казахском</b>:", parse_mode="HTML")
    await state.set_state(AdminStates.section_title_kk)

@dp.message(AdminStates.section_title_kk)
async def adm_sec_kk(message: types.Message, state: FSMContext):
    d = await state.get_data()
    title_ru = d["title_ru"]
    title_kk = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO sections (title_ru,title_kk) VALUES(?,?)",
                         (title_ru, title_kk))
        await db.commit()
    await message.answer(f"✅ Раздел <b>«{title_ru}»</b> создан!", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "adm_sec_del")
async def adm_sec_del(callback: types.CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return
    sections = await get_sections(active_only=False)
    if not sections:
        return await callback.answer("Разделов нет", show_alert=True)
    b = InlineKeyboardBuilder()
    for s_id, ru, kk, _, _ in sections:
        b.row(InlineKeyboardButton(text=f"🗑 {ru}", callback_data=f"del_sec_{s_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_sections"))
    await callback.message.edit_text("Выберите раздел для удаления:", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("del_sec_"))
async def del_sec(callback: types.CallbackQuery):
    s_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE sections SET is_active=0 WHERE id=?", (s_id,))
        await db.commit()
    await callback.answer("✅ Раздел деактивирован", show_alert=True)
    await adm_sections(callback)

@dp.callback_query(F.data == "adm_sec_channels")
async def adm_sec_channels(callback: types.CallbackQuery):
    sections = await get_sections()
    if not sections:
        return await callback.answer("Разделов нет", show_alert=True)
    b = InlineKeyboardBuilder()
    for s_id, ru, _, req, ch in sections:
        status = "✅" if req else "❌"
        ch_str = f" ({ch})" if ch else ""
        b.row(InlineKeyboardButton(text=f"{status} {ru}{ch_str}",
                                    callback_data=f"sec_ch_{s_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_sections"))
    await callback.message.edit_text("📢 <b>Каналы подписки по разделам</b>\n\n✅ — включено | ❌ — выключено",
                                      reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("sec_ch_"))
async def sec_ch_manage(callback: types.CallbackQuery):
    s_id = int(callback.data.split("_")[2])
    sec  = await get_section(s_id)
    if not sec:
        return
    _, ru, _, req, ch = sec
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✏️ Задать канал",        callback_data=f"sec_ch_set_{s_id}"))
    if req:
        b.row(InlineKeyboardButton(text="❌ Выключить подписку", callback_data=f"sec_ch_off_{s_id}"))
    else:
        b.row(InlineKeyboardButton(text="✅ Включить подписку",  callback_data=f"sec_ch_on_{s_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_sec_channels"))
    await callback.message.edit_text(
        f"📢 Раздел: <b>{ru}</b>\nКанал: <code>{ch or 'не задан'}</code>\n"
        f"Подписка: {'✅ включена' if req else '❌ выключена'}",
        reply_markup=b.as_markup(), parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("sec_ch_set_"))
async def sec_ch_set(callback: types.CallbackQuery, state: FSMContext):
    s_id = int(callback.data.split("_")[3])
    await state.update_data(section_id=s_id)
    await callback.message.answer("Введите @username канала:")
    await state.set_state(AdminStates.channel_username)

@dp.message(AdminStates.channel_username)
async def save_section_channel(message: types.Message, state: FSMContext):
    d    = await state.get_data()
    s_id = d["section_id"]
    ch   = message.text.strip()
    if not ch.startswith("@"):
        ch = "@" + ch
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE sections SET required_channel_username=? WHERE id=?", (ch, s_id))
        await db.commit()
    await message.answer(f"✅ Канал <b>{ch}</b> установлен для раздела.", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data.startswith("sec_ch_on_"))
async def sec_ch_on(callback: types.CallbackQuery):
    s_id = int(callback.data.split("_")[3])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE sections SET require_subscription=1 WHERE id=?", (s_id,))
        await db.commit()
    await callback.answer("✅ Подписка включена", show_alert=True)
    await adm_sec_channels(callback)

@dp.callback_query(F.data.startswith("sec_ch_off_"))
async def sec_ch_off(callback: types.CallbackQuery):
    s_id = int(callback.data.split("_")[3])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE sections SET require_subscription=0 WHERE id=?", (s_id,))
        await db.commit()
    await callback.answer("❌ Подписка выключена", show_alert=True)
    await adm_sec_channels(callback)


# ============================================================
# УПРАВЛЕНИЕ АДМИНАМИ РАЗДЕЛОВ
# ============================================================
@dp.callback_query(F.data == "adm_sec_admins")
async def adm_sec_admins(callback: types.CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Добавить админа раздела", callback_data="add_sec_admin"))
    b.row(InlineKeyboardButton(text="🗑 Удалить админа раздела",  callback_data="del_sec_admin"))
    b.row(InlineKeyboardButton(text="📋 Список админов",           callback_data="list_sec_admins"))
    b.row(InlineKeyboardButton(text="🔙 Назад",                    callback_data="admin_panel"))
    await callback.message.edit_text("👥 <b>Админы разделов</b>",
                                      reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "add_sec_admin")
async def add_sec_admin(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите <b>user_id</b> нового админа раздела:", parse_mode="HTML")
    await state.set_state(AdminStates.section_admin_uid)

@dp.message(AdminStates.section_admin_uid)
async def sec_admin_get_uid(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        await state.update_data(new_admin_uid=uid)
        sections = await get_sections()
        if not sections:
            return await message.answer("Разделов нет")
        b = InlineKeyboardBuilder()
        for s_id, ru, _, _, _ in sections:
            b.row(InlineKeyboardButton(text=ru, callback_data=f"assign_sec_{s_id}"))
        await message.answer("Выберите раздел:", reply_markup=b.as_markup())
        await state.set_state(AdminStates.section_admin_sid)
    except ValueError:
        await message.answer("❌ Введите числовой ID")

@dp.callback_query(AdminStates.section_admin_sid)
async def assign_sec_admin(callback: types.CallbackQuery, state: FSMContext):
    s_id = int(callback.data.split("_")[2])
    d    = await state.get_data()
    uid  = d["new_admin_uid"]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO section_admins (user_id,section_id) VALUES(?,?)",
                         (uid, s_id))
        await db.commit()
    await callback.message.answer(f"✅ Пользователь {uid} назначен админом раздела #{s_id}.")
    await state.clear()

@dp.callback_query(F.data == "list_sec_admins")
async def list_sec_admins(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT sa.user_id, u.username, s.title_ru
            FROM section_admins sa
            LEFT JOIN users u ON sa.user_id=u.user_id
            JOIN sections s ON sa.section_id=s.id
        """) as c:
            rows = await c.fetchall()
    if not rows:
        return await callback.answer("Нет назначенных админов", show_alert=True)
    text = "👥 <b>Админы разделов:</b>\n\n"
    for uid, uname, sec_title in rows:
        text += f"• {('@'+uname) if uname else uid} → {sec_title}\n"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_sec_admins"))
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


# ============================================================
# ДОБАВЛЕНИЕ ТЕСТА (накопительный буфер)
# ============================================================
@dp.callback_query(F.data == "adm_add_quiz")
async def adm_add_quiz(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if not await is_any_admin(uid):
        return
    # Показываем разделы, которыми управляет этот админ
    sec_ids  = await get_admin_sections(uid)
    sections = await get_sections()
    sections = [s for s in sections if s[0] in sec_ids]
    if not sections:
        return await callback.answer("У вас нет доступных разделов", show_alert=True)
    b = InlineKeyboardBuilder()
    for s_id, ru, _, _, _ in sections:
        b.row(InlineKeyboardButton(text=ru, callback_data=f"quiz_sec_{s_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("Выберите <b>раздел</b> для теста:",
                                      reply_markup=b.as_markup(), parse_mode="HTML")
    await state.set_state(AdminStates.quiz_section)

@dp.callback_query(AdminStates.quiz_section)
async def quiz_pick_section(callback: types.CallbackQuery, state: FSMContext):
    s_id = int(callback.data.split("_")[2])
    await state.update_data(section_id=s_id)
    await callback.message.answer("Введите <b>название теста</b>:", parse_mode="HTML")
    await state.set_state(AdminStates.quiz_title)

@dp.message(AdminStates.quiz_title)
async def quiz_get_title(message: types.Message, state: FSMContext):
    uid   = message.from_user.id
    title = message.text.strip()
    await state.update_data(title=title)
    quiz_buffers[uid] = {"title": title, "parts": [], "polls": []}
    await message.answer(
        f"✅ Название: <b>{title}</b>\n\n"
        "Отправляй вопросы:\n"
        "• Текстом (несколько сообщений подряд)\n"
        "• Пересылай Quiz Poll из других чатов\n\n"
        "<code>Вопрос?\nA) Вариант\n*B) Правильный\nC) Вариант</code>\n\n"
        "Когда готово — нажми «💾 Сохранить тест».",
        reply_markup=collecting_kb(), parse_mode="HTML"
    )
    await state.set_state(AdminStates.quiz_collecting)

@dp.message(AdminStates.quiz_collecting, F.poll)
async def collect_poll(message: types.Message, state: FSMContext):
    uid  = message.from_user.id
    poll = message.poll
    if poll.type != 'quiz' or uid not in quiz_buffers:
        return await message.answer("⚠️ Это не Quiz Poll.")
    q = {"q": poll.question,
         "opts": [o.text for o in poll.options],
         "correct": poll.correct_option_id}
    quiz_buffers[uid]["polls"].append(q)
    total = len(quiz_buffers[uid]["polls"]) + sum(
        count_questions_in_text(p) for p in quiz_buffers[uid]["parts"]
    )
    await message.answer(f"✅ Poll добавлен! Вопросов: <b>{total}</b>",
                          reply_markup=collecting_kb(), parse_mode="HTML")

@dp.message(AdminStates.quiz_collecting)
async def collect_text(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    if uid not in quiz_buffers:
        return
    raw    = message.text or ""
    parsed, error = parse_quiz_data(raw)

    if error:
        quiz_buffers[uid]["bad_fragment"] = raw
        preview = detect_error_block(raw, error)
        text_q  = sum(count_questions_in_text(p) for p in quiz_buffers[uid]["parts"])
        poll_q  = len(quiz_buffers[uid]["polls"])
        await message.answer(
            f"⚠️ <b>Ошибка в фрагменте!</b>\n\nПричина: {error}{preview}\n\n"
            f"<i>Уже накоплено: <b>{text_q + poll_q}</b> вопросов</i>\n"
            "Этот фрагмент <b>не добавлен</b>. Выберите действие:",
            reply_markup=error_fragment_kb(), parse_mode="HTML"
        )
        return

    quiz_buffers[uid]["parts"].append(raw)
    quiz_buffers[uid].pop("bad_fragment", None)
    text_q = sum(count_questions_in_text(p) for p in quiz_buffers[uid]["parts"])
    poll_q = len(quiz_buffers[uid]["polls"])
    await message.answer(
        f"✅ <b>Фрагмент добавлен!</b>\n\n"
        f"Частей: <b>{len(quiz_buffers[uid]['parts'])}</b> | Poll: <b>{poll_q}</b>\n"
        f"Всего вопросов: <b>{text_q + poll_q}</b>\n\n"
        "Продолжайте или нажмите «💾 Сохранить тест».",
        reply_markup=collecting_kb(), parse_mode="HTML"
    )

# --- Кнопки буфера ---
@dp.callback_query(F.data == "quiz_buf_save")
async def quiz_buf_save(callback: types.CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in quiz_buffers:
        return await callback.answer("Буфер пуст", show_alert=True)
    buf   = quiz_buffers[uid]
    title = buf["title"]
    d     = await state.get_data()
    s_id  = d.get("section_id", 1)

    all_questions = []
    for part in buf["parts"]:
        qs, _ = parse_quiz_data(part)
        all_questions.extend(qs)
    all_questions.extend(buf["polls"])

    if not all_questions:
        return await callback.message.answer(
            "❌ Вопросов нет. Добавьте хотя бы один корректный фрагмент.",
            reply_markup=collecting_kb()
        )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO quizzes (section_id,title,data,created_by) VALUES(?,?,?,?)",
            (s_id, title, json.dumps(all_questions, ensure_ascii=False), uid)
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
        quiz_buffers[uid]["parts"]       = []
        quiz_buffers[uid]["polls"]       = []
        quiz_buffers[uid].pop("bad_fragment", None)
    await callback.message.answer("🗑 Всё очищено.", reply_markup=collecting_kb())

@dp.callback_query(F.data == "quiz_buf_cancel")
async def quiz_buf_cancel(callback: types.CallbackQuery, state: FSMContext):
    quiz_buffers.pop(callback.from_user.id, None)
    await state.clear()
    await callback.message.answer("❌ Создание теста отменено.")

@dp.callback_query(F.data == "frag_drop")
async def frag_drop(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in quiz_buffers:
        quiz_buffers[uid].pop("bad_fragment", None)
    text_q = sum(count_questions_in_text(p) for p in quiz_buffers.get(uid, {}).get("parts", []))
    poll_q = len(quiz_buffers.get(uid, {}).get("polls", []))
    await callback.message.edit_text(
        f"🗑 Фрагмент удалён. Накоплено: <b>{text_q + poll_q}</b> вопросов.\n\nПродолжайте или сохраните.",
        reply_markup=collecting_kb(), parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "frag_retry")
async def frag_retry(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "✏️ <b>Отправьте исправленный фрагмент.</b>\n\n"
        "<code>Вопрос?\nA) Вариант\n*B) Правильный\nC) Вариант</code>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "frag_continue")
async def frag_continue(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in quiz_buffers:
        quiz_buffers[uid].pop("bad_fragment", None)
    text_q = sum(count_questions_in_text(p) for p in quiz_buffers.get(uid, {}).get("parts", []))
    poll_q = len(quiz_buffers.get(uid, {}).get("polls", []))
    await callback.message.edit_text(
        f"➕ Продолжаем. Накоплено: <b>{text_q + poll_q}</b> вопросов.\n\nОтправьте следующую часть.",
        reply_markup=collecting_kb(), parse_mode="HTML"
    )
    await callback.answer()


# ============================================================
# СПИСОК / УДАЛЕНИЕ / ТИП ДОСТУПА ТЕСТОВ
# ============================================================
@dp.callback_query(F.data == "adm_list_quiz")
async def adm_list_quiz(callback: types.CallbackQuery):
    uid     = callback.from_user.id
    sec_ids = await get_admin_sections(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT q.id, q.title, q.access_type, q.stars_price, q.data,
                   s.title_ru,
                   COUNT(DISTINCT r.user_id) AS users,
                   COUNT(r.id) AS attempts,
                   AVG(r.percent) AS avg_pct
            FROM quizzes q
            JOIN sections s ON q.section_id=s.id
            LEFT JOIN results r ON q.id=r.quiz_id
            WHERE q.section_id IN ({})
            GROUP BY q.id
        """.format(",".join("?" * len(sec_ids))), sec_ids) as c:
            rows = await c.fetchall()

    if not rows:
        return await callback.answer("Тестов нет", show_alert=True)

    icons = {"free":"🆓","premium":"🔒","stars":"⭐","private":"🔐"}
    text  = "📋 <b>Тесты:</b>\n\n"
    for q_id, title, atype, sp, data_json, sec_ru, users, attempts, avg_pct in rows:
        cnt  = len(json.loads(data_json))
        mark = icons.get(atype, "🆓")
        text += f"<b>#{q_id}</b> {mark} [{sec_ru}] {title} | 📝{cnt}\n"
        if attempts:
            text += f"   👥{users or 0} | 🔄{attempts} | 📈{avg_pct:.0f}%\n"
        text += "\n"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "adm_del_quiz")
async def adm_del_quiz(callback: types.CallbackQuery):
    uid     = callback.from_user.id
    sec_ids = await get_admin_sections(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title FROM quizzes WHERE section_id IN ({}) AND is_active=1".format(
                ",".join("?" * len(sec_ids))
            ), sec_ids
        ) as c:
            quizzes = await c.fetchall()

    if not quizzes:
        return await callback.answer("Тестов нет", show_alert=True)
    b = InlineKeyboardBuilder()
    for q_id, title in quizzes:
        b.row(InlineKeyboardButton(text=f"🗑 {title}", callback_data=f"del_quiz_{q_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("🗑 Выберите тест:", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("del_quiz_"))
async def del_quiz(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE quizzes SET is_active=0 WHERE id=?", (q_id,))
        await db.commit()
    await callback.answer("✅ Тест удалён", show_alert=True)
    await adm_del_quiz(callback)

@dp.callback_query(F.data == "adm_access")
async def adm_access(callback: types.CallbackQuery):
    uid     = callback.from_user.id
    sec_ids = await get_admin_sections(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, title, access_type FROM quizzes WHERE section_id IN ({}) AND is_active=1".format(
                ",".join("?" * len(sec_ids))
            ), sec_ids
        ) as c:
            quizzes = await c.fetchall()

    if not quizzes:
        return await callback.answer("Тестов нет", show_alert=True)
    icons = {"free":"🆓","premium":"🔒","stars":"⭐","private":"🔐"}
    b = InlineKeyboardBuilder()
    for q_id, title, atype in quizzes:
        b.row(InlineKeyboardButton(text=f"{icons.get(atype,'🆓')} {title}",
                                    callback_data=f"setacc_{q_id}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("💰 Выберите тест:", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("setacc_"))
async def setacc_choose(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    b = InlineKeyboardBuilder()
    for atype, label in [("free","🆓 Бесплатно"),("premium","🔒 Премиум"),
                          ("stars","⭐ Stars"),("private","🔐 Приватный")]:
        b.row(InlineKeyboardButton(text=label, callback_data=f"appacc_{q_id}_{atype}"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_access"))
    await callback.message.edit_text("Выберите тип:", reply_markup=b.as_markup())

@dp.callback_query(F.data.startswith("appacc_"))
async def appacc_apply(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    q_id  = int(parts[1])
    atype = parts[2]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE quizzes SET access_type=? WHERE id=?", (atype, q_id))
        await db.commit()
    await callback.answer(f"✅ Тип изменён: {atype}", show_alert=True)
    await adm_access(callback)

@dp.callback_query(F.data == "adm_stars")
async def adm_stars(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("⭐ Введите <b>ID теста</b>:", parse_mode="HTML")
    await state.set_state(AdminStates.stars_quiz_id)

@dp.message(AdminStates.stars_quiz_id)
async def stars_get_qid(message: types.Message, state: FSMContext):
    try:
        q_id = int(message.text.strip())
        row  = await get_quiz(q_id)
        if not row:
            return await message.answer("❌ Тест не найден")
        await state.update_data(quiz_id=q_id)
        await message.answer(f"Тест: <b>{row[2]}</b>\nВведите <b>цену в Stars</b>:", parse_mode="HTML")
        await state.set_state(AdminStates.stars_price)
    except ValueError:
        await message.answer("❌ Введите число")

@dp.message(AdminStates.stars_price)
async def stars_set_price(message: types.Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        d     = await state.get_data()
        q_id  = d["quiz_id"]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE quizzes SET stars_price=?, access_type='stars' WHERE id=?", (price, q_id)
            )
            await db.commit()
        await message.answer(f"✅ Цена <b>{price} Stars</b> установлена.", parse_mode="HTML")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число")


# ============================================================
# ПРИВАТНЫЙ ДОСТУП
# ============================================================
@dp.callback_query(F.data == "adm_private")
async def adm_private(callback: types.CallbackQuery):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ Выдать доступ",          callback_data="priv_grant"))
    b.row(InlineKeyboardButton(text="➖ Забрать доступ",         callback_data="priv_revoke"))
    b.row(InlineKeyboardButton(text="📋 Список доступов",        callback_data="priv_list"))
    b.row(InlineKeyboardButton(text="📊 Результаты приватного",  callback_data="priv_results"))
    b.row(InlineKeyboardButton(text="🔓 Сбросить попытки",       callback_data="priv_reset"))
    b.row(InlineKeyboardButton(text="🗑 Удалить результаты",     callback_data="priv_del_results"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("🔐 <b>Приватный доступ</b>",
                                      reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "priv_grant")
async def priv_grant(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите <b>ID теста</b> (приватного):", parse_mode="HTML")
    await state.set_state(AdminStates.private_quiz_id)

@dp.message(AdminStates.private_quiz_id)
async def priv_quiz_id(message: types.Message, state: FSMContext):
    try:
        q_id = int(message.text.strip())
        await state.update_data(quiz_id=q_id)
        await message.answer("Введите <b>user_id</b> пользователя:", parse_mode="HTML")
        await state.set_state(AdminStates.private_uid)
    except ValueError:
        await message.answer("❌ Введите число")

@dp.message(AdminStates.private_uid)
async def priv_uid(message: types.Message, state: FSMContext):
    try:
        uid  = int(message.text.strip())
        d    = await state.get_data()
        q_id = d["quiz_id"]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO private_access (user_id,quiz_id,granted_by,max_attempts) VALUES(?,?,?,?)",
                (uid, q_id, message.from_user.id, PRIVATE_MAX_ATTEMPTS)
            )
            await db.execute("UPDATE quizzes SET access_type='private' WHERE id=?", (q_id,))
            await db.commit()
        await message.answer(f"✅ Доступ к тесту #{q_id} выдан пользователю {uid}.")
        try:
            row = await get_quiz(q_id)
            await bot.send_message(uid, f"🔐 Вам открыт приватный тест <b>«{row[2]}»</b>!\n"
                                        f"Попыток: {PRIVATE_MAX_ATTEMPTS}", parse_mode="HTML")
        except Exception:
            pass
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите числовой user_id")

@dp.callback_query(F.data == "priv_revoke")
async def priv_revoke(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("ID теста для отзыва доступа:")
    await state.set_state(AdminStates.revoke_quiz_id)

@dp.message(AdminStates.revoke_quiz_id)
async def revoke_qid(message: types.Message, state: FSMContext):
    try:
        await state.update_data(quiz_id=int(message.text.strip()))
        await message.answer("user_id пользователя:")
        await state.set_state(AdminStates.revoke_uid)
    except ValueError:
        await message.answer("❌ Число")

@dp.message(AdminStates.revoke_uid)
async def revoke_uid(message: types.Message, state: FSMContext):
    try:
        uid  = int(message.text.strip())
        d    = await state.get_data()
        q_id = d["quiz_id"]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM private_access WHERE user_id=? AND quiz_id=?", (uid, q_id)
            )
            await db.commit()
        await message.answer(f"✅ Доступ к тесту #{q_id} у {uid} отозван.")
        await state.clear()
    except ValueError:
        await message.answer("❌ Число")

@dp.callback_query(F.data == "priv_list")
async def priv_list(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT pa.quiz_id, q.title, pa.user_id, u.username, pa.max_attempts, pa.used_attempts
            FROM private_access pa
            JOIN quizzes q ON pa.quiz_id=q.id
            LEFT JOIN users u ON pa.user_id=u.user_id
            ORDER BY pa.quiz_id
        """) as c:
            rows = await c.fetchall()

    if not rows:
        return await callback.answer("Нет приватных доступов", show_alert=True)
    text = "🔐 <b>Приватные доступы:</b>\n\n"
    for q_id, title, uid, uname, max_a, used_a in rows:
        left = max(0, max_a - used_a)
        ustr = f"@{uname}" if uname else str(uid)
        text += f"#{q_id} «{title}» → {ustr} (попыток: {left}/{max_a})\n"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_private"))
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "priv_results")
async def priv_results(callback: types.CallbackQuery):
    """Результаты участников приватных тестов."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT r.quiz_id, q.title, r.user_id, u.username,
                   r.attempt_number, r.score, r.total, r.wrong, r.missed,
                   r.percent, r.finished, r.completed_at
            FROM results r
            JOIN quizzes q ON r.quiz_id=q.id
            LEFT JOIN users u ON r.user_id=u.user_id
            WHERE q.access_type='private'
            ORDER BY r.quiz_id, r.user_id, r.attempt_number
        """) as c:
            rows = await c.fetchall()

    if not rows:
        return await callback.answer("Нет результатов по приватным тестам", show_alert=True)

    text = "📊 <b>Результаты приватных тестов:</b>\n\n"
    prev_q = prev_u = None
    for q_id, qtitle, uid, uname, attempt, score, total, wrong, missed, pct, fin, dt in rows:
        if q_id != prev_q:
            text += f"\n🔐 <b>{qtitle}</b>\n"
            prev_q = q_id
            prev_u = None
        if uid != prev_u:
            ustr  = f"@{uname}" if uname else str(uid)
            text += f"\n  👤 {ustr}\n"
            prev_u = uid
        flag  = "✅" if fin else "⚠️"
        dt_s  = dt[:16] if dt else "—"
        text += f"    Попытка {attempt} [{dt_s}]: ✅{score} ❌{wrong} ⏭{missed}/{total} — <b>{pct:.0f}%</b> {flag}\n"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_private"))
    # Разбиваем если слишком длинный
    if len(text) > 3800:
        text = text[:3800] + "\n\n<i>...список обрезан</i>"
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "priv_reset")
async def priv_reset(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите <b>user_id</b> для сброса попыток:", parse_mode="HTML")
    await state.set_state(AdminStates.reset_attempts_uid)

@dp.message(AdminStates.reset_attempts_uid)
async def priv_reset_uid(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE private_access SET used_attempts=0 WHERE user_id=?", (uid,)
            )
            await db.commit()
        await message.answer(f"✅ Попытки сброшены для {uid}.")
        await state.clear()
    except ValueError:
        await message.answer("❌ Число")

@dp.callback_query(F.data == "priv_del_results")
async def priv_del_results_menu(callback: types.CallbackQuery):
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🗑 Удалить по пользователю+тесту",
                                callback_data="del_res_user"))
    b.row(InlineKeyboardButton(text="🗑 Удалить все по тесту",
                                callback_data="del_res_quiz"))
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="adm_private"))
    await callback.message.edit_text("🗑 <b>Удаление результатов</b>\n\n⚠️ Действие необратимо!",
                                      reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "del_res_user")
async def del_res_user(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите: <code>user_id quiz_id</code>", parse_mode="HTML")
    await state.update_data(del_mode="user")
    await state.set_state(AdminStates.reset_attempts_uid)

@dp.callback_query(F.data == "del_res_quiz")
async def del_res_quiz(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите <b>quiz_id</b>:", parse_mode="HTML")
    await state.update_data(del_mode="quiz")
    await state.set_state(AdminStates.reset_attempts_uid)

# Переиспользуем тот же стейт — дополнительная обработка
@dp.message(AdminStates.reset_attempts_uid)
async def handle_del_or_reset(message: types.Message, state: FSMContext):
    d    = await state.get_data()
    mode = d.get("del_mode")
    try:
        if mode == "user":
            parts  = message.text.strip().split()
            uid, q_id = int(parts[0]), int(parts[1])
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "DELETE FROM results WHERE user_id=? AND quiz_id=?", (uid, q_id)
                )
                await db.commit()
            await message.answer(f"✅ Результаты пользователя {uid} по тесту #{q_id} удалены.")
        elif mode == "quiz":
            q_id = int(message.text.strip())
            b = InlineKeyboardBuilder()
            b.row(InlineKeyboardButton(text="✅ Подтвердить удаление",
                                        callback_data=f"confirm_del_res_{q_id}"))
            b.row(InlineKeyboardButton(text="❌ Отмена", callback_data="adm_private"))
            await message.answer(
                f"⚠️ Удалить ВСЕ результаты теста #{q_id}? Это необратимо.",
                reply_markup=b.as_markup()
            )
            await state.clear()
            return
        else:
            uid = int(message.text.strip())
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE private_access SET used_attempts=0 WHERE user_id=?", (uid,))
                await db.commit()
            await message.answer(f"✅ Попытки сброшены для {uid}.")
        await state.clear()
    except (ValueError, IndexError):
        await message.answer("❌ Неверный формат")

@dp.callback_query(F.data.startswith("confirm_del_res_"))
async def confirm_del_res(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[3])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM results WHERE quiz_id=?", (q_id,))
        await db.commit()
    await callback.message.edit_text(f"✅ Все результаты теста #{q_id} удалены.", reply_markup=None)


# ============================================================
# ВЫДАТЬ ПРЕМИУМ
# ============================================================
@dp.callback_query(F.data == "adm_premium")
async def adm_premium(callback: types.CallbackQuery, state: FSMContext):
    if not await is_any_admin(callback.from_user.id):
        return
    await callback.message.answer("🎁 Введите <b>user_id</b>:", parse_mode="HTML")
    await state.set_state(AdminStates.premium_uid)

@dp.message(AdminStates.premium_uid)
async def prem_uid(message: types.Message, state: FSMContext):
    try:
        await state.update_data(target_uid=int(message.text.strip()))
        await message.answer("📅 На сколько <b>дней</b>?", parse_mode="HTML")
        await state.set_state(AdminStates.premium_days)
    except ValueError:
        await message.answer("❌ Число")

@dp.message(AdminStates.premium_days)
async def prem_days(message: types.Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        d    = await state.get_data()
        uid  = d["target_uid"]
        await grant_premium(uid, days)
        await message.answer(f"✅ Премиум на <b>{days} дней</b> выдан {uid}", parse_mode="HTML")
        try:
            await bot.send_message(uid,
                f"🎉 Вам выдан <b>Премиум на {days} дней</b>!\nДоступны все тесты и разбор ошибок.",
                parse_mode="HTML")
        except Exception:
            pass
        await state.clear()
    except ValueError:
        await message.answer("❌ Число")


# ============================================================
# СТАТИСТИКА АДМИНКИ
# ============================================================
@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: types.CallbackQuery):
    if not await is_any_admin(callback.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_u = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_premium=1") as c:
            prem_u  = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM quizzes WHERE is_active=1") as c:
            total_q = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM results") as c:
            total_r = (await c.fetchone())[0]
        async with db.execute("SELECT AVG(percent) FROM results") as c:
            avg_pct = (await c.fetchone())[0] or 0
        async with db.execute("SELECT COUNT(*) FROM referrals") as c:
            refs    = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM purchased_tests") as c:
            stars_p = (await c.fetchone())[0]
        async with db.execute("""
            SELECT u.user_id, u.username, u.first_name, u.last_active_at,
                   q.title, r.score, r.total, r.finished
            FROM users u
            LEFT JOIN results r ON u.user_id=r.user_id
            LEFT JOIN quizzes q ON r.quiz_id=q.id
            WHERE u.last_active_at IS NOT NULL
            ORDER BY u.last_active_at DESC LIMIT 10
        """) as c:
            activity = await c.fetchall()

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: <b>{total_u}</b>\n"
        f"💎 Премиум: <b>{prem_u}</b>\n"
        f"📚 Тестов: <b>{total_q}</b>\n"
        f"📝 Прохождений: <b>{total_r}</b>\n"
        f"📈 Средний %: <b>{avg_pct:.1f}%</b>\n"
        f"👥 Рефералов: <b>{refs}</b>\n"
        f"⭐ Покупок Stars: <b>{stars_p}</b>\n\n"
        f"{'─'*20}\n"
        f"👥 <b>Последние активные:</b>\n\n"
    )
    for uid, uname, fname, last_at, qtitle, score, total, fin in activity:
        ustr = f"@{uname}" if uname else (fname or str(uid))
        dt   = (last_at or "")[:16]
        text += f"• {ustr} [{dt}]\n"
        if qtitle:
            text += f"  📘 {qtitle} — {score}/{total} {'✅' if fin else '⚠️'}\n"
        text += "\n"

    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    if len(text) > 3800:
        text = text[:3800] + "\n<i>...обрезано</i>"
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")


# ============================================================
# АПЕЛЛЯЦИИ В АДМИНКЕ
# ============================================================
@dp.callback_query(F.data == "adm_appeals")
async def adm_appeals(callback: types.CallbackQuery):
    uid     = callback.from_user.id
    sec_ids = await get_admin_sections(uid)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT a.id, a.user_id, u.username, q.title, a.question_index, a.message, a.created_at
            FROM appeals a
            JOIN quizzes q ON a.quiz_id=q.id
            LEFT JOIN users u ON a.user_id=u.user_id
            WHERE q.section_id IN ({}) AND a.status='pending'
            ORDER BY a.created_at DESC
        """.format(",".join("?" * len(sec_ids))), sec_ids) as c:
            rows = await c.fetchall()

    if not rows:
        b = InlineKeyboardBuilder()
        b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
        return await callback.message.edit_text(
            "⚖️ Новых апелляций нет.", reply_markup=b.as_markup()
        )

    text = "⚖️ <b>Апелляции:</b>\n\n"
    b    = InlineKeyboardBuilder()
    for a_id, a_uid, uname, qtitle, q_idx, msg, dt in rows:
        ustr = f"@{uname}" if uname else str(a_uid)
        text += (f"<b>#{a_id}</b> [{dt[:16]}]\n"
                 f"От: {ustr} | Тест: {qtitle} | Вопрос #{q_idx+1}\n"
                 f"<i>{msg[:100]}</i>\n\n")
        b.row(InlineKeyboardButton(text=f"✅ Закрыть #{a_id}",
                                    callback_data=f"close_appeal_{a_id}"))

    b.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    if len(text) > 3800:
        text = text[:3800] + "\n<i>...обрезано</i>"
    await callback.message.edit_text(text, reply_markup=b.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("close_appeal_"))
async def close_appeal(callback: types.CallbackQuery):
    a_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE appeals SET status='closed', handled_by=?, handled_at=datetime('now') WHERE id=?",
            (callback.from_user.id, a_id)
        )
        await db.commit()
    await callback.answer("✅ Апелляция закрыта", show_alert=True)
    await adm_appeals(callback)

# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    await init_db()
    logger.info("✅ ENT Quiz Bot запущен.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
