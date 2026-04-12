import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Конфигурация
TOKEN = "8634239927:AAEBAMELMPHeG_1Y1OJ7ZyeBLLr_ITohX08"
ADMIN_IDS = [5048547918] 
MANAGER_USER = "@manager_ent" # Юзернейм менеджера для платных тем

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временная БД в памяти
quizzes = {} # База тестов
active_sessions = {} # Сессии в группах {chat_id: {"players": set(), "quiz_id": int}}

class AdminState(StatesGroup):
    waiting_for_quiz = State()

# --- ФУНКЦИЯ ПАРСИНГА ---
def parse_quiz_text(text):
    questions = []
    blocks = text.strip().split('\n\n')
    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 2: continue
        
        q_text = lines[0]
        options = []
        correct_id = 0
        for i, opt in enumerate(lines[1:]):
            if '*' in opt:
                correct_id = i
                options.append(opt.replace('*', '').strip())
            else:
                options.append(opt.strip())
        questions.append({"q": q_text, "opts": options, "correct": correct_id})
    return questions

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    text = (f"Здравствуйте, {username}\n"
            f"Рад приветствовать, что усиленно готовитесь к ЕНТ и желаете практиковаться")
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📚 Выберите тему для практики", callback_data="subjects")
    if user_id in ADMIN_IDS:
        kb.button(text="⚙️ Создать тест (Админ)", callback_data="admin_add")
    kb.adjust(1)
    
    await message.answer(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "subjects")
async def subjects_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    # Если тестов нет
    if not quizzes:
        kb.button(text="Пока нет доступных тем", callback_data="none")
    else:
        for q_id, q_data in quizzes.items():
            status = "🔒" if q_data.get('private') else "📖"
            kb.button(text=f"{status} {q_data['title']}", callback_data=f"info_{q_id}")
    
    kb.button(text="🔙 Назад", callback_data="start_back")
    kb.adjust(1)
    await callback.message.edit_text("Выберите тему для практики:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "start_back")
async def back_to_start(callback: types.CallbackQuery):
    await start_handler(callback.message)

# --- АДМИНКА ---
@dp.callback_query(F.data == "admin_add")
async def admin_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Пришли текст теста.\nФормат:\nВопрос?\nА) Ответ*\nБ) Ответ\n\n(Между вопросами пустая строка!)")
    await state.set_state(AdminState.waiting_for_quiz)

@dp.message(AdminState.waiting_for_quiz)
async def save_quiz(message: types.Message, state: FSMContext):
    parsed = parse_quiz_text(message.text)
    if not parsed:
        await message.answer("Ошибка формата! Попробуй еще раз.")
        return
    
    q_id = len(quizzes) + 1
    quizzes[q_id] = {
        "title": f"Тест №{q_id}",
        "questions": parsed,
        "private": False
    }
    await message.answer(f"✅ Готово! Создано вопросов: {len(parsed)}\nID теста: {q_id}")
    await state.clear()

# --- ЛОГИКА QUIZ BOT ---
@dp.callback_query(F.data.startswith("info_"))
async def quiz_info(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    quiz = quizzes[q_id]
    
    if quiz['private']:
        await callback.message.answer(f"Этот тест платный. Пиши менеджеру: {MANAGER_USER}")
        return

    text = (f"📋 Тема: {quiz['title']}\n"
            f"❓ Вопросов: {len(quiz['questions'])}\n"
            f"⏱ Время: 30 сек на вопрос\n\n"
            f"Запускайте в группе, где есть бот!")
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Запустить тест в этом чате", callback_data=f"lobby_{q_id}")
    kb.button(text="🔙 Назад", callback_data="subjects")
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("lobby_"))
async def lobby_logic(callback: types.CallbackQuery):
    q_id = int(callback.data.split("_")[1])
    chat_id = callback.message.chat.id
    
    if chat_id not in active_sessions:
        active_sessions[chat_id] = {"players": set(), "quiz_id": q_id, "active": False}
    
    active_sessions[chat_id]["players"].add(callback.from_user.id)
    count = len(active_sessions[chat_id]["players"])
    
    kb = InlineKeyboardBuilder()
    kb.button(text="Я участвую! 🙋‍♂️", callback_data=f"lobby_{q_id}")
    
    lobby_msg = (f"🎮 Сбор участников на тест!\n"
                 f"Присоединилось: {count}\n"
                 f"Нужно минимум 2 человека.")
    
    if count >= 2 and not active_sessions[chat_id]["active"]:
        active_sessions[chat_id]["active"] = True
        await callback.message.edit_text("✅ Игроки найдены! Начинаем через 3 секунды...")
        await asyncio.sleep(3)
        await run_quiz(chat_id, q_id)
    else:
        await callback.message.edit_text(lobby_text=lobby_msg, reply_markup=kb.as_markup())

async def run_quiz(chat_id, q_id):
    quiz = quizzes[q_id]
    for i, q in enumerate(quiz['questions']):
        await bot.send_poll(
            chat_id=chat_id,
            question=f"Вопрос {i+1}/{len(quiz['questions'])}: {q['q']}",
            options=q['opts'],
            type='quiz',
            correct_option_id=q['correct'],
            open_period=30,
            is_anonymous=False,
            protect_content=True
        )
        await asyncio.sleep(31) # Ждем таймер + 1 сек
    
    await bot.send_message(chat_id, "🏁 Тест завершен! Проверьте свои результаты выше.")
    del active_sessions[chat_id]

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
