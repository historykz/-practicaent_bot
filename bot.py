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

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8634239927:AAEBAMELMPHeG_1Y1OJ7ZyeBLLr_ITohX08"
ADMIN_IDS = [5048547918]
MANAGER_LINK = "@manager_ent"

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

class QuizStates(StatesGroup):
    waiting_for_text = State()

user_activity = {}

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("ent_final.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS quizzes 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, data TEXT, is_paid INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS results 
            (user_id INTEGER, quiz_id INTEGER, score INTEGER, total INTEGER, PRIMARY KEY(user_id, quiz_id))""")
        await db.commit()

# --- ПАРСЕР ---
def parse_quiz_text(text):
    questions = []
    blocks = [b.strip() for b in text.split('\n\n') if b.strip()]
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2: continue
        q_text, options, correct_id = lines[0], [], 0
        for i, opt in enumerate(lines[1:]):
            if '*' in opt:
                correct_id, options.append(opt.replace('*', '').strip())
            else: options.append(opt.strip())
        if options: questions.append({"q": q_text, "opts": options, "correct": correct_id})
    return questions

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject = None):
    if command and command.args and command.args.startswith("run_"):
        return await start_quiz_logic(message, int(command.args.split("_")[1]))

    # ИСПРАВЛЕНО: Обращение к пользователю, а не к боту
    user_mention = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    async with aiosqlite.connect("ent_final.db") as db:
        async with db.execute("SELECT quiz_id FROM results WHERE user_id = ?", (message.from_user.id,)) as c:
            done = [r[0] for r in await c.fetchall()]
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            all_q = await c.fetchall()

    builder = InlineKeyboardBuilder()
    for q_id, title, paid in all_q:
        mark = "✅ " if q_id in done else ("🔒 " if paid else "📖 ")
        builder.row(types.InlineKeyboardButton(text=f"{mark}{title}", callback_data=f"info_{q_id}"))
    
    if message.from_user.id in ADMIN_IDS:
        builder.row(types.InlineKeyboardButton(text="⚙️ Управление", callback_data="admin_main"))

    await message.answer(
        f"Здравствуйте, {user_mention}\nРад приветствовать! Вы усиленно готовитесь к ЕНТ. Пора практиковаться!\n\nВыберите тему:",
        reply_markup=builder.as_markup()
    )

# --- УДАЛЕНИЕ "ЧАСИКОВ" (МГНОВЕННЫЕ ОТВЕТЫ) ---
@dp.callback_query(F.data == "admin_main")
async def admin_panel(callback: types.CallbackQuery):
    await callback.answer() # Убирает загрузку
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="➕ Добавить", callback_data="adm_add"),
           types.InlineKeyboardButton(text="🗑 Удалить", callback_data="adm_del"))
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main"))
    await callback.message.edit_text("⚙️ <b>Панель администратора:</b>", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    await cmd_start(callback.message)

@dp.callback_query(F.data.startswith("info_"))
async def info_q(callback: types.CallbackQuery):
    await callback.answer()
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("ent_final.db") as db:
        async with db.execute("SELECT title, data, is_paid FROM quizzes WHERE id = ?", (q_id,)) as c:
            row = await c.fetchone()
    
    if row[2] and callback.from_user.id not in ADMIN_IDS:
        return await callback.message.answer(f"🔒 Тест платный: {MANAGER_LINK}")

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🚀 Пройти тест", callback_data=f"run_{q_id}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text(f"🏁 Тема: {row[0]}\nВопросов: {len(json.loads(row[1]))}\nТаймер: 30с", reply_markup=builder.as_markup())

# --- ЛОГИКА ТЕСТА (ОБЛЕГЧЕННАЯ) ---
async def start_quiz_logic(message: types.Message, q_id: int):
    uid = message.from_user.id
    user_activity[uid] = []
    async with aiosqlite.connect("ent_final.db") as db:
        async with db.execute("SELECT title, data FROM quizzes WHERE id = ?", (q_id,)) as c:
            row = await c.fetchone()
    
    questions = json.loads(row[1])
    await message.answer(f"🏁 <b>Старт:</b> {row[0]}")

    for i, q in enumerate(questions):
        if len(user_activity.get(uid, [])) >= 2 and all(x == "missed" for x in user_activity[uid][-2:]):
            await message.answer("⚠️ Тест остановлен (2 пропуска).")
            break

        await bot.send_poll(message.chat.id, f"[{i+1}/{len(questions)}] {q['q']}", q['opts'], type='quiz', correct_option_id=q['correct'], open_period=30, is_anonymous=False)
        await asyncio.sleep(30.5)
        if uid in user_activity and len(user_activity[uid]) <= i:
            user_activity[uid].append("missed")

    async with aiosqlite.connect("ent_final.db") as db:
        await db.execute("INSERT OR REPLACE INTO results (user_id, quiz_id) VALUES (?, ?)", (uid, q_id))
        await db.commit()
    await message.answer("🏁 Тест завершен!", reply_markup=InlineKeyboardBuilder().button(text="🔙 Меню", callback_data="to_main").as_markup())

# --- INLINE MODE (БЕЗ ТОРМОЗОВ) ---
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    if "quiz_" in query.query:
        q_id = query.query.split("_")[1]
        async with aiosqlite.connect("ent_final.db") as db:
            async with db.execute("SELECT title FROM quizzes WHERE id = ?", (q_id,)) as c:
                row = await c.fetchone()
        if row:
            res = [InlineQueryResultArticle(id=q_id, title=f"🎲 {row[0]}", input_message_content=InputTextMessageContent(message_text=f"🎲 <b>Тест: {row[0]}</b>"),
                reply_markup=InlineKeyboardBuilder().button(text="🚀 Пройти тест", url=f"https://t.me/{(await bot.get_me()).username}?start=run_{q_id}").as_markup())]
            await query.answer(res, cache_time=1)

@dp.poll_answer()
async def handle_poll(answer: PollAnswer):
    if answer.user.id in user_activity: user_activity[answer.user.id].append("hit")

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
