import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Настройки
TOKEN = "ВАШ_ТОКЕН"
ADMIN_IDS = [123456789] # ID админов через запятую
MANAGER_USERNAME = "@manager_user" # Юзер для платных тестов

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Временное хранилище (в идеале заменить на базу данных)
quizzes = {} # {quiz_id: {"title": str, "questions": list, "is_paid": bool}}
active_sessions = {} # {chat_id: {"players": set, "quiz_id": int, "status": str}}
user_scores = {} # {chat_id: {user_id: score}}

# --- ПАРСЕР ТЕКСТА ---
def parse_quiz_text(text):
    questions = []
    blocks = text.strip().split('\n\n')
    for block in blocks:
        lines = block.split('\n')
        q_text = lines[0]
        options = []
        correct_id = 0
        for i, line in enumerate(lines[1:]):
            if '*' in line:
                correct_id = i
                options.append(line.replace('*', '').strip())
            else:
                options.append(line.strip())
        questions.append({"q": q_text, "opts": options, "correct": correct_id})
    return questions

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start(message: types.Message):
    # Приветствие по ТЗ
    user_mention = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
    text = (f"Здравствуйте, {user_mention}\n"
            f"Рад приветствовать, что усиленно готовитесь к ЕНТ и желаете практиковаться")
    
    kb = InlineKeyboardBuilder()
    kb.button(text="📚 Выбрать тему для практики", callback_data="show_subjects")
    await message.answer(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "show_subjects")
async def subjects(callback: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    # Пример тем (в реальности тянутся из БД)
    kb.button(text="История Казахстана (Бесплатно)", callback_data="quiz_info_1")
    kb.button(text="Биология (PREMIUM) 🔒", callback_data="paid_quiz")
    kb.adjust(1)
    await callback.message.edit_text("Выберите тему для практики:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "paid_quiz")
async def paid_info(callback: types.CallbackQuery):
    await callback.message.answer(f"Этот тест закрытый. Пишите менеджеру для доступа: {MANAGER_USERNAME}")
    await callback.answer()

# --- ЛОГИКА QUIZ BOT (ЛОББИ) ---

@dp.callback_query(F.data.startswith("quiz_info_"))
async def quiz_prepare(callback: types.CallbackQuery):
    quiz_id = 1 # Условно
    # Карточка теста как в QuizBot
    text = (f"🏁 Тест: История Казахстана\n\n"
            f"❓ 10 вопросов\n"
            f"⏱ 30 сек на вопрос\n"
            f"🛡 Защита от пересылки включена\n\n"
            f"Для запуска в группе добавьте бота туда и нажмите кнопку ниже.")
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🚀 Запустить тест в этом чате", callback_data=f"lobby_start_{quiz_id}")
    kb.button(text="🔙 Назад", callback_data="show_subjects")
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("lobby_start_"))
async def lobby_join(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    
    if chat_id not in active_sessions:
        active_sessions[chat_id] = {"players": set(), "quiz_id": 1, "status": "waiting"}
    
    active_sessions[chat_id]["players"].add(callback.from_user.id)
    count = len(active_sessions[chat_id]["players"])
    
    kb = InlineKeyboardBuilder()
    kb.button(text="Присоединиться", callback_data=f"lobby_start_1")
    
    # Текст ожидания (Пункт 10: старт от 2 человек)
    lobby_text = (f"🎮 Ожидание участников...\n"
                  f"Присоединилось: {count}\n\n"
                  f"Нужно минимум 2 человека для старта.")
    
    if count >= 2:
        lobby_text += "\n\n✅ Достаточно игроков! Начинаем через 3 секунды..."
        await callback.message.edit_text(lobby_text)
        await asyncio.sleep(3)
        await start_quiz_engine(chat_id)
    else:
        await callback.message.edit_text(lobby_text, reply_markup=kb.as_markup())

async def start_quiz_engine(chat_id):
    # Тестовые вопросы (в реальности из БД)
    questions = [
        {"q": "Сколько лет Казахскому ханству?", "opts": ["550*", "200", "100"], "correct": 0},
        {"q": "Первая столица КазАССР?", "opts": ["Алматы", "Оренбург*", "Кызылорда"], "correct": 1}
    ]
    
    user_scores[chat_id] = {}
    
    for i, q in enumerate(questions):
        # Отправляем опрос (Пункт 11, 12, 15)
        poll = await bot.send_poll(
            chat_id=chat_id,
            question=f"Вопрос {i+1}/{len(questions)}: {q['q']}",
            options=q['opts'],
            type='quiz',
            correct_option_id=q['correct'],
            open_period=30, # Таймер 30 сек
            is_anonymous=False,
            protect_content=True
        )
        await asyncio.sleep(31) # Ждем закрытия таймера
        
    # Итоговая таблица (Пункт 14)
    await bot.send_message(chat_id, "🏁 Тест окончен! Результаты появятся здесь.")

# --- ЗАПУСК ---
async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
