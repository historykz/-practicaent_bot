import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# КОНФИГУРАЦИЯ
TOKEN = "8634239927:AAEBAMELMPHeG_1Y1OJ7ZyeBLLr_ITohX08"
ADMIN_IDS = [5048547918]  # ЗАМЕНИ НА СВОЙ ID (узнай в @userinfobot)
MANAGER_LINK = "@manager_ent"

bot = Bot(token=TOKEN)
dp = Dispatcher()

class QuizStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_edit = State()

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("quiz_bot.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quizzes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                data TEXT,
                is_private INTEGER DEFAULT 0
            )
        """)
        await db.commit()

# --- ПАРСЕР ---
def parse_quiz(text):
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

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Исправленное приветствие
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    text = (f"Здравствуйте, {user_name}\n"
            f"Рад приветствовать, что усиленно готовитесь к ЕНТ и желаете практиковаться")
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📚 Выбрать тему для практики", callback_data="menu_subjects"))
    if message.from_user.id in ADMIN_IDS:
        builder.row(types.InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_main"))
    
    await message.answer(text, reply_markup=builder.as_markup())

# Меню выбора тем
@dp.callback_query(F.data == "menu_subjects")
async def show_quizzes(callback: types.CallbackQuery):
    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT id, title, is_private FROM quizzes") as cursor:
            rows = await cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for row in rows:
        prefix = "🔒" if row[2] else "📖"
        builder.row(types.InlineKeyboardButton(text=f"{prefix} {row[1]}", callback_data=f"view_{row[0]}"))
    
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_start"))
    await callback.message.edit_text("Выберите тему для практики:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "to_start")
async def back_start(callback: types.CallbackQuery):
    await callback.message.delete()
    await cmd_start(callback.message)

# Просмотр теста перед запуском
@dp.callback_query(F.data.startswith("view_"))
async def view_quiz(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT title, data, is_private FROM quizzes WHERE id = ?", (q_id,)) as cursor:
            quiz = await cursor.fetchone()
    
    if quiz[2] and callback.from_user.id not in ADMIN_IDS:
        return await callback.message.answer(f"Тест закрыт. Пишите менеджеру: {MANAGER_LINK}")

    import json
    q_count = len(json.loads(quiz[1]))
    text = f"Тема: {quiz[0]}\nВопросов: {q_count}\nТаймер: 30 сек\n\nГотовы?"
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🚀 Запустить тест", callback_data=f"run_{q_id}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="menu_subjects"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

# Запуск теста (упрощенная версия для работы и в личке, и в группе)
@dp.callback_query(F.data.startswith("run_"))
async def run_quiz(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT data FROM quizzes WHERE id = ?", (q_id,)) as cursor:
            row = await cursor.fetchone()
    
    import json
    questions = json.loads(row[0])
    
    await callback.message.answer("🏁 Тест начинается!")
    
    for i, q in enumerate(questions):
        poll = await bot.send_poll(
            chat_id=callback.message.chat.id,
            question=f"[{i+1}/{len(questions)}] {q['q']}",
            options=q['opts'],
            type='quiz',
            correct_option_id=q['correct'],
            open_period=30,
            is_anonymous=False,
            protect_content=True
        )
        await asyncio.sleep(31) # Таймер

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Завершить и выйти", callback_data="menu_subjects"))
    await callback.message.answer("Тест окончен!", reply_markup=builder.as_markup())

# --- АДМИН-ФУНКЦИИ (УДАЛЕНИЕ/ДОБАВЛЕНИЕ) ---

@dp.callback_query(F.data == "admin_main")
async def admin_panel(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Добавить тест", callback_data="adm_add"))
    builder.row(types.InlineKeyboardButton(text="🗑 Удалить тест", callback_data="adm_del_list"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="to_start"))
    await callback.message.edit_text("Панель администратора:", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "adm_add")
async def adm_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришли вопросы (Вопрос? \nОтвет1* \nОтвет2)")
    await state.set_state(QuizStates.waiting_for_text)

@dp.message(QuizStates.waiting_for_text)
async def adm_save(message: types.Message, state: FSMContext):
    import json
    parsed = parse_quiz(message.text)
    if not parsed: return await message.answer("Ошибка формата!")
    
    async with aiosqlite.connect("quiz_bot.db") as db:
        title = parsed[0]['q'][:20] + "..."
        await db.execute("INSERT INTO quizzes (title, data) VALUES (?, ?)", (title, json.dumps(parsed)))
        await db.commit()
    
    await message.answer("✅ Тест сохранен в базу!")
    await state.clear()

@dp.callback_query(F.data == "adm_del_list")
async def adm_del_list(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    async with aiosqlite.connect("quiz_bot.db") as db:
        async with db.execute("SELECT id, title FROM quizzes") as cursor:
            async for row in cursor:
                builder.row(types.InlineKeyboardButton(text=f"❌ {row[1]}", callback_data=f"del_{row[0]}"))
    builder.row(types.InlineKeyboardButton(text="🔙 Назад", callback_data="admin_main"))
    await callback.message.edit_text("Нажми на тест, чтобы УДАЛИТЬ его:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del_"))
async def adm_delete(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect("quiz_bot.db") as db:
        await db.execute("DELETE FROM quizzes WHERE id = ?", (q_id,))
        await db.commit()
    await callback.answer("Удалено!")
    await adm_del_list(callback)

async def main():
    await init_db()
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
