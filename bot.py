import asyncio
import json
import logging
from datetime import datetime, timedelta
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineQueryResultArticle, InputTextMessageContent,
    PollAnswer, InlineKeyboardMarkup, InlineKeyboardButton
)
 
# ============================================================
# НАСТРОЙКИ
# ============================================================
TOKEN = "8634239927:AAG2KLGHGvGMOkeDQyymMKzKOluUjqaxWxg"
BOT_USERNAME = "practicaent_bot"
ADMIN_IDS = [5048547918]
MANAGER_LINK = "@historyentk_bot"
REFERRAL_BONUS_COUNT = 3  # сколько друзей нужно для бонуса
 
bot = Bot(token=TOKEN)
dp = Dispatcher()
 
# Хранилище активных тестов: {user_id: {"answers": [], "q_id": int}}
active_quizzes = {}
 
# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================
class QuizStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_data = State()
 
class PremiumStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_days = State()
 
# ============================================================
# БАЗА ДАННЫХ
# ============================================================
async def init_db():
    async with aiosqlite.connect("ent_bot.db") as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_premium INTEGER DEFAULT 0,
                premium_until TEXT,
                invited_by INTEGER
            )
        """)
        # Таблица тестов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                data TEXT,
                is_paid INTEGER DEFAULT 0
            )
        """)
        # Таблица результатов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS results (
                user_id INTEGER,
                quiz_id INTEGER,
                score INTEGER,
                total INTEGER,
                percent REAL,
                PRIMARY KEY(user_id, quiz_id)
            )
        """)
        # Таблица рефералов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                inviter_id INTEGER,
                invited_user_id INTEGER PRIMARY KEY
            )
        """)
        await db.commit()
 
# ============================================================
# УТИЛИТЫ
# ============================================================
def parse_quiz_data(text: str) -> list:
    """Парсит текст с вопросами в список словарей."""
    questions = []
    blocks = text.strip().split('\n\n')
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 3:
            continue
        question = lines[0]
        opts = []
        correct = 0
        for i, line in enumerate(lines[1:]):
            if line.startswith('*'):
                correct = i
                opts.append(line[1:].strip())
            else:
                opts.append(line.strip())
        if len(opts) >= 2:
            questions.append({"q": question, "opts": opts, "correct": correct})
    return questions
 
async def get_quiz(q_id: int):
    """Получить тест по ID."""
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT id, title, data, is_paid FROM quizzes WHERE id = ?", (q_id,)) as c:
            return await c.fetchone()
 
async def register_user(user: types.User, invited_by: int = None):
    """Зарегистрировать пользователя если его нет."""
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user.id,)) as c:
            exists = await c.fetchone()
        if not exists:
            await db.execute(
                "INSERT INTO users (user_id, username, first_name, invited_by) VALUES (?, ?, ?, ?)",
                (user.id, user.username, user.first_name, invited_by)
            )
            # Записываем реферала
            if invited_by and invited_by != user.id:
                await db.execute(
                    "INSERT OR IGNORE INTO referrals (inviter_id, invited_user_id) VALUES (?, ?)",
                    (invited_by, user.id)
                )
                # Проверяем бонус: каждые REFERRAL_BONUS_COUNT рефералов → 7 дней премиума
                async with db.execute(
                    "SELECT COUNT(*) FROM referrals WHERE inviter_id = ?", (invited_by,)
                ) as c2:
                    ref_count = (await c2.fetchone())[0]
                if ref_count % REFERRAL_BONUS_COUNT == 0:
                    await grant_premium(invited_by, 7, db)
                    await bot.send_message(
                        invited_by,
                        f"🎁 Вы пригласили {ref_count} друзей и получили <b>7 дней Премиума</b> бесплатно!",
                        parse_mode="HTML"
                    )
            await db.commit()
 
async def grant_premium(user_id: int, days: int, db=None):
    """Выдать премиум пользователю на N дней."""
    until = (datetime.now() + timedelta(days=days)).isoformat()
    if db:
        await db.execute(
            "UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?",
            (until, user_id)
        )
    else:
        async with aiosqlite.connect("ent_bot.db") as db2:
            await db2.execute(
                "UPDATE users SET is_premium = 1, premium_until = ? WHERE user_id = ?",
                (until, user_id)
            )
            await db2.commit()
 
async def check_premium(user_id: int) -> bool:
    """Проверить актуальность премиума."""
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute(
            "SELECT is_premium, premium_until FROM users WHERE user_id = ?", (user_id,)
        ) as c:
            row = await c.fetchone()
    if not row or not row[0]:
        return False
    if row[1]:
        until = datetime.fromisoformat(row[1])
        if datetime.now() > until:
            # Срок истёк — снимаем премиум
            async with aiosqlite.connect("ent_bot.db") as db:
                await db.execute(
                    "UPDATE users SET is_premium = 0 WHERE user_id = ?", (user_id,)
                )
                await db.commit()
            return False
    return True
 
def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура главного меню."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📚 Выбрать тест", callback_data="menu_tests"))
    builder.row(types.InlineKeyboardButton(text="📊 Мои результаты", callback_data="menu_results"))
    builder.row(types.InlineKeyboardButton(text="👥 Пригласить друзей", callback_data="menu_referral"))
    builder.row(
        types.InlineKeyboardButton(text="ℹ️ Помощь", callback_data="menu_help"),
        types.InlineKeyboardButton(text="👨‍💼 Менеджер", url=f"https://t.me/{MANAGER_LINK.lstrip('@')}")
    )
    if is_admin:
        builder.row(types.InlineKeyboardButton(text="⚙️ Админка", callback_data="admin_panel"))
    return builder.as_markup()
 
# ============================================================
# СТАРТ / ГЛАВНОЕ МЕНЮ
# ============================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    args = message.text.split()
    invited_by = None
 
    # Обработка deep link
    if len(args) > 1:
        param = args[1]
        # Реферальная ссылка: ?start=ref_12345
        if param.startswith("ref_"):
            try:
                invited_by = int(param.split("_")[1])
            except (IndexError, ValueError):
                pass
        # Запуск теста: ?start=quiz_5
        elif param.startswith("quiz_"):
            await register_user(message.from_user)
            try:
                q_id = int(param.split("_")[1])
                await launch_quiz(message.chat.id, message.from_user.id, q_id)
            except (IndexError, ValueError):
                pass
            return
 
    await register_user(message.from_user, invited_by)
    is_admin = message.from_user.id in ADMIN_IDS
    name = message.from_user.first_name or "друг"
 
    await message.answer(
        f"👋 Привет, <b>{name}</b>!\n\n"
        f"Добро пожаловать в бот для подготовки к ЕНТ 🎓\n\n"
        f"Выбери раздел ниже:",
        reply_markup=main_menu_kb(is_admin),
        parse_mode="HTML"
    )
 
@dp.callback_query(F.data == "to_main")
async def to_main(callback: types.CallbackQuery):
    is_admin = callback.from_user.id in ADMIN_IDS
    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>\n\nВыбери раздел:",
        reply_markup=main_menu_kb(is_admin),
        parse_mode="HTML"
    )
 
# ============================================================
# РАЗДЕЛ: ВЫБРАТЬ ТЕСТ
# ============================================================
@dp.callback_query(F.data == "menu_tests")
async def menu_tests(callback: types.CallbackQuery):
    async with aiosqlite.connect("ent_bot.db") as db:
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
        if q_id in done:
            mark = "✅ "
        elif is_paid and not is_premium:
            mark = "🔒 "
        else:
            mark = "📖 "
        builder.row(types.InlineKeyboardButton(
            text=f"{mark}{title}",
            callback_data=f"info_{q_id}"
        ))
 
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text(
        "📚 <b>Список тестов</b>\n\n"
        "✅ — пройден | 🔒 — Премиум | 📖 — бесплатно",
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
    questions = json.loads(data_json)
    is_premium = await check_premium(callback.from_user.id)
 
    lock_text = "🔒 Премиум" if is_paid else "🆓 Бесплатно"
 
    builder = InlineKeyboardBuilder()
    if is_paid and not is_premium:
        builder.row(types.InlineKeyboardButton(text="💳 Купить доступ", callback_data="buy_premium"))
        builder.row(types.InlineKeyboardButton(
            text="👨‍💼 Связаться с менеджером",
            url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
        ))
    else:
        builder.row(types.InlineKeyboardButton(text="▶️ Начать тест", callback_data=f"run_{q_id}"))
 
    builder.row(types.InlineKeyboardButton(
        text="📤 Поделиться тестом",
        switch_inline_query=f"quiz_{q_id}"
    ))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="menu_tests"))
 
    await callback.message.edit_text(
        f"🎯 <b>{title}</b>\n\n"
        f"📝 Вопросов: <b>{len(questions)}</b>\n"
        f"⏱ Время на вопрос: <b>30 сек</b>\n"
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
    builder.row(types.InlineKeyboardButton(
        text="👨‍💼 Связаться с менеджером",
        url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
    ))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="menu_tests"))
    await callback.message.edit_text(
        "💎 <b>Премиум доступ</b>\n\n"
        "Что входит:\n"
        "• 1000+ вопросов\n"
        "• Подробная статистика\n"
        "• Разбор ошибок\n\n"
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
 
    await callback.message.delete()
    await launch_quiz(callback.message.chat.id, callback.from_user.id, q_id)
 
async def launch_quiz(chat_id: int, user_id: int, q_id: int):
    """Основная функция запуска теста."""
    row = await get_quiz(q_id)
    if not row:
        await bot.send_message(chat_id, "❌ Тест не найден.")
        return
 
    _, title, data_json, is_paid = row
    is_premium = await check_premium(user_id)
 
    if is_paid and not is_premium:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="💳 Купить доступ", callback_data="buy_premium"))
        await bot.send_message(
            chat_id,
            "🔒 Этот тест доступен только для Премиум пользователей.",
            reply_markup=builder.as_markup()
        )
        return
 
    questions = json.loads(data_json)
    active_quizzes[user_id] = {
        "q_id": q_id,
        "title": title,
        "answers": [],       # "correct" / "wrong" / "missed"
        "wrong_questions": []  # для разбора ошибок
    }
 
    await bot.send_message(
        chat_id,
        f"🚀 Начинаем тест <b>«{title}»</b>!\n"
        f"📝 {len(questions)} вопросов · ⏱ 30 сек на вопрос\n\n"
        f"Удачи! 🍀",
        parse_mode="HTML"
    )
 
    for i, q in enumerate(questions):
        # Стоп если 2 пропуска подряд
        answers = active_quizzes[user_id]["answers"]
        if len(answers) >= 2 and answers[-1] == "missed" and answers[-2] == "missed":
            await bot.send_message(chat_id, "⚠️ Вы пропустили 2 вопроса подряд. Тест остановлен.")
            break
 
        await bot.send_poll(
            chat_id=chat_id,
            question=f"[{i+1}/{len(questions)}] {q['q']}",
            options=q['opts'],
            type='quiz',
            correct_option_id=q['correct'],
            open_period=30,
            is_anonymous=False,
            protect_content=True
        )
 
        prev_len = len(active_quizzes[user_id]["answers"])
        await asyncio.sleep(31)
 
        # Если ответ не пришёл — пропуск
        if len(active_quizzes[user_id]["answers"]) == prev_len:
            active_quizzes[user_id]["answers"].append("missed")
            active_quizzes[user_id]["wrong_questions"].append(q)
 
    # Подводим итоги
    await finish_quiz(chat_id, user_id)
 
async def finish_quiz(chat_id: int, user_id: int):
    """Показать результат теста."""
    if user_id not in active_quizzes:
        return
 
    data = active_quizzes.pop(user_id)
    q_id = data["q_id"]
    title = data["title"]
    answers = data["answers"]
    wrong_questions = data["wrong_questions"]
 
    total = len(answers)
    correct = answers.count("correct")
    wrong = answers.count("wrong") + answers.count("missed")
    percent = round(correct / total * 100) if total else 0
 
    # Сохраняем результат
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO results (user_id, quiz_id, score, total, percent) VALUES (?, ?, ?, ?, ?)",
            (user_id, q_id, correct, total, percent)
        )
        await db.commit()
 
    emoji = "🏆" if percent >= 80 else ("👍" if percent >= 50 else "📚")
 
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔄 Пройти снова", callback_data=f"run_{q_id}"))
    builder.row(types.InlineKeyboardButton(text="📚 К тестам", callback_data="menu_tests"))
    builder.row(types.InlineKeyboardButton(
        text="📤 Поделиться результатом",
        switch_inline_query=f"quiz_{q_id}"
    ))
 
    # Разбор ошибок (только премиум)
    is_premium = await check_premium(user_id)
    if wrong_questions and is_premium:
        error_text = "\n\n📋 <b>Разбор ошибок:</b>\n"
        for i, q in enumerate(wrong_questions[:5], 1):  # показываем первые 5
            correct_ans = q['opts'][q['correct']]
            error_text += f"\n{i}. {q['q']}\n✅ Ответ: <b>{correct_ans}</b>\n"
    elif wrong_questions and not is_premium:
        error_text = "\n\n🔒 <i>Разбор ошибок доступен в Премиуме</i>"
    else:
        error_text = ""
 
    await bot.send_message(
        chat_id,
        f"{emoji} <b>Тест «{title}» завершён!</b>\n\n"
        f"✅ Правильных ответов: <b>{correct}</b>\n"
        f"❌ Неверных: <b>{wrong}</b>\n\n"
        f"📊 Результат: <b>{percent}%</b>"
        f"{error_text}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
 
# ============================================================
# ОТСЛЕЖИВАНИЕ ОТВЕТОВ НА ОПРОСЫ
# ============================================================
@dp.poll_answer()
async def handle_poll_answer(answer: PollAnswer):
    uid = answer.user.id
    if uid not in active_quizzes:
        return
 
    q_index = len(active_quizzes[uid]["answers"])
 
    # Получаем текущий вопрос чтобы проверить правильность
    q_id = active_quizzes[uid]["q_id"]
    row = await get_quiz(q_id)
    if not row:
        return
 
    questions = json.loads(row[2])
    if q_index >= len(questions):
        return
 
    current_q = questions[q_index]
    user_answer = answer.option_ids[0] if answer.option_ids else -1
 
    if user_answer == current_q["correct"]:
        active_quizzes[uid]["answers"].append("correct")
    else:
        active_quizzes[uid]["answers"].append("wrong")
        active_quizzes[uid]["wrong_questions"].append(current_q)
 
# ============================================================
# МОИ РЕЗУЛЬТАТЫ
# ============================================================
@dp.callback_query(F.data == "menu_results")
async def menu_results(callback: types.CallbackQuery):
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("""
            SELECT q.title, r.score, r.total, r.percent
            FROM results r
            JOIN quizzes q ON r.quiz_id = q.id
            WHERE r.user_id = ?
            ORDER BY r.percent DESC
        """, (callback.from_user.id,)) as c:
            results = await c.fetchall()
 
    if not results:
        builder = InlineKeyboardBuilder()
        builder.row(types.InlineKeyboardButton(text="📚 Выбрать тест", callback_data="menu_tests"))
        builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
        return await callback.message.edit_text(
            "📊 У вас пока нет результатов.\n\nПройдите первый тест!",
            reply_markup=builder.as_markup()
        )
 
    best = max(results, key=lambda x: x[3])
    text = f"📊 <b>Мои результаты</b>\n\n"
    text += f"🏅 Лучший результат: <b>{best[3]:.0f}%</b> — {best[0]}\n"
    text += f"📝 Тестов пройдено: <b>{len(results)}</b>\n\n"
    text += "─" * 25 + "\n\n"
 
    for title, score, total, percent in results:
        emoji = "🏆" if percent >= 80 else ("👍" if percent >= 50 else "📚")
        text += f"{emoji} <b>{title}</b>\n"
        text += f"   ✅ {score}/{total} · {percent:.0f}%\n\n"
 
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
 
# ============================================================
# РЕФЕРАЛЬНАЯ СИСТЕМА
# ============================================================
@dp.callback_query(F.data == "menu_referral")
async def menu_referral(callback: types.CallbackQuery):
    uid = callback.from_user.id
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{uid}"
 
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute(
            "SELECT COUNT(*) FROM referrals WHERE inviter_id = ?", (uid,)
        ) as c:
            ref_count = (await c.fetchone())[0]
 
    next_bonus = REFERRAL_BONUS_COUNT - (ref_count % REFERRAL_BONUS_COUNT)
    if next_bonus == REFERRAL_BONUS_COUNT:
        next_bonus = 0
 
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="📤 Поделиться ссылкой",
        url=f"https://t.me/share/url?url={ref_link}&text=Готовься к ЕНТ вместе со мной!"
    ))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
 
    bonus_text = (
        f"🎁 Ещё <b>{next_bonus}</b> приглашений → <b>7 дней Премиума</b> бесплатно!"
        if next_bonus > 0
        else "🎉 Вы получили бонус за приглашения!"
    )
 
    await callback.message.edit_text(
        f"👥 <b>Пригласить друзей</b>\n\n"
        f"Ваша реферальная ссылка:\n"
        f"<code>{ref_link}</code>\n\n"
        f"📊 Приглашено друзей: <b>{ref_count}</b>\n\n"
        f"{bonus_text}\n\n"
        f"<i>За каждые {REFERRAL_BONUS_COUNT} приглашённых друга — 7 дней Премиума!</i>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
 
# ============================================================
# ПОМОЩЬ
# ============================================================
@dp.callback_query(F.data == "menu_help")
async def menu_help(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="👨‍💼 Связаться с менеджером",
        url=f"https://t.me/{MANAGER_LINK.lstrip('@')}"
    ))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text(
        "ℹ️ <b>Помощь</b>\n\n"
        "📚 <b>Как проходить тесты?</b>\n"
        "Выбери тест из списка и нажми «Начать». "
        "На каждый вопрос даётся 30 секунд.\n\n"
        "💎 <b>Что даёт Премиум?</b>\n"
        "• Доступ ко всем тестам\n"
        "• Разбор ошибок после теста\n"
        "• Расширенная статистика\n\n"
        "👥 <b>Реферальная программа</b>\n"
        f"Пригласи {REFERRAL_BONUS_COUNT} друзей — получи 7 дней Премиума бесплатно!\n\n"
        "По всем вопросам — пишите менеджеру:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
 
# ============================================================
# INLINE MODE
# ============================================================
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    results = []
 
    if query.query.startswith("quiz_"):
        try:
            q_id = int(query.query.split("_")[1])
        except (IndexError, ValueError):
            await query.answer([], cache_time=1)
            return
 
        row = await get_quiz(q_id)
        if not row:
            await query.answer([], cache_time=1)
            return
 
        _, title, data_json, _ = row
        count = len(json.loads(data_json))
        deep_link = f"https://t.me/{BOT_USERNAME}?start=quiz_{q_id}"
 
        card_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Пройти тест", url=deep_link)],
            [InlineKeyboardButton(text="📤 Отправить в группу", switch_inline_query=f"quiz_{q_id}")],
            [InlineKeyboardButton(
                text="↗️ Поделиться",
                url=f"https://t.me/share/url?url={deep_link}&text=Пройди тест «{title}»!"
            )],
        ])
 
        results.append(InlineQueryResultArticle(
            id=str(q_id),
            title=f"🎲 Тест «{title}»",
            description=f"📝 {count} вопросов · ⏱ 30 сек",
            input_message_content=InputTextMessageContent(
                message_text=(
                    f"🎲 Тест <b>«{title}»</b>\n\n"
                    f"📝 {count} вопросов · ⏱ 30 сек на вопрос\n\n"
                    f"👇 Нажми кнопку ниже, чтобы начать!"
                ),
                parse_mode="HTML"
            ),
            reply_markup=card_kb,
            thumbnail_url="https://img.icons8.com/color/96/test-passed.png"
        ))
    else:
        # Показываем все тесты
        async with aiosqlite.connect("ent_bot.db") as db:
            async with db.execute("SELECT id, title, data FROM quizzes") as c:
                all_quizzes = await c.fetchall()
 
        for q_id, title, data_json in all_quizzes:
            count = len(json.loads(data_json))
            deep_link = f"https://t.me/{BOT_USERNAME}?start=quiz_{q_id}"
            card_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="▶️ Пройти тест", url=deep_link)],
                [InlineKeyboardButton(text="📤 Отправить в группу", switch_inline_query=f"quiz_{q_id}")],
            ])
            results.append(InlineQueryResultArticle(
                id=str(q_id),
                title=f"🎲 Тест «{title}»",
                description=f"📝 {count} вопросов · ⏱ 30 сек",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        f"🎲 Тест <b>«{title}»</b>\n\n"
                        f"📝 {count} вопросов · ⏱ 30 сек на вопрос\n\n"
                        f"👇 Нажми кнопку ниже, чтобы начать!"
                    ),
                    parse_mode="HTML"
                ),
                reply_markup=card_kb,
                thumbnail_url="https://img.icons8.com/color/96/test-passed.png"
            ))
 
    await query.answer(results, cache_time=5)
 
# ============================================================
# АДМИНКА
# ============================================================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет доступа", show_alert=True)
 
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Добавить тест", callback_data="adm_add"))
    builder.row(
        types.InlineKeyboardButton(text="🗑 Удалить тест", callback_data="adm_del"),
        types.InlineKeyboardButton(text="📋 Список тестов", callback_data="adm_list")
    )
    builder.row(types.InlineKeyboardButton(text="💰 Платный/Бесплатный", callback_data="adm_toggle"))
    builder.row(types.InlineKeyboardButton(text="🎁 Выдать Премиум", callback_data="adm_premium"))
    builder.row(types.InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
 
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
 
# --- Добавить тест ---
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
        "📋 Теперь отправь вопросы в формате:\n\n"
        "<code>Вопрос?\nВариант А\n*Правильный вариант\nВариант В\n\nСледующий вопрос?</code>\n\n"
        "<i>Блоки разделяй пустой строкой. * перед правильным ответом.</i>",
        parse_mode="HTML"
    )
    await state.set_state(QuizStates.waiting_for_data)
 
@dp.message(QuizStates.waiting_for_data)
async def adm_save_quiz(message: types.Message, state: FSMContext):
    fsm_data = await state.get_data()
    title = fsm_data.get("title", "Без названия")
    questions = parse_quiz_data(message.text)
 
    if not questions:
        return await message.answer(
            "❌ Не удалось распознать вопросы. Проверь формат и попробуй снова."
        )
 
    async with aiosqlite.connect("ent_bot.db") as db:
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
 
# --- Список тестов ---
@dp.callback_query(F.data == "adm_list")
async def adm_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            quizzes = await c.fetchall()
 
    if not quizzes:
        return await callback.answer("Тестов нет", show_alert=True)
 
    text = "📋 <b>Все тесты:</b>\n\n"
    for q_id, title, is_paid in quizzes:
        mark = "🔒" if is_paid else "🆓"
        text += f"<b>#{q_id}</b> {mark} {title}\n"
 
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
 
# --- Удалить тест ---
@dp.callback_query(F.data == "adm_del")
async def adm_del_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT id, title FROM quizzes") as c:
            quizzes = await c.fetchall()
 
    if not quizzes:
        return await callback.answer("Нет тестов для удаления", show_alert=True)
 
    builder = InlineKeyboardBuilder()
    for q_id, title in quizzes:
        builder.row(types.InlineKeyboardButton(
            text=f"🗑 {title}", callback_data=f"del_{q_id}"
        ))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(
        "🗑 Выберите тест для удаления:",
        reply_markup=builder.as_markup()
    )
 
@dp.callback_query(F.data.startswith("del_"))
async def adm_delete(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute("DELETE FROM quizzes WHERE id = ?", (q_id,))
        await db.execute("DELETE FROM results WHERE quiz_id = ?", (q_id,))
        await db.commit()
    await callback.answer("✅ Тест удалён", show_alert=True)
    await adm_del_list(callback)
 
# --- Платный/бесплатный ---
@dp.callback_query(F.data == "adm_toggle")
async def adm_toggle_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            quizzes = await c.fetchall()
 
    if not quizzes:
        return await callback.answer("Нет тестов", show_alert=True)
 
    builder = InlineKeyboardBuilder()
    for q_id, title, is_paid in quizzes:
        mark = "🔒" if is_paid else "🆓"
        builder.row(types.InlineKeyboardButton(
            text=f"{mark} {title}", callback_data=f"toggle_{q_id}"
        ))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(
        "💰 Выберите тест для смены статуса:\n🔒 — платный | 🆓 — бесплатный",
        reply_markup=builder.as_markup()
    )
 
@dp.callback_query(F.data.startswith("toggle_"))
async def adm_toggle(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT is_paid FROM quizzes WHERE id = ?", (q_id,)) as c:
            row = await c.fetchone()
        new_status = 0 if row[0] else 1
        await db.execute("UPDATE quizzes SET is_paid = ? WHERE id = ?", (new_status, q_id))
        await db.commit()
    status_text = "🔒 Платный" if new_status else "🆓 Бесплатный"
    await callback.answer(f"Статус изменён: {status_text}", show_alert=True)
    await adm_toggle_list(callback)
 
# --- Выдать премиум ---
@dp.callback_query(F.data == "adm_premium")
async def adm_give_premium(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer(
        "🎁 Введите <b>ID пользователя</b>, которому хотите выдать Премиум:",
        parse_mode="HTML"
    )
    await state.set_state(PremiumStates.waiting_for_user_id)
 
@dp.message(PremiumStates.waiting_for_user_id)
async def adm_premium_get_id(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        await state.update_data(target_user_id=uid)
        await message.answer("📅 На сколько <b>дней</b> выдать Премиум?", parse_mode="HTML")
        await state.set_state(PremiumStates.waiting_for_days)
    except ValueError:
        await message.answer("❌ Введите числовой ID пользователя")
 
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
                f"🎉 Вам выдан <b>Премиум доступ на {days} дней</b>!\n\n"
                f"Теперь вам доступны все тесты и разбор ошибок.",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число дней")
 
# --- Статистика ---
@dp.callback_query(F.data == "adm_stats")
async def adm_stats(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1") as c:
            premium_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM quizzes") as c:
            total_quizzes = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM results") as c:
            total_results = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM referrals") as c:
            total_refs = (await c.fetchone())[0]
 
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text(
        f"📊 <b>Статистика бота</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"💎 Премиум: <b>{premium_users}</b>\n"
        f"📚 Тестов: <b>{total_quizzes}</b>\n"
        f"📝 Прохождений: <b>{total_results}</b>\n"
        f"👥 Рефералов: <b>{total_refs}</b>",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
 
# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    await init_db()
    await dp.start_polling(bot)
 
if __name__ == "__main__":
    asyncio.run(main())
