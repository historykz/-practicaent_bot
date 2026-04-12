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

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8634239927:AAEBAMELMPHeG_1Y1OJ7ZyeBLLr_ITohX08"
ADMIN_IDS = [5048547918]
MANAGER_LINK = "@manager_ent"

bot = Bot(token=TOKEN, parse_mode="HTML")
dp = Dispatcher()

# Состояния для админки
class QuizStates(StatesGroup):
    waiting_for_text = State()

# Временное хранилище активности для остановки теста
user_activity = {} # {user_id: [status, status]}

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("ent_final.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS quizzes 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, data TEXT, is_paid INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS results 
            (user_id INTEGER, quiz_id INTEGER, score INTEGER, total INTEGER, PRIMARY KEY(user_id, quiz_id))""")
        await db.commit()

# --- ПАРСЕР ТЕКСТА ---
def parse_quiz_text(text):
    questions = []
    blocks = text.strip().split('\n\n')
    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2: continue
        q_text = lines[0]
        options, correct_id = [], 0
        for i, opt in enumerate(lines[1:]):
            if '*' in opt:
                correct_id = i
                options.append(opt.replace('*', '').strip())
            else:
                options.append(opt.strip())
        questions.append({"q": q_text, "opts": options, "correct": correct_id})
    return questions

# --- ГЛАВНОЕ МЕНЮ (С ГАЛОЧКАМИ) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    # Если зашли по ссылке из чата: /start run_1
    if command.args and command.args.startswith("run_"):
        q_id = int(command.args.split("_")[1])
        return await start_quiz_logic(message, q_id)

    name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    async with aiosqlite.connect("ent_final.db") as db:
        async with db.execute("SELECT quiz_id FROM results WHERE user_id = ?", (message.from_user.id,)) as c:
            done = [r[0] for r in await c.fetchall()]
        async with db.execute("SELECT id, title, is_paid FROM quizzes") as c:
            all_quizzes = await c.fetchall()

    builder = InlineKeyboardBuilder()
    for q_id, title, is_paid in all_quizzes:
        mark = "✅ " if q_id in done else ("🔒 " if is_paid else "📖 ")
        builder.row(types.InlineKeyboardButton(text=f"{mark}{title}", callback_data=f"info_{q_id}"))
    
    if message.from_user.id in ADMIN_IDS:
        builder.row(types.InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_main"))

    await message.answer(
        f"Здравствуйте, {name}\nРад приветствовать! Вы усиленно готовитесь к ЕНТ. Пора практиковаться!\n\nВыберите тему:",
        reply_markup=builder.as_markup()
    )

# --- ИНФОРМАЦИЯ О ТЕСТЕ ---
@dp.callback_query(F.data.startswith("info_"))
async def info_quiz(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("ent_final.db") as db:
        async with db.execute("SELECT title, data, is_paid FROM quizzes WHERE id = ?", (q_id,)) as c:
            row = await c.fetchone()
    
    if row[2] and callback.from_user.id not in ADMIN_IDS:
        return await callback.message.answer(f"🔒 Тест платный. Менеджер: {MANAGER_LINK}")

    q_count = len(json.loads(row[1]))
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🚀 Пройти тест", callback_data=f"run_{q_id}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    
    await callback.message.edit_text(
        f"<b>Тема:</b> {row[0]}\n<b>Вопросов:</b> {q_count}\n<b>Таймер:</b> 30 сек\n\nНачать?",
        reply_markup=builder.as_markup()
    )

# --- ЛОГИКА ТЕСТА (ОСТАНОВКА НА 2 ПРОПУСКАХ) ---
async def start_quiz_logic(message: types.Message, q_id: int):
    uid = message.from_user.id
    user_activity[uid] = [] 
    
    async with aiosqlite.connect("ent_final.db") as db:
        async with db.execute("SELECT title, data FROM quizzes WHERE id = ?", (q_id,)) as c:
            row = await c.fetchone()
    
    questions = json.loads(row[1])
    score = 0
    await message.answer(f"🏁 <b>Старт теста:</b> {row[0]}")

    for i, q in enumerate(questions):
        # Проверка на 2 пропуска подряд
        if len(user_activity[uid]) >= 2 and all(x == "missed" for x in user_activity[uid][-2:]):
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(text="Продолжить", callback_data=f"run_{q_id}"))
            builder.row(types.InlineKeyboardButton(text="Завершить", callback_data="to_main"))
            await message.answer("⚠️ Вы пропустили 2 вопроса. Продолжаем?", reply_markup=builder.as_markup())
            return

        poll = await bot.send_poll(
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
        if len(user_activity[uid]) <= i:
            user_activity[uid].append("missed")
    
    # ФИНАЛ (ФОТО 3)
    async with aiosqlite.connect("ent_final.db") as db:
        await db.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?)", (uid, q_id, 0, len(questions)))
        await db.commit()

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🔄 Попробовать снова", callback_data=f"run_{q_id}"))
    builder.row(types.InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=f"quiz_{q_id}"))
    builder.row(types.InlineKeyboardButton(text="🔙 К выбору тем", callback_data="to_main"))
    
    await message.answer(f"🏁 Тест «{row[0]}» завершен!\nРезультат сохранен ✅", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("run_"))
async def run_callback(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    await start_quiz_logic(callback.message, q_id)

@dp.poll_answer()
async def poll_ans(answer: PollAnswer):
    if answer.user.id in user_activity:
        user_activity[answer.user.id].append("hit")

# --- INLINE MODE (СЕРАЯ ПАНЕЛЬ ФОТО 2 И КАРТОЧКА ФОТО 3) ---
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    if "quiz_" in query.query:
        q_id = query.query.split("_")[1]
        async with aiosqlite.connect("ent_final.db") as db:
            async with db.execute("SELECT title, data FROM quizzes WHERE id = ?", (q_id,)) as c:
                row = await c.fetchone()
        
        if row:
            q_count = len(json.loads(row[1]))
            # ТА САМАЯ ПАНЕЛЬ ИЗ ПРИМЕРА
            res = [InlineQueryResultArticle(
                id=str(q_id),
                title=f"🎲 Тест: {row[0]}",
                description=f"📝 {q_count} вопросов · ⏱ 30 сек",
                thumb_url="https://img.icons8.com/color/96/test-passed.png",
                input_message_content=InputTextMessageContent(
                    message_text=f"🎲 <b>Тест «{row[0]}»</b>\n\n🖋 {q_count} вопросов\n⏱ 30 сек на вопрос"
                ),
                reply_markup=InlineKeyboardBuilder()
                    .row(types.InlineKeyboardButton(text="🚀 Пройти тест", url=f"https://t.me/{(await bot.get_me()).username}?start=run_{q_id}"))
                    .row(types.InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=f"quiz_{q_id}"))
                    .as_markup()
            )]
            await query.answer(res, cache_time=1)

# --- АДМИН-ПАНЕЛЬ ---
@dp.callback_query(F.data == "admin_main")
async def admin_panel(callback: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="➕ Добавить тест", callback_data="adm_add"))
    kb.row(types.InlineKeyboardButton(text="🗑 Удалить тест", callback_data="adm_del_list"))
    kb.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_main"))
    await callback.message.edit_text("⚙️ Управление тестами:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "adm_add")
async def adm_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришли вопросы (Вопрос? \nОтвет1* \nОтвет2)")
    await state.set_state(QuizStates.waiting_for_text)

@dp.message(QuizStates.waiting_for_text)
async def adm_save(message: types.Message, state: FSMContext):
    data = parse_quiz_text(message.text)
    if not data: return await message.answer("❌ Ошибка формата!")
    async with aiosqlite.connect("ent_final.db") as db:
        await db.execute("INSERT INTO quizzes (title, data) VALUES (?, ?)", (data[0]['q'][:25], json.dumps(data)))
        await db.commit()
    await message.answer("✅ Тест успешно добавлен!")
    await state.clear()

@dp.callback_query(F.data == "to_main")
async def back_main(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_start(callback.message, CommandObject(command="start", args=None))

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
