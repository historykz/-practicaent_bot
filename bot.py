import asyncio
import json
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, PollAnswer
from aiogram.client.default import DefaultBotProperties

# --- НАСТРОЙКИ ---
TOKEN = "8634239927:AAEBAMELMPHeG_1Y1OJ7ZyeBLLr_ITohX08"
ADMIN_IDS = [5048547918] 
MANAGER_LINK = "@manager_ent"

# Используем DefaultBotProperties для parse_mode
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

user_activity = {}

class QuizStates(StatesGroup):
    waiting_for_quiz = State()

async def init_db():
    async with aiosqlite.connect("ent_bot.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS quizzes 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, data TEXT, is_paid INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS results 
            (user_id INTEGER, quiz_id INTEGER, score INTEGER, total INTEGER, PRIMARY KEY(user_id, quiz_id))""")
        await db.commit()

# --- ПАРСЕР ---
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
                options = o.replace('*', '').strip()
                opts.append(options)
            else: opts.append(o.strip())
        questions.append({"q": q, "opts": opts, "correct": corr})
    return questions

# --- ГЛАВНОЕ МЕНЮ (С ПОДДЕРЖКОЙ ГЛУБОКИХ ССЫЛОК) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject = None):
    # Если человек пришел по кнопке "Пройти тест" из другого чата
    if command and command.args and command.args.startswith("run_"):
        q_id = int(command.args.split("_")[1])
        return await start_quiz_logic(message, q_id)

    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT quiz_id FROM results WHERE user_id = ?", (message.from_user.id,)) as c:
            done = [r[0] for r in await c.fetchall()]
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            quizzes = await c.fetchall()

    builder = InlineKeyboardBuilder()
    for q_id, title, paid in quizzes:
        mark = "✅ " if q_id in done else ("🔒 " if paid else "📖 ")
        builder.row(types.InlineKeyboardButton(text=f"{mark}{title}", callback_data=f"info_{q_id}"))
    
    if message.from_user.id in ADMIN_IDS:
        builder.row(types.InlineKeyboardButton(text="⚙️ Админка", callback_data="admin_panel"))

    await message.answer(f"Здравствуйте, {name}\nВыберите тему для практики:", reply_markup=builder.as_markup())

# --- ЛОГИКА ТЕСТА ---
async def start_quiz_logic(message: types.Message, q_id: int):
    uid = message.from_user.id
    user_activity[uid] = []

    async with aiosqlite.connect("ent_bot.db") as db:
        async with db.execute("SELECT data, title FROM quizzes WHERE id = ?", (q_id,)) as c:
            row = await c.fetchone()
    
    if not row: return
    questions = json.loads(row[0])

    await message.answer(f"🏁 <b>Старт теста: {row[1]}</b>")

    for i, q in enumerate(questions):
        if len(user_activity.get(uid, [])) >= 2 and all(x == "missed" for x in user_activity[uid][-2:]):
            await message.answer("⚠️ Тест остановлен (2 пропуска).")
            break

        await bot.send_poll(
            chat_id=message.chat.id,
            question=f"[{i+1}/{len(questions)}] {q['q']}",
            options=q['opts'],
            type='quiz',
            correct_option_id=q['correct'],
            open_period=30,
            is_anonymous=False,
            protect_content=True
        )
        await asyncio.sleep(30.5)
        if uid in user_activity and len(user_activity[uid]) <= i:
            user_activity[uid].append("missed")

    # Итоги
    res_kb = InlineKeyboardBuilder()
    res_kb.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"run_{q_id}"))
    res_kb.row(types.InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=f"quiz_{q_id}"))
    res_kb.row(types.InlineKeyboardButton(text="🔙 В меню", callback_data="to_main"))
    
    await message.answer(f"🏁 Тест «{row[1]}» завершен!", reply_markup=res_kb.as_markup())

@dp.callback_query(F.data.startswith("run_"))
async def run_callback(callback: types.CallbackQuery):
    await callback.answer()
    q_id = int(callback.data.split("_")[1])
    await start_quiz_logic(callback.message, q_id)

@dp.poll_answer()
async def handle_poll_answer(answer: PollAnswer):
    uid = answer.user.id
    if uid in user_activity:
        user_activity[uid].append("answered")

# --- ИСПРАВЛЕННЫЙ INLINE MODE (КАК НА ФОТО 2) ---
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    if "quiz_" in query.query:
        q_id = query.query.split("_")[1]
        
        async with aiosqlite.connect("ent_bot.db") as db:
            async with db.execute("SELECT title, data FROM quizzes WHERE id = ?", (q_id,)) as c:
                quiz = await c.fetchone()
        
        if quiz:
            q_count = len(json.loads(quiz[1]))
            bot_user = await bot.get_me()
            
            # Создаем кнопки для карточки
            kb = InlineKeyboardBuilder()
            # Кнопка ПЕРЕБРАСЫВАЕТ в бота и ЗАПУСКАЕТ тест
            kb.row(types.InlineKeyboardButton(
                text="🚀 Пройти тест", 
                url=f"https://t.me/{bot_user.username}?start=run_{q_id}"
            ))
            kb.row(types.InlineKeyboardButton(
                text="📤 Поделиться", 
                switch_inline_query=f"quiz_{q_id}"
            ))

            results = [InlineQueryResultArticle(
                id=str(q_id),
                title=f"🎲 Тест: {quiz[0]}",
                description=f"📝 {q_count} вопросов · ⏱ 30 сек",
                thumb_url="https://img.icons8.com/color/96/test-passed.png",
                input_message_content=InputTextMessageContent(
                    message_text=f"🏁 <b>Тест: {quiz[0]}</b>\n\n🖋 {q_count} вопросов\n⏱ 30 сек на вопрос\n\nНажмите на кнопку ниже, чтобы начать."
                ),
                reply_markup=kb.as_markup() # ДОБАВЛЯЕМ КНОПКИ
            )]
            await query.answer(results, cache_time=1)

# --- ОСТАЛЬНЫЕ ХЕНДЛЕРЫ ---
@dp.callback_query(F.data == "admin_panel")
async def adm_menu(callback: types.CallbackQuery):
    await callback.answer()
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="➕ Добавить", callback_data="adm_add"), 
           types.InlineKeyboardButton(text="🗑 Удалить", callback_data="adm_del"))
    kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text("Админ-панель:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "to_main")
async def back(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    await cmd_start(callback.message)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
