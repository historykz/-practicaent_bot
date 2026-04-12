import asyncio
import json
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, PollAnswer

# --- НАСТРОЙКИ ---
TOKEN = "8634239927:AAEBAMELMPHeG_1Y1OJ7ZyeBLLr_ITohX08"
ADMIN_IDS = [5048547918]  # Твой ID вставлен
MANAGER_LINK = "@manager_ent"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Хранилище для отслеживания активности (пропусков)
user_activity = {} # {user_id: [responses]}

class QuizStates(StatesGroup):
    waiting_for_quiz = State()

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS quizzes 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, data TEXT, is_paid INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS results 
            (user_id INTEGER, quiz_id INTEGER, score INTEGER, total INTEGER, PRIMARY KEY(user_id, quiz_id))""")
        await db.commit()

# --- ПАРСЕР ТЕКСТА ---
def parse_quiz_data(text):
    questions = []
    blocks = text.strip().split('\n\n')
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2: continue
        q, opts, corr = lines[0], [], 0
        for i, o in enumerate(lines[1:]):
            if '*' in o:
                corr = i
                opts.append(o.replace('*', '').strip())
            else: opts.append(o.strip())
        questions.append({"q": q, "opts": opts, "correct": corr})
    return questions

# --- ГЛАВНОЕ МЕНЮ С ГАЛОЧКАМИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT quiz_id FROM results WHERE user_id = ?", (message.from_user.id,)) as c:
            done = [r[0] for r in await c.fetchall()]
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            all_quizzes = await c.fetchall()

    builder = InlineKeyboardBuilder()
    for q_id, title, paid in all_quizzes:
        mark = "✅ " if q_id in done else ("🔒 " if paid else "📖 ")
        builder.row(types.InlineKeyboardButton(text=f"{mark}{title}", callback_data=f"info_{q_id}"))
    
    if message.from_user.id in ADMIN_IDS:
        builder.row(types.InlineKeyboardButton(text="⚙️ Админка", callback_data="admin_panel"))

    await message.answer(
        f"Здравствуйте, {name}\nРад приветствовать, что усиленно готовитесь к ЕНТ и желаете практиковаться.\n\nВыберите тему для практики:",
        reply_markup=builder.as_markup()
    )

# --- ИНФО И ЗАПУСК ТЕСТА ---
@dp.callback_query(F.data.startswith("info_"))
async def info_quiz(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT title, data, is_paid FROM quizzes WHERE id = ?", (q_id,)) as c:
            quiz = await c.fetchone()
    
    if quiz[2] and callback.from_user.id not in ADMIN_IDS:
        return await callback.message.answer(f"Это закрытая тема. Менеджер: {MANAGER_LINK}")

    q_count = len(json.loads(quiz[1]))
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🚀 Пройти тест", callback_data=f"run_{q_id}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    
    await callback.message.edit_text(
        f"🏁 Тема: {quiz[0]}\n❓ Вопросов: {q_count}\n⏱ Таймер: 30 сек\n\nНачать?",
        reply_markup=builder.as_markup()
    )

# --- ЛОГИКА ТЕСТА С ПРОВЕРКОЙ НА 2 ПРОПУСКА ---
@dp.callback_query(F.data.startswith("run_"))
async def start_quiz(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    uid = callback.from_user.id
    user_activity[uid] = [] 

    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT data, title FROM quizzes WHERE id = ?", (q_id,)) as c:
            row = await c.fetchone()
    
    questions = json.loads(row[0])
    await callback.message.answer(f"🏁 Начинаем: {row[1]}")
    
    for i, q in enumerate(questions):
        # Если пропустил 2 вопроса подряд — СТОП
        if len(user_activity[uid]) >= 2 and all(x == "missed" for x in user_activity[uid][-2:]):
            break

        await bot.send_poll(
            chat_id=callback.message.chat.id,
            question=f"[{i+1}/{len(questions)}] {q['q']}",
            options=q['opts'],
            type='quiz',
            correct_option_id=q['correct'],
            open_period=30,
            is_anonymous=False,
            protect_content=True
        )
        
        await asyncio.sleep(30.5)
        if len(user_activity[uid]) <= i:
            user_activity[uid].append("missed")

    # ИТОГОВАЯ КАРТОЧКА (КАК НА ФОТО 3)
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?)", (uid, q_id, 0, len(questions)))
        await db.commit()

    res_kb = InlineKeyboardBuilder()
    res_kb.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"run_{q_id}"))
    res_kb.row(types.InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=f"quiz_{q_id}"))
    res_kb.row(types.InlineKeyboardButton(text="🔙 К выбору тем", callback_data="to_main"))
    
    await bot.send_message(callback.message.chat.id, 
        f"🏁 Тест «{row[1]}» завершен!\n\nВы можете поделиться результатом или пройти другой тест.", 
        reply_markup=res_kb.as_markup())

@dp.poll_answer()
async def handle_poll_answer(answer: PollAnswer):
    uid = answer.user.id
    if uid in user_activity:
        user_activity[uid].append("answered")

# --- INLINE MODE (СЕРАЯ ПАНЕЛЬ ФОТО 2/4) ---
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    if "quiz_" in query.query:
        q_id = query.query.split("_")[1]
        results = [InlineQueryResultArticle(
            id=q_id,
            title=f"Тест #{q_id}",
            description="30 сек на вопрос · Нажми, чтобы отправить",
            input_message_content=InputTextMessageContent(message_text=f"Нажми на панель ниже, чтобы начать тест!"),
            thumb_url="https://img.icons8.com/color/96/test-passed.png"
        )]
        await query.answer(results, cache_time=1)

# --- АДМИНКА ---
@dp.callback_query(F.data == "admin_panel")
async def adm_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="➕ Добавить", callback_data="adm_add"), 
           types.InlineKeyboardButton(text="🗑 Удалить", callback_data="adm_del"))
    kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text("Панель управления:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "adm_add")
async def adm_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришли вопросы. Пример:\nВопрос?\nОтвет1*\nОтвет2")
    await state.set_state(QuizStates.waiting_for_quiz)

@dp.message(QuizStates.waiting_for_quiz)
async def adm_save(message: types.Message, state: FSMContext):
    data = parse_quiz_data(message.text)
    if not data: return await message.answer("Ошибка формата текста!")
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute("INSERT INTO quizzes (title, data) VALUES (?, ?)", (data[0]['q'][:25], json.dumps(data)))
        await db.commit()
    await message.answer("✅ Тест успешно сохранен в базу!")
    await state.clear()

@dp.callback_query(F.data == "to_main")
async def back_to_start(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_start(callback.message)

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
