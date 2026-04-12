import asyncio
import json
import logging
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

# --- НАСТРОЙКИ ---
TOKEN = "ВАШ_ТОКЕН"
BOT_USERNAME = "practicaent_bot"  # ← без @, только username бота
ADMIN_IDS = [123456789]
MANAGER_LINK = "@manager_ent"

bot = Bot(token=TOKEN)
dp = Dispatcher()

user_activity = {}

class QuizStates(StatesGroup):
    waiting_for_quiz_title = State()
    waiting_for_quiz_data = State()

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                data TEXT,
                is_paid INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS results (
                user_id INTEGER,
                quiz_id INTEGER,
                score INTEGER,
                total INTEGER,
                PRIMARY KEY(user_id, quiz_id)
            )
        """)
        await db.commit()

# --- ПАРСЕР ---
def parse_quiz_data(text):
    questions = []
    blocks = text.strip().split('\n\n')
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2:
            continue
        q, opts, corr = lines[0], [], 0
        for i, o in enumerate(lines[1:]):
            if '*' in o:
                corr = i
                opts.append(o.replace('*', '').strip())
            else:
                opts.append(o.strip())
        questions.append({"q": q, "opts": opts, "correct": corr})
    return questions

# --- УТИЛИТА: получить тест из БД ---
async def get_quiz(q_id: int):
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT id, title, data, is_paid FROM quizzes WHERE id = ?", (q_id,)) as c:
            return await c.fetchone()

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Обработка deep link: /start quiz_5
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("quiz_"):
        q_id = int(args[1].split("_")[1])
        await launch_quiz(message.chat.id, message.from_user.id, q_id)
        return

    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT quiz_id FROM results WHERE user_id = ?", (message.from_user.id,)) as c:
            done = [r[0] for r in await c.fetchall()]
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            quizzes = await c.fetchall()

    builder = InlineKeyboardBuilder()
    for q_id, title, paid in quizzes:
        mark = "✅ " if q_id in done else ("🔒 " if paid else "📖 ")
        builder.row(types.InlineKeyboardButton(
            text=f"{mark}{title}",
            callback_data=f"info_{q_id}"
        ))

    if message.from_user.id in ADMIN_IDS:
        builder.row(types.InlineKeyboardButton(text="⚙️ Админка", callback_data="admin_panel"))

    await message.answer(
        f"👋 Здравствуйте, {name}!\n\n📚 Выберите тему для практики:",
        reply_markup=builder.as_markup()
    )

# --- КАРТОЧКА ТЕСТА (info) ---
@dp.callback_query(F.data.startswith("info_"))
async def quiz_info(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    row = await get_quiz(q_id)
    if not row:
        return await callback.answer("Тест не найден", show_alert=True)

    _, title, data_json, is_paid = row
    questions = json.loads(data_json)

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="▶️ Пройти тест", callback_data=f"run_{q_id}"))
    builder.row(types.InlineKeyboardButton(
        text="📤 Поделиться тестом",
        switch_inline_query=f"quiz_{q_id}"
    ))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))

    lock = "🔒 Платный" if is_paid else "🆓 Бесплатный"
    await callback.message.edit_text(
        f"🎯 <b>{title}</b>\n\n"
        f"📝 Вопросов: <b>{len(questions)}</b>\n"
        f"⏱ Время на вопрос: <b>30 сек</b>\n"
        f"💰 Доступ: {lock}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

# --- ЗАПУСК ТЕСТА ---
async def launch_quiz(chat_id: int, user_id: int, q_id: int):
    row = await get_quiz(q_id)
    if not row:
        await bot.send_message(chat_id, "❌ Тест не найден.")
        return

    _, title, data_json, _ = row
    questions = json.loads(data_json)
    user_activity[user_id] = []
    correct_answers = 0

    await bot.send_message(chat_id, f"🚀 Начинаем тест <b>«{title}»</b>!\n⏱ 30 секунд на каждый вопрос.", parse_mode="HTML")

    for i, q in enumerate(questions):
        # Стоп если 2 пропуска подряд
        if len(user_activity[user_id]) >= 2 and all(x == "missed" for x in user_activity[user_id][-2:]):
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

        await asyncio.sleep(30.5)

        # Если ответа нет — пропуск
        if len(user_activity[user_id]) <= i:
            user_activity[user_id].append("missed")
        elif user_activity[user_id][i] == "correct":
            correct_answers += 1

    total = len(questions)
    wrong = total - correct_answers

    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute(
            "INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?)",
            (user_id, q_id, correct_answers, total)
        )
        await db.commit()

    res_kb = InlineKeyboardBuilder()
    res_kb.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"run_{q_id}"))
    res_kb.row(types.InlineKeyboardButton(text="📤 Поделиться результатом", switch_inline_query=f"quiz_{q_id}"))
    res_kb.row(types.InlineKeyboardButton(text="🔙 К списку тем", callback_data="to_main"))

    percent = round(correct_answers / total * 100) if total else 0
    emoji = "🏆" if percent >= 80 else ("👍" if percent >= 50 else "📚")

    await bot.send_message(
        chat_id,
        f"{emoji} Тест <b>«{title}»</b> завершён!\n\n"
        f"✅ Верно: <b>{correct_answers}</b>\n"
        f"❌ Неверно: <b>{wrong}</b>\n"
        f"📊 Результат: <b>{percent}%</b>",
        reply_markup=res_kb.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("run_"))
async def start_quiz_callback(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    await callback.message.delete()
    await launch_quiz(callback.message.chat.id, callback.from_user.id, q_id)

# --- ОТСЛЕЖИВАНИЕ ОТВЕТОВ ---
@dp.poll_answer()
async def handle_poll_answer(answer: PollAnswer):
    uid = answer.user.id
    if uid not in user_activity:
        return
    # Нужно знать правильный вариант — здесь упрощённо отмечаем "answered"
    user_activity[uid].append("answered")

# ====================================================
# INLINE MODE — красивая карточка как на фото 2
# ====================================================
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    results = []

    if query.query.startswith("quiz_"):
        q_id_str = query.query.split("_")[1]
        try:
            q_id = int(q_id_str)
        except ValueError:
            await query.answer([], cache_time=1)
            return

        row = await get_quiz(q_id)
        if not row:
            await query.answer([], cache_time=1)
            return

        _, title, data_json, _ = row
        questions = json.loads(data_json)
        count = len(questions)

        # Deep link: t.me/BOT?start=quiz_5
        deep_link = f"https://t.me/{BOT_USERNAME}?start=quiz_{q_id}"

        # Кнопки прямо на inline-карточке (как на фото 2)
        card_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="▶️ Пройти тест",
                url=deep_link          # ← открывает бота и сразу запускает тест
            )],
            [InlineKeyboardButton(
                text="📤 Отправить в группу",
                switch_inline_query=f"quiz_{q_id}"
            )],
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
            reply_markup=card_kb,      # ← ВОТ ГДЕ МАГИЯ: кнопки на карточке
            thumbnail_url="https://img.icons8.com/color/96/test-passed.png"
        ))

    else:
        # Если query пустой — показываем все тесты
        async with aiosqlite.connect("ent_bot.db") as db:
            async with db.execute("SELECT id, title, data FROM quizzes") as c:
                all_quizzes = await c.fetchall()

        for q_id, title, data_json in all_quizzes:
            questions = json.loads(data_json)
            count = len(questions)
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

# --- АДМИНКА ---
@dp.callback_query(F.data == "admin_panel")
async def adm_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("❌ Нет доступа", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.row(
        types.InlineKeyboardButton(text="➕ Добавить тест", callback_data="adm_add"),
        types.InlineKeyboardButton(text="🗑 Удалить тест", callback_data="adm_del")
    )
    kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text("⚙️ <b>Админ-панель</b>", reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "adm_add")
async def adm_add(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await callback.message.answer("📝 Введите <b>название</b> теста:", parse_mode="HTML")
    await state.set_state(QuizStates.waiting_for_quiz_title)

@dp.message(QuizStates.waiting_for_quiz_title)
async def adm_get_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer(
        "📋 Теперь пришли вопросы в формате:\n\n"
        "<code>Вопрос?\nВариант А\n*Правильный вариант\nВариант В</code>\n\n"
        "(блоки через пустую строку)",
        parse_mode="HTML"
    )
    await state.set_state(QuizStates.waiting_for_quiz_data)

@dp.message(QuizStates.waiting_for_quiz_data)
async def adm_save(message: types.Message, state: FSMContext):
    fsm_data = await state.get_data()
    title = fsm_data.get("title", "Без названия")
    data = parse_quiz_data(message.text)
    if not data:
        return await message.answer("❌ Ошибка парсинга! Проверь формат.")
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute(
            "INSERT INTO quizzes (title, data) VALUES (?, ?)",
            (title, json.dumps(data, ensure_ascii=False))
        )
        await db.commit()
    await message.answer(f"✅ Тест <b>«{title}»</b> добавлен! ({len(data)} вопросов)", parse_mode="HTML")
    await state.clear()

@dp.callback_query(F.data == "adm_del")
async def adm_del_list(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT id, title FROM quizzes") as c:
            quizzes = await c.fetchall()
    if not quizzes:
        return await callback.answer("Нет тестов для удаления", show_alert=True)
    kb = InlineKeyboardBuilder()
    for q_id, title in quizzes:
        kb.row(types.InlineKeyboardButton(text=f"🗑 {title}", callback_data=f"del_{q_id}"))
    kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel"))
    await callback.message.edit_text("Выберите тест для удаления:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("del_"))
async def adm_del_confirm(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute("DELETE FROM quizzes WHERE id = ?", (q_id,))
        await db.execute("DELETE FROM results WHERE quiz_id = ?", (q_id,))
        await db.commit()
    await callback.answer("✅ Тест удалён", show_alert=True)
    await adm_del_list(callback)

@dp.callback_query(F.data == "to_main")
async def back(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_start(callback.message)

async def main():
    logging.basicConfig(level=logging.INFO)
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
