“””
Образовательный Telegram-бот для подготовки через тесты.
Технологии: Python 3.11+, aiogram 3, aiosqlite, Telegram Stars, Inline Mode.
“””

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
CallbackQuery,
ChatMemberUpdated,
ChosenInlineResult,
InlineKeyboardButton,
InlineKeyboardMarkup,
InlineQuery,
InlineQueryResultArticle,
InputTextMessageContent,
KeyboardButton,
LabeledPrice,
Message,
Poll,
PollAnswer,
PreCheckoutQuery,
ReplyKeyboardMarkup,
ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ───────────────────────────────── CONFIG ─────────────────────────────────

BOT_TOKEN = os.getenv(“BOT_TOKEN”)
if not BOT_TOKEN:
raise RuntimeError(“BOT_TOKEN не задан. Установите переменную окружения BOT_TOKEN.”)

BOT_USERNAME = “practicaent_bot”
SUPER_ADMIN_IDS = [5048547918]
MANAGER_LINK = “@historyentk_bot”
DB_PATH = “bot.db”

logging.basicConfig(level=logging.INFO, format=”%(asctime)s [%(levelname)s] %(message)s”)
log = logging.getLogger(**name**)

# ───────────────────────────────── I18N ───────────────────────────────────

TEXTS = {
“ru”: {
“choose_lang”: “Выберите язык / Тілді таңдаңыз”,
“welcome”: (
“👋 Добро пожаловать в образовательный бот!\n\n”
“Здесь вы можете подготовиться к экзаменам через тесты по разным предметам.”
),
“main_menu”: “📋 Главное меню”,
“btn_sections”: “📚 Разделы”,
“btn_results”: “📊 Мои результаты”,
“btn_invite”: “👥 Пригласить друзей”,
“btn_help”: “ℹ️ Помощь”,
“btn_cooperate”: “🤝 Сотрудничать”,
“btn_manager”: “👨‍💼 Менеджер”,
“btn_admin”: “⚙️ Админ-панель”,
“btn_back”: “◀️ Назад”,
“sections_title”: “📚 Выберите раздел:”,
“no_sections”: “Разделы пока не созданы.”,
“subscribe_required”: (
“🔒 Для доступа к бесплатным тестам этого раздела\n”
“подпишитесь на канал:”
),
“btn_subscribe”: “📢 Подписаться”,
“btn_check_sub”: “✅ Я подписался”,
“not_subscribed”: “❌ Вы ещё не подписались. Пожалуйста, подпишитесь и попробуйте снова.”,
“subscribed_ok”: “✅ Подписка подтверждена!”,
“premium_promo”: (
“✅ Спасибо за подписку! Бесплатные тесты уже доступны.\n\n”
“💎 <b>Премиум</b> откроет:\n”
“• Все платные тесты\n”
“• Разбор ошибок\n”
“• Приватные тесты\n”
“• Расширенную статистику”
),
“btn_premium_info”: “💎 О Премиуме”,
“btn_to_tests”: “📚 К тестам”,
“quiz_list_title”: “📋 Тесты раздела <b>{section}</b>:”,
“no_quizzes”: “В этом разделе пока нет тестов.”,
“access_premium”: “💎 Этот тест доступен только по Премиуму.”,
“access_private”: “🔒 У вас нет доступа к этому тесту.”,
“access_stars”: “⭐ Этот тест стоит {price} Stars.”,
“btn_buy_stars”: “⭐ Купить за {price} Stars”,
“already_purchased”: “✅ Тест уже куплен.”,
“test_start”: “🚀 Запускаю тест: <b>{title}</b>\nВопросов: {count}\n\nПриготовьтесь!”,
“question_num”: “Вопрос {current}/{total}”,
“btn_pause”: “⏸ Приостановить”,
“btn_finish”: “⛔ Завершить тест”,
“btn_appeal”: “⚖️ Апелляция”,
“btn_resume”: “▶️ Продолжить”,
“paused”: “⏸ Тест приостановлен.\n\nНажмите ▶️ Продолжить, чтобы возобновить.”,
“two_missed”: (
“⚠️ Два вопроса подряд пропущены.\nТест приостановлен.\n\n”
“Что делаем?”
),
“finished_early”: “⛔ Тест завершён досрочно.”,
“result_title”: “📊 <b>Результат теста</b>”,
“result_body”: (
“📝 Тест: <b>{title}</b>\n”
“✅ Правильных: {correct}/{total}\n”
“❌ Неправильных: {wrong}\n”
“⏭ Пропущенных: {missed}\n”
“📈 Процент: <b>{percent:.1f}%</b>{early}”
),
“result_early_note”: “\n\n⚠️ Тест завершён досрочно.”,
“my_results_empty”: “У вас пока нет результатов.”,
“my_results_title”: “📊 <b>Мои результаты</b>”,
“invite_text”: (
“👥 <b>Пригласите друзей!</b>\n\n”
“Ваша реферальная ссылка:\n”
“<code>{link}</code>\n\n”
“Приглашено: {count} чел.”
),
“help_text”: (
“ℹ️ <b>Помощь</b>\n\n”
“• Выберите раздел → тест → проходите по одному вопросу.\n”
“• Бесплатные тесты доступны после подписки на канал раздела.\n”
“• Платные тесты можно купить за Stars или оформить Премиум.\n”
“• Бесплатные тесты можно отправить в группу через кнопку «Пройти в группе».\n”
“• По вопросам сотрудничества: “ + MANAGER_LINK
),
“cooperate_text”: f”🤝 По вопросам сотрудничества пишите: {MANAGER_LINK}”,
“no_active_session”: “У вас нет активного теста.”,
“appeal_prompt”: (
“⚖️ <b>Апелляция</b>\n\n”
“Опишите проблему с вопросом #{num}.\n”
“Тест приостановлен. Напишите текст апелляции:”
),
“appeal_sent”: “✅ Апелляция отправлена на рассмотрение.”,
“appeal_cancelled”: “❌ Апелляция отменена. Тест возобновлён.”,
“btn_cancel_appeal”: “❌ Отменить апелляцию”,
“private_tests_only_pm”: “🔒 Платные тесты доступны только внутри бота (в личке).”,
“group_card_title”: “📝 <b>{title}</b>”,
“group_card_body”: “Вопросов: {count} | Время: 30 сек/вопрос\n\nНажмите кнопку, чтобы участвовать:”,
“btn_join_group_test”: “▶️ Пройти тест”,
“group_waiting”: “👥 Участников готово: {count}/2. Ожидаем ещё…”,
“group_countdown”: “🚀 Запуск через {n}…”,
“group_start”: “🎯 Тест начался! Отвечайте на вопросы.”,
“group_two_missed”: “⚠️ Два вопроса пропущены. Тест приостановлен.”,
“group_finished”: “🏁 Тест завершён!”,
“only_initiator_can_finish”: “❌ Завершить тест может только организатор или администратор группы.”,
“admin_panel”: “⚙️ <b>Админ-панель</b>”,
“admin_section_panel”: “⚙️ <b>Управление разделами</b>”,
“btn_add_section”: “➕ Добавить раздел”,
“btn_edit_section”: “✏️ Разделы”,
“btn_add_quiz”: “➕ Добавить тест”,
“btn_quiz_list”: “📋 Тесты”,
“btn_admins”: “👥 Админы разделов”,
“btn_stats”: “📊 Статистика”,
“btn_appeals”: “⚖️ Апелляции”,
“btn_channels”: “📢 Каналы подписки”,
“section_name_prompt_ru”: “Введите название раздела на русском:”,
“section_name_prompt_kk”: “Введите название раздела на казахском:”,
“section_saved”: “✅ Раздел сохранён.”,
“section_deleted”: “🗑 Раздел удалён.”,
“quiz_title_prompt”: “Введите название теста:”,
“quiz_type_prompt”: “Выберите тип доступа:”,
“quiz_stars_price_prompt”: “Введите цену в Stars (целое число):”,
“quiz_add_questions”: (
“➕ Отправляйте вопросы по одному.\n\n”
“<b>Формат текстом:</b>\n”
“Текст вопроса\n”
“A) вариант\nB) вариант\nC) вариант\nD) вариант\n”
“Ответ: A\n\n”
“Или пересылайте quiz poll из другого чата.”
),
“quiz_buffer”: “📦 В буфере: {count} вопрос(ов).”,
“btn_save_quiz”: “💾 Сохранить тест”,
“btn_add_more”: “➕ Добавить ещё”,
“btn_clear_all”: “🗑 Очистить всё”,
“btn_cancel”: “❌ Отмена”,
“quiz_saved”: “✅ Тест сохранён! Вопросов: {count}.”,
“quiz_cleared”: “🗑 Буфер очищен.”,
“quiz_cancelled”: “❌ Создание теста отменено.”,
“parse_error”: “⚠️ Ошибка в блоке #{num}. Вопрос не добавлен.\n{detail}”,
“btn_remove_fragment”: “🗑 Убрать фрагмент”,
“btn_fix_fragment”: “✏️ Исправить заново”,
“btn_continue_adding”: “➕ Продолжить”,
“admin_added”: “✅ Админ добавлен.”,
“admin_removed”: “✅ Админ удалён.”,
“prompt_user_id”: “Введите Telegram user_id:”,
“prompt_section_choice”: “Выберите раздел:”,
“private_access_granted”: “✅ Доступ выдан пользователю {uid}.”,
“private_access_revoked”: “✅ Доступ отозван.”,
“appeal_admin_msg”: (
“⚖️ <b>Новая апелляция</b>\n\n”
“Тест: {quiz}\nВопрос #{qnum}\n”
“Пользователь: {user}\n\n”
“Текст: {text}”
),
“btn_delete_question”: “🗑 Удалить вопрос”,
“btn_change_answer”: “✏️ Изменить ответ”,
“btn_reject_appeal”: “❌ Отклонить”,
“appeal_resolved”: “✅ Апелляция обработана.”,
“stats_title”: “📊 <b>Статистика пользователей</b>”,
“no_stats”: “Нет данных.”,
“private_test_results_title”: “📊 Результаты по тесту <b>{title}</b>”,
“attempt”: “Попытка {n}”,
“no_attempts”: “Ещё не проходил.”,
“btn_reset_attempts”: “🔓 Разрешить повторно”,
“btn_delete_results”: “🗑 Удалить результаты”,
“confirm_delete”: “⚠️ Подтвердите удаление результатов пользователя {uid}?”,
“btn_confirm”: “✅ Да, удалить”,
“results_deleted”: “🗑 Результаты удалены.”,
“attempts_reset”: “🔓 Попытки сброшены.”,
“attempts_exhausted”: “⛔ Вы исчерпали все попытки для этого теста.\nОбратитесь к администратору.”,
“channel_prompt”: “Введите @username канала (или ‘нет’ для отключения):”,
“channel_saved”: “✅ Канал сохранён.”,
“not_admin”: “❌ У вас нет прав для этого действия.”,
“purchase_title”: “Покупка теста”,
“purchase_desc”: “Доступ к тесту: {title}”,
“purchase_success”: “✅ Тест куплен! Теперь он доступен.”,
“free_label”: “🆓”,
“premium_label”: “💎”,
“stars_label”: “⭐”,
“private_label”: “🔒”,
“section_admin_panel”: “⚙️ Панель администратора раздела”,
},
“kk”: {
“choose_lang”: “Выберите язык / Тілді таңдаңыз”,
“welcome”: (
“👋 Білім беру ботына қош келдіңіз!\n\n”
“Мұнда сіз әртүрлі пәндер бойынша тесттер арқылы емтиханға дайындала аласыз.”
),
“main_menu”: “📋 Басты мәзір”,
“btn_sections”: “📚 Бөлімдер”,
“btn_results”: “📊 Менің нәтижелерім”,
“btn_invite”: “👥 Достарды шақыру”,
“btn_help”: “ℹ️ Көмек”,
“btn_cooperate”: “🤝 Ынтымақтасу”,
“btn_manager”: “👨‍💼 Менеджер”,
“btn_admin”: “⚙️ Әкімші панелі”,
“btn_back”: “◀️ Артқа”,
“sections_title”: “📚 Бөлімді таңдаңыз:”,
“no_sections”: “Бөлімдер әлі жасалмаған.”,
“subscribe_required”: (
“🔒 Осы бөлімнің тегін тесттеріне қол жеткізу үшін\n”
“каналға жазылыңыз:”
),
“btn_subscribe”: “📢 Жазылу”,
“btn_check_sub”: “✅ Жазылдым”,
“not_subscribed”: “❌ Сіз әлі жазылмадыңыз. Жазылып, қайтадан көріңіз.”,
“subscribed_ok”: “✅ Жазылым расталды!”,
“premium_promo”: (
“✅ Жазылғаныңыз үшін рахмет! Тегін тесттер қолжетімді.\n\n”
“💎 <b>Премиум</b> ашады:\n”
“• Барлық ақылы тесттер\n”
“• Қателерді талдау\n”
“• Жеке тесттер\n”
“• Кеңейтілген статистика”
),
“btn_premium_info”: “💎 Премиум туралы”,
“btn_to_tests”: “📚 Тесттерге”,
“quiz_list_title”: “📋 <b>{section}</b> бөліміндегі тесттер:”,
“no_quizzes”: “Бұл бөлімде тесттер жоқ.”,
“access_premium”: “💎 Бұл тест тек Премиум арқылы қолжетімді.”,
“access_private”: “🔒 Сізде бұл тестке рұқсат жоқ.”,
“access_stars”: “⭐ Бұл тест {price} Stars тұрады.”,
“btn_buy_stars”: “⭐ {price} Stars-қа сатып алу”,
“already_purchased”: “✅ Тест бұрын сатып алынған.”,
“test_start”: “🚀 Тест басталуда: <b>{title}</b>\nСұрақтар: {count}\n\nДайын болыңыз!”,
“question_num”: “Сұрақ {current}/{total}”,
“btn_pause”: “⏸ Тоқтату”,
“btn_finish”: “⛔ Тестті аяқтау”,
“btn_appeal”: “⚖️ Апелляция”,
“btn_resume”: “▶️ Жалғастыру”,
“paused”: “⏸ Тест тоқтатылды.\n\n▶️ Жалғастыру батырмасын басыңыз.”,
“two_missed”: “⚠️ Қатарынан екі сұрақ өткізілді.\nТест тоқтатылды.\n\nНе істейміз?”,
“finished_early”: “⛔ Тест мерзімінен бұрын аяқталды.”,
“result_title”: “📊 <b>Тест нәтижесі</b>”,
“result_body”: (
“📝 Тест: <b>{title}</b>\n”
“✅ Дұрыс: {correct}/{total}\n”
“❌ Қате: {wrong}\n”
“⏭ Өткізілген: {missed}\n”
“📈 Пайыз: <b>{percent:.1f}%</b>{early}”
),
“result_early_note”: “\n\n⚠️ Тест мерзімінен бұрын аяқталды.”,
“my_results_empty”: “Нәтижелер жоқ.”,
“my_results_title”: “📊 <b>Менің нәтижелерім</b>”,
“invite_text”: (
“👥 <b>Достарыңызды шақырыңыз!</b>\n\n”
“Сіздің реферал сілтемеңіз:\n”
“<code>{link}</code>\n\n”
“Шақырылған: {count} адам.”
),
“help_text”: (
“ℹ️ <b>Көмек</b>\n\n”
“• Бөлімді → тестті таңдаңыз → сұрақтарға жауап беріңіз.\n”
“• Тегін тесттер каналға жазылғаннан кейін қолжетімді.\n”
“• Ақылы тесттерді Stars-қа сатып алуға немесе Премиум алуға болады.\n”
“• Тегін тесттерді топқа жіберуге болады.\n”
“• Ынтымақтасу: “ + MANAGER_LINK
),
“cooperate_text”: f”🤝 Ынтымақтасу мәселелері бойынша: {MANAGER_LINK}”,
“no_active_session”: “Белсенді тестіңіз жоқ.”,
“appeal_prompt”: (
“⚖️ <b>Апелляция</b>\n\n”
“#{num} сұрақтағы мәселені сипаттаңыз.\n”
“Тест тоқтатылды. Апелляция мәтінін жазыңыз:”
),
“appeal_sent”: “✅ Апелляция жіберілді.”,
“appeal_cancelled”: “❌ Апелляция болдырылмады. Тест жалғасты.”,
“btn_cancel_appeal”: “❌ Апелляциядан бас тарту”,
“private_tests_only_pm”: “🔒 Ақылы тесттер тек жеке хабарлама арқылы қолжетімді.”,
“group_card_title”: “📝 <b>{title}</b>”,
“group_card_body”: “Сұрақтар: {count} | Уақыт: 30 сек/сұрақ\n\nҚатысу үшін басыңыз:”,
“btn_join_group_test”: “▶️ Тестке кіру”,
“group_waiting”: “👥 Дайын қатысушылар: {count}/2. Күтуде…”,
“group_countdown”: “🚀 {n} секундтан кейін басталады…”,
“group_start”: “🎯 Тест басталды! Сұрақтарға жауап беріңіз.”,
“group_two_missed”: “⚠️ Екі сұрақ өткізілді. Тест тоқтатылды.”,
“group_finished”: “🏁 Тест аяқталды!”,
“only_initiator_can_finish”: “❌ Тестті тек ұйымдастырушы немесе топ әкімшісі аяқтай алады.”,
“admin_panel”: “⚙️ <b>Әкімші панелі</b>”,
“admin_section_panel”: “⚙️ <b>Бөлімдерді басқару</b>”,
“btn_add_section”: “➕ Бөлім қосу”,
“btn_edit_section”: “✏️ Бөлімдер”,
“btn_add_quiz”: “➕ Тест қосу”,
“btn_quiz_list”: “📋 Тесттер”,
“btn_admins”: “👥 Бөлім әкімшілері”,
“btn_stats”: “📊 Статистика”,
“btn_appeals”: “⚖️ Апелляциялар”,
“btn_channels”: “📢 Жазылым арналары”,
“section_name_prompt_ru”: “Бөлімнің орысша атауын енгізіңіз:”,
“section_name_prompt_kk”: “Бөлімнің қазақша атауын енгізіңіз:”,
“section_saved”: “✅ Бөлім сақталды.”,
“section_deleted”: “🗑 Бөлім жойылды.”,
“quiz_title_prompt”: “Тест атауын енгізіңіз:”,
“quiz_type_prompt”: “Қол жеткізу түрін таңдаңыз:”,
“quiz_stars_price_prompt”: “Stars бағасын енгізіңіз (бүтін сан):”,
“quiz_add_questions”: (
“➕ Сұрақтарды бірінен соң бірін жіберіңіз.\n\n”
“<b>Мәтін форматы:</b>\n”
“Сұрақ мәтіні\n”
“A) нұсқа\nB) нұсқа\nC) нұсқа\nD) нұсқа\n”
“Жауап: A\n\n”
“Немесе басқа чаттан quiz poll-ды қайта жіберіңіз.”
),
“quiz_buffer”: “📦 Буферде: {count} сұрақ.”,
“btn_save_quiz”: “💾 Тестті сақтау”,
“btn_add_more”: “➕ Тағы қосу”,
“btn_clear_all”: “🗑 Барлығын тазалау”,
“btn_cancel”: “❌ Болдырмау”,
“quiz_saved”: “✅ Тест сақталды! Сұрақтар: {count}.”,
“quiz_cleared”: “🗑 Буфер тазаланды.”,
“quiz_cancelled”: “❌ Тест жасау болдырылмады.”,
“parse_error”: “⚠️ #{num} блогында қате. Сұрақ қосылмады.\n{detail}”,
“btn_remove_fragment”: “🗑 Фрагментті жою”,
“btn_fix_fragment”: “✏️ Қайтадан түзету”,
“btn_continue_adding”: “➕ Жалғастыру”,
“admin_added”: “✅ Әкімші қосылды.”,
“admin_removed”: “✅ Әкімші жойылды.”,
“prompt_user_id”: “Telegram user_id енгізіңіз:”,
“prompt_section_choice”: “Бөлімді таңдаңыз:”,
“private_access_granted”: “✅ {uid} пайдаланушыға рұқсат берілді.”,
“private_access_revoked”: “✅ Рұқсат алынып тасталды.”,
“appeal_admin_msg”: (
“⚖️ <b>Жаңа апелляция</b>\n\n”
“Тест: {quiz}\nСұрақ #{qnum}\n”
“Пайдаланушы: {user}\n\n”
“Мәтін: {text}”
),
“btn_delete_question”: “🗑 Сұрақты жою”,
“btn_change_answer”: “✏️ Жауапты өзгерту”,
“btn_reject_appeal”: “❌ Қабылдамау”,
“appeal_resolved”: “✅ Апелляция өңделді.”,
“stats_title”: “📊 <b>Пайдаланушылар статистикасы</b>”,
“no_stats”: “Деректер жоқ.”,
“private_test_results_title”: “📊 <b>{title}</b> тесті бойынша нәтижелер”,
“attempt”: “Әрекет {n}”,
“no_attempts”: “Әлі өтпеген.”,
“btn_reset_attempts”: “🔓 Қайтадан рұқсат беру”,
“btn_delete_results”: “🗑 Нәтижелерді жою”,
“confirm_delete”: “⚠️ {uid} пайдаланушының нәтижелерін жоюды растайсыз ба?”,
“btn_confirm”: “✅ Иә, жою”,
“results_deleted”: “🗑 Нәтижелер жойылды.”,
“attempts_reset”: “🔓 Әрекеттер нөлге қайтарылды.”,
“attempts_exhausted”: “⛔ Бұл тест үшін барлық әрекеттеріңізді пайдаландыңыз.\nӘкімшіге хабарласыңыз.”,
“channel_prompt”: “Арна @username-ін енгізіңіз (немесе ‘жоқ’ деп өшіру үшін):”,
“channel_saved”: “✅ Арна сақталды.”,
“not_admin”: “❌ Бұл әрекет үшін рұқсатыңыз жоқ.”,
“purchase_title”: “Тест сатып алу”,
“purchase_desc”: “Тестке қол жеткізу: {title}”,
“purchase_success”: “✅ Тест сатып алынды! Қолжетімді.”,
“free_label”: “🆓”,
“premium_label”: “💎”,
“stars_label”: “⭐”,
“private_label”: “🔒”,
“section_admin_panel”: “⚙️ Бөлім әкімшісінің панелі”,
},
}

def t(lang: str, key: str, **kwargs) -> str:
“”“Получить перевод по ключу.”””
text = TEXTS.get(lang, TEXTS[“ru”]).get(key, TEXTS[“ru”].get(key, key))
if kwargs:
try:
return text.format(**kwargs)
except Exception:
return text
return text

# ───────────────────────────────── FSM STATES ─────────────────────────────

class LangState(StatesGroup):
choosing = State()

class QuizState(StatesGroup):
running = State()
paused = State()
appeal = State()

class AdminState(StatesGroup):
# Section
add_section_ru = State()
add_section_kk = State()
# Quiz creation
quiz_title = State()
quiz_type = State()
quiz_stars_price = State()
quiz_adding_questions = State()
quiz_fix_fragment = State()
# Admin management
add_section_admin_uid = State()
add_section_admin_section = State()
remove_section_admin_uid = State()
# Channel
set_channel = State()
# Private access
private_access_uid = State()
private_access_quiz = State()
# Appeal handling
appeal_change_answer = State()
# Reset attempts
reset_attempts_uid = State()

# ───────────────────────────────── DATABASE ───────────────────────────────

async def init_db(db: aiosqlite.Connection):
await db.executescript(”””
PRAGMA journal_mode=WAL;

```
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    language     TEXT DEFAULT 'ru',
    created_at   TEXT DEFAULT (datetime('now')),
    invited_by   INTEGER,
    is_premium   INTEGER DEFAULT 0,
    premium_until TEXT,
    last_active_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sections (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    title_ru                  TEXT NOT NULL,
    title_kk                  TEXT NOT NULL,
    is_active                 INTEGER DEFAULT 1,
    required_channel_username TEXT,
    require_subscription      INTEGER DEFAULT 0,
    created_at                TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS section_admins (
    user_id    INTEGER,
    section_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, section_id)
);

CREATE TABLE IF NOT EXISTS quizzes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id  INTEGER NOT NULL,
    title       TEXT NOT NULL,
    data        TEXT NOT NULL DEFAULT '[]',
    access_type TEXT DEFAULT 'free',
    stars_price INTEGER DEFAULT 0,
    created_by  INTEGER,
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS purchased_tests (
    user_id      INTEGER,
    quiz_id      INTEGER,
    purchased_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, quiz_id)
);

CREATE TABLE IF NOT EXISTS private_access (
    user_id     INTEGER,
    quiz_id     INTEGER,
    granted_by  INTEGER,
    granted_at  TEXT DEFAULT (datetime('now')),
    max_attempts INTEGER DEFAULT 2,
    PRIMARY KEY (user_id, quiz_id)
);

CREATE TABLE IF NOT EXISTS results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER,
    quiz_id      INTEGER,
    section_id   INTEGER,
    attempt_num  INTEGER DEFAULT 1,
    score        INTEGER DEFAULT 0,
    total        INTEGER DEFAULT 0,
    wrong        INTEGER DEFAULT 0,
    missed       INTEGER DEFAULT 0,
    unfinished   INTEGER DEFAULT 0,
    percent      REAL DEFAULT 0,
    mode         TEXT DEFAULT 'private',
    early        INTEGER DEFAULT 0,
    completed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS appeals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER,
    quiz_id        INTEGER,
    question_index INTEGER,
    message        TEXT,
    status         TEXT DEFAULT 'pending',
    created_at     TEXT DEFAULT (datetime('now')),
    handled_by     INTEGER,
    handled_at     TEXT
);

CREATE TABLE IF NOT EXISTS referrals (
    inviter_id      INTEGER,
    invited_user_id INTEGER PRIMARY KEY,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS group_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      INTEGER,
    quiz_id      INTEGER,
    created_by   INTEGER,
    status       TEXT DEFAULT 'waiting',
    participants TEXT DEFAULT '[]',
    current_q    INTEGER DEFAULT 0,
    missed_streak INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS active_sessions (
    user_id      INTEGER PRIMARY KEY,
    quiz_id      INTEGER,
    current_q    INTEGER DEFAULT 0,
    answers      TEXT DEFAULT '[]',
    missed_streak INTEGER DEFAULT 0,
    poll_msg_id  INTEGER,
    ctrl_msg_id  INTEGER,
    timer_task   INTEGER DEFAULT 0
);
""")
await db.commit()
```

async def get_db() -> aiosqlite.Connection:
db = await aiosqlite.connect(DB_PATH)
db.row_factory = aiosqlite.Row
return db

# ───────────────────────────── DB HELPERS ────────────────────────────────

async def upsert_user(db, user_id, username, first_name, lang=“ru”, invited_by=None):
await db.execute(
“”“INSERT INTO users (user_id, username, first_name, language, invited_by)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(user_id) DO UPDATE SET
username=excluded.username,
first_name=excluded.first_name,
last_active_at=datetime(‘now’)”””,
(user_id, username, first_name, lang, invited_by),
)
await db.commit()

async def get_user(db, user_id) -> Optional[aiosqlite.Row]:
async with db.execute(“SELECT * FROM users WHERE user_id=?”, (user_id,)) as cur:
return await cur.fetchone()

async def set_user_lang(db, user_id, lang):
await db.execute(“UPDATE users SET language=? WHERE user_id=?”, (lang, user_id))
await db.commit()

async def get_user_lang(db, user_id) -> str:
async with db.execute(“SELECT language FROM users WHERE user_id=?”, (user_id,)) as cur:
row = await cur.fetchone()
return row[“language”] if row else “ru”

async def is_super_admin(user_id: int) -> bool:
return user_id in SUPER_ADMIN_IDS

async def get_section_admin_sections(db, user_id) -> list:
async with db.execute(
“SELECT section_id FROM section_admins WHERE user_id=?”, (user_id,)
) as cur:
rows = await cur.fetchall()
return [r[“section_id”] for r in rows]

async def is_admin_of_section(db, user_id, section_id) -> bool:
if await is_super_admin(user_id):
return True
async with db.execute(
“SELECT 1 FROM section_admins WHERE user_id=? AND section_id=?”,
(user_id, section_id),
) as cur:
return await cur.fetchone() is not None

async def get_sections(db) -> list:
async with db.execute(“SELECT * FROM sections WHERE is_active=1 ORDER BY id”) as cur:
return await cur.fetchall()

async def get_section(db, section_id) -> Optional[aiosqlite.Row]:
async with db.execute(“SELECT * FROM sections WHERE id=?”, (section_id,)) as cur:
return await cur.fetchone()

async def get_quizzes_for_section(db, section_id) -> list:
async with db.execute(
“SELECT * FROM quizzes WHERE section_id=? AND is_active=1 ORDER BY id”,
(section_id,),
) as cur:
return await cur.fetchall()

async def get_quiz(db, quiz_id) -> Optional[aiosqlite.Row]:
async with db.execute(“SELECT * FROM quizzes WHERE id=?”, (quiz_id,)) as cur:
return await cur.fetchone()

async def has_premium(db, user_id) -> bool:
async with db.execute(
“SELECT is_premium, premium_until FROM users WHERE user_id=?”, (user_id,)
) as cur:
row = await cur.fetchone()
if not row:
return False
if not row[“is_premium”]:
return False
if row[“premium_until”]:
until = datetime.fromisoformat(row[“premium_until”])
if until < datetime.now():
return False
return True

async def has_purchased(db, user_id, quiz_id) -> bool:
async with db.execute(
“SELECT 1 FROM purchased_tests WHERE user_id=? AND quiz_id=?”, (user_id, quiz_id)
) as cur:
return await cur.fetchone() is not None

async def has_private_access(db, user_id, quiz_id) -> bool:
async with db.execute(
“SELECT 1 FROM private_access WHERE user_id=? AND quiz_id=?”, (user_id, quiz_id)
) as cur:
return await cur.fetchone() is not None

async def get_attempt_count(db, user_id, quiz_id) -> int:
async with db.execute(
“SELECT COUNT(*) as cnt FROM results WHERE user_id=? AND quiz_id=?”,
(user_id, quiz_id),
) as cur:
row = await cur.fetchone()
return row[“cnt”] if row else 0

async def get_max_attempts(db, user_id, quiz_id) -> int:
async with db.execute(
“SELECT max_attempts FROM private_access WHERE user_id=? AND quiz_id=?”,
(user_id, quiz_id),
) as cur:
row = await cur.fetchone()
return row[“max_attempts”] if row else 2

async def save_result(db, user_id, quiz_id, section_id, score, total, wrong, missed,
unfinished, percent, mode, early, attempt_num):
await db.execute(
“”“INSERT INTO results
(user_id, quiz_id, section_id, attempt_num, score, total, wrong, missed,
unfinished, percent, mode, early)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)”””,
(user_id, quiz_id, section_id, attempt_num, score, total, wrong, missed,
unfinished, percent, mode, early),
)
await db.commit()

async def get_active_session(db, user_id) -> Optional[aiosqlite.Row]:
async with db.execute(“SELECT * FROM active_sessions WHERE user_id=?”, (user_id,)) as cur:
return await cur.fetchone()

async def set_active_session(db, user_id, quiz_id, current_q=0, answers=None,
missed_streak=0, poll_msg_id=0, ctrl_msg_id=0):
answers_json = json.dumps(answers or [])
await db.execute(
“”“INSERT INTO active_sessions
(user_id, quiz_id, current_q, answers, missed_streak, poll_msg_id, ctrl_msg_id)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(user_id) DO UPDATE SET
quiz_id=excluded.quiz_id,
current_q=excluded.current_q,
answers=excluded.answers,
missed_streak=excluded.missed_streak,
poll_msg_id=excluded.poll_msg_id,
ctrl_msg_id=excluded.ctrl_msg_id”””,
(user_id, quiz_id, current_q, answers_json, missed_streak, poll_msg_id, ctrl_msg_id),
)
await db.commit()

async def update_session_field(db, user_id, **kwargs):
if not kwargs:
return
fields = “, “.join(f”{k}=?” for k in kwargs)
values = list(kwargs.values()) + [user_id]
await db.execute(f”UPDATE active_sessions SET {fields} WHERE user_id=?”, values)
await db.commit()

async def clear_session(db, user_id):
await db.execute(“DELETE FROM active_sessions WHERE user_id=?”, (user_id,))
await db.commit()

async def get_referral_count(db, user_id) -> int:
async with db.execute(
“SELECT COUNT(*) as cnt FROM referrals WHERE inviter_id=?”, (user_id,)
) as cur:
row = await cur.fetchone()
return row[“cnt”] if row else 0

# ─────────────────────────── KEYBOARDS ────────────────────────────────────

def lang_keyboard() -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=“🇷🇺 Русский”, callback_data=“lang:ru”)
kb.button(text=“🇰🇿 Қазақша”, callback_data=“lang:kk”)
kb.adjust(2)
return kb.as_markup()

def main_menu_keyboard(lang: str, is_admin: bool = False) -> ReplyKeyboardMarkup:
buttons = [
[KeyboardButton(text=t(lang, “btn_sections”)), KeyboardButton(text=t(lang, “btn_results”))],
[KeyboardButton(text=t(lang, “btn_invite”)), KeyboardButton(text=t(lang, “btn_help”))],
[KeyboardButton(text=t(lang, “btn_cooperate”)), KeyboardButton(text=t(lang, “btn_manager”))],
]
if is_admin:
buttons.append([KeyboardButton(text=t(lang, “btn_admin”))])
return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def sections_keyboard(lang: str, sections: list) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
title_field = “title_kk” if lang == “kk” else “title_ru”
for s in sections:
kb.button(text=s[title_field], callback_data=f”section:{s[‘id’]}”)
kb.button(text=t(lang, “btn_back”), callback_data=“back:main”)
kb.adjust(1)
return kb.as_markup()

def quiz_access_label(lang: str, access_type: str, stars_price: int) -> str:
if access_type == “free”:
return t(lang, “free_label”)
if access_type == “premium”:
return t(lang, “premium_label”)
if access_type == “stars”:
return f”{t(lang, ‘stars_label’)} {stars_price}”
if access_type == “private”:
return t(lang, “private_label”)
return “”

def quizzes_keyboard(lang: str, quizzes: list, section_id: int) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
for q in quizzes:
label = quiz_access_label(lang, q[“access_type”], q[“stars_price”])
kb.button(text=f”{label} {q[‘title’]}”, callback_data=f”quiz:{q[‘id’]}”)
kb.button(text=t(lang, “btn_back”), callback_data=f”section_back:{section_id}”)
kb.adjust(1)
return kb.as_markup()

def subscribe_keyboard(lang: str, channel: str, section_id: int) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_subscribe”), url=f”https://t.me/{channel.lstrip(’@’)}”)
kb.button(text=t(lang, “btn_check_sub”), callback_data=f”check_sub:{section_id}”)
kb.adjust(1)
return kb.as_markup()

def premium_promo_keyboard(lang: str, section_id: int) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_premium_info”), callback_data=“premium_info”)
kb.button(text=t(lang, “btn_to_tests”), callback_data=f”section:{section_id}”)
kb.button(text=t(lang, “btn_manager”), url=f”https://t.me/{MANAGER_LINK.lstrip(’@’)}”)
kb.adjust(2)
return kb.as_markup()

def quiz_control_keyboard(lang: str) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_pause”), callback_data=“quiz_ctrl:pause”)
kb.button(text=t(lang, “btn_finish”), callback_data=“quiz_ctrl:finish”)
kb.button(text=t(lang, “btn_appeal”), callback_data=“quiz_ctrl:appeal”)
kb.adjust(3)
return kb.as_markup()

def paused_keyboard(lang: str) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_resume”), callback_data=“quiz_ctrl:resume”)
kb.button(text=t(lang, “btn_finish”), callback_data=“quiz_ctrl:finish”)
kb.adjust(2)
return kb.as_markup()

def appeal_keyboard(lang: str) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_cancel_appeal”), callback_data=“appeal:cancel”)
kb.adjust(1)
return kb.as_markup()

def admin_main_keyboard(lang: str) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_add_section”), callback_data=“adm:add_section”)
kb.button(text=t(lang, “btn_edit_section”), callback_data=“adm:sections_list”)
kb.button(text=t(lang, “btn_add_quiz”), callback_data=“adm:add_quiz_choose_section”)
kb.button(text=t(lang, “btn_quiz_list”), callback_data=“adm:quizzes_list”)
kb.button(text=t(lang, “btn_admins”), callback_data=“adm:admins_menu”)
kb.button(text=t(lang, “btn_stats”), callback_data=“adm:stats”)
kb.button(text=t(lang, “btn_appeals”), callback_data=“adm:appeals”)
kb.button(text=t(lang, “btn_channels”), callback_data=“adm:channels”)
kb.adjust(2)
return kb.as_markup()

def section_admin_keyboard(lang: str, section_id: int) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_add_quiz”), callback_data=f”adm:add_quiz:{section_id}”)
kb.button(text=t(lang, “btn_quiz_list”), callback_data=f”adm:quizzes:{section_id}”)
kb.button(text=t(lang, “btn_appeals”), callback_data=f”adm:appeals:{section_id}”)
kb.button(text=t(lang, “btn_stats”), callback_data=f”adm:results:{section_id}”)
kb.adjust(2)
return kb.as_markup()

def group_test_start_keyboard(lang: str, quiz_id: int, session_id: int) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_join_group_test”), callback_data=f”gtest_join:{session_id}”)
kb.adjust(1)
return kb.as_markup()

# ─────────────────────────── QUIZ PARSING ─────────────────────────────────

ANSWER_LETTERS = [“A”, “B”, “C”, “D”, “E”]

def parse_text_question(text: str) -> dict:
“””
Парсить вопрос из текста.
Формат:
Текст вопроса
A) вариант
B) вариант
Ответ: A
“””
lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
if len(lines) < 3:
raise ValueError(“Слишком мало строк”)

```
answer_line = None
for i, line in enumerate(lines):
    if re.match(r"^(Ответ|Жауап)\s*:\s*[A-Ea-e]", line, re.IGNORECASE):
        answer_line = lines.pop(i)
        break

if not answer_line:
    raise ValueError("Не найдена строка 'Ответ: X' или 'Жауап: X'")

correct_letter = re.search(r"[A-Ea-e]", answer_line).group(0).upper()

options = []
question_lines = []
for line in lines:
    m = re.match(r"^([A-Ea-e])\s*[.)]\s*(.+)$", line, re.IGNORECASE)
    if m:
        options.append(m.group(2).strip())
    else:
        question_lines.append(line)

if not question_lines:
    raise ValueError("Не найден текст вопроса")
if len(options) < 2:
    raise ValueError("Нужно минимум 2 варианта ответа")

correct_index = ANSWER_LETTERS.index(correct_letter) if correct_letter in ANSWER_LETTERS else 0
if correct_index >= len(options):
    raise ValueError(f"Правильный ответ {correct_letter} выходит за пределы вариантов")

return {
    "question": " ".join(question_lines),
    "options": options,
    "correct": correct_index,
}
```

def parse_poll_question(poll: Poll) -> Optional[dict]:
“”“Парсить вопрос из Telegram Poll.”””
if poll.type != “quiz”:
return None
options = [o.text for o in poll.options]
return {
“question”: poll.question,
“options”: options,
“correct”: poll.correct_option_id or 0,
}

# ──────────────────────────── QUIZ RUNNER ─────────────────────────────────

# Хранилище задач таймеров: user_id -> asyncio.Task

_timer_tasks: dict[int, asyncio.Task] = {}

# Хранилище pending poll_id -> (user_id, question_index)

_poll_map: dict[str, tuple[int, int]] = {}

async def send_question(bot: Bot, db, user_id: int, quiz_id: int, q_index: int,
questions: list, lang: str):
“”“Отправить вопрос пользователю как quiz poll.”””
if q_index >= len(questions):
await finish_quiz(bot, db, user_id, early=False)
return

```
q = questions[q_index]
total = len(questions)

# Удалить предыдущее контрольное сообщение
session = await get_active_session(db, user_id)
if session and session["ctrl_msg_id"]:
    try:
        await bot.delete_message(user_id, session["ctrl_msg_id"])
    except Exception:
        pass

try:
    poll_msg = await bot.send_poll(
        chat_id=user_id,
        question=f"[{q_index + 1}/{total}] {q['question']}",
        options=q["options"],
        type="quiz",
        correct_option_id=q["correct"],
        is_anonymous=False,
        open_period=30,
        protect_content=True,
    )
except Exception as e:
    log.error(f"send_question error: {e}")
    return

_poll_map[poll_msg.poll.id] = (user_id, q_index)

ctrl_msg = await bot.send_message(
    user_id,
    t(lang, "question_num", current=q_index + 1, total=total),
    reply_markup=quiz_control_keyboard(lang),
)

await update_session_field(
    db, user_id,
    current_q=q_index,
    poll_msg_id=poll_msg.message_id,
    ctrl_msg_id=ctrl_msg.message_id,
)

# Запустить таймер на 30 сек
_cancel_timer(user_id)
task = asyncio.create_task(_question_timer(bot, db, user_id, quiz_id, q_index, questions, lang))
_timer_tasks[user_id] = task
```

async def _question_timer(bot: Bot, db, user_id: int, quiz_id: int, q_index: int,
questions: list, lang: str):
“”“Таймер вопроса — через 30 сек считается пропущенным.”””
try:
await asyncio.sleep(30)
except asyncio.CancelledError:
return

```
session = await get_active_session(db, user_id)
if not session or session["current_q"] != q_index:
    return

# Вопрос не был отвечен — пропускаем
answers = json.loads(session["answers"])
while len(answers) <= q_index:
    answers.append(None)
if answers[q_index] is None:
    answers[q_index] = "missed"

missed_streak = session["missed_streak"] + 1
await update_session_field(db, user_id, answers=json.dumps(answers), missed_streak=missed_streak)

if missed_streak >= 2:
    # Автопауза
    await update_session_field(db, user_id, missed_streak=0)
    try:
        await bot.send_message(
            user_id,
            t(lang, "two_missed"),
            reply_markup=paused_keyboard(lang),
        )
    except Exception:
        pass
    return

# Следующий вопрос
await send_question(bot, db, user_id, quiz_id, q_index + 1, questions, lang)
```

def _cancel_timer(user_id: int):
if user_id in _timer_tasks:
_timer_tasks[user_id].cancel()
del _timer_tasks[user_id]

async def finish_quiz(bot: Bot, db, user_id: int, early: bool = False):
“”“Завершить тест, сохранить результат, очистить сессию.”””
_cancel_timer(user_id)

```
session = await get_active_session(db, user_id)
if not session:
    return

quiz_id = session["quiz_id"]
quiz = await get_quiz(db, quiz_id)
if not quiz:
    await clear_session(db, user_id)
    return

questions = json.loads(quiz["data"])
answers = json.loads(session["answers"])
total = len(questions)
lang = await get_user_lang(db, user_id)

correct = 0
wrong = 0
missed = 0

for i, q in enumerate(questions):
    ans = answers[i] if i < len(answers) else None
    if ans is None or ans == "missed":
        missed += 1
    elif ans == q["correct"]:
        correct += 1
    else:
        wrong += 1

unanswered = total - len(answers)
missed += unanswered

percent = (correct / total * 100) if total > 0 else 0

# Считаем номер попытки
attempt_num = await get_attempt_count(db, user_id, quiz_id) + 1

await save_result(
    db, user_id, quiz_id, quiz["section_id"],
    score=correct, total=total, wrong=wrong, missed=missed,
    unfinished=unanswered, percent=percent,
    mode="private", early=int(early), attempt_num=attempt_num,
)

early_note = t(lang, "result_early_note") if early else ""
text = (
    t(lang, "result_title") + "\n\n" +
    t(lang, "result_body",
      title=quiz["title"],
      correct=correct,
      total=total,
      wrong=wrong,
      missed=missed,
      percent=percent,
      early=early_note)
)

# Удалить контрольное сообщение
if session["ctrl_msg_id"]:
    try:
        await bot.delete_message(user_id, session["ctrl_msg_id"])
    except Exception:
        pass

await clear_session(db, user_id)

try:
    await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
except Exception as e:
    log.error(f"finish_quiz send error: {e}")
```

# ─────────────────────────── ROUTERS ──────────────────────────────────────

router = Router()

# ─── /start ───────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot):
user = message.from_user
db = await get_db()
try:
existing = await get_user(db, user.id)

```
    # Реферал
    args = message.text.split() if message.text else []
    invited_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            invited_by = int(args[1][4:])
            if invited_by == user.id:
                invited_by = None
        except ValueError:
            pass

    if not existing:
        await upsert_user(db, user.id, user.username, user.first_name, invited_by=invited_by)
        if invited_by:
            # Сохранить реферал
            try:
                await db.execute(
                    "INSERT OR IGNORE INTO referrals (inviter_id, invited_user_id) VALUES (?,?)",
                    (invited_by, user.id),
                )
                await db.commit()
            except Exception:
                pass
        # Новый пользователь — выбор языка
        await message.answer(
            t("ru", "choose_lang"),
            reply_markup=lang_keyboard(),
        )
        await state.set_state(LangState.choosing)
    else:
        await upsert_user(db, user.id, user.username, user.first_name)
        lang = existing["language"]
        is_adm = await is_super_admin(user.id) or bool(await get_section_admin_sections(db, user.id))
        await message.answer(
            t(lang, "welcome"),
            reply_markup=main_menu_keyboard(lang, is_adm),
        )
finally:
    await db.close()
```

@router.callback_query(F.data.startswith(“lang:”), LangState.choosing)
async def choose_lang(callback: CallbackQuery, state: FSMContext, bot: Bot):
lang = callback.data.split(”:”)[1]
db = await get_db()
try:
await set_user_lang(db, callback.from_user.id, lang)
is_adm = await is_super_admin(callback.from_user.id) or bool(
await get_section_admin_sections(db, callback.from_user.id)
)
await callback.message.edit_text(t(lang, “welcome”))
await callback.message.answer(
t(lang, “main_menu”),
reply_markup=main_menu_keyboard(lang, is_adm),
)
await state.clear()
finally:
await db.close()
await callback.answer()

# ─── MAIN MENU HANDLERS ───────────────────────────────────────────────────

@router.message(F.text.in_({TEXTS[“ru”][“btn_sections”], TEXTS[“kk”][“btn_sections”]}))
async def menu_sections(message: Message):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
sections = await get_sections(db)
if not sections:
await message.answer(t(lang, “no_sections”))
return
await message.answer(
t(lang, “sections_title”),
reply_markup=sections_keyboard(lang, sections),
)
finally:
await db.close()

@router.message(F.text.in_({TEXTS[“ru”][“btn_results”], TEXTS[“kk”][“btn_results”]}))
async def menu_results(message: Message):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
async with db.execute(
“”“SELECT r.*, q.title as quiz_title FROM results r
JOIN quizzes q ON r.quiz_id=q.id
WHERE r.user_id=? ORDER BY r.completed_at DESC LIMIT 20”””,
(message.from_user.id,),
) as cur:
rows = await cur.fetchall()

```
    if not rows:
        await message.answer(t(lang, "my_results_empty"))
        return

    text = t(lang, "my_results_title") + "\n\n"
    for r in rows:
        early = " ⚠️" if r["early"] else ""
        text += (
            f"📝 <b>{r['quiz_title']}</b>\n"
            f"✅ {r['score']}/{r['total']} — {r['percent']:.1f}%{early}\n"
            f"🗓 {r['completed_at'][:16]}\n\n"
        )
    await message.answer(text, parse_mode=ParseMode.HTML)
finally:
    await db.close()
```

@router.message(F.text.in_({TEXTS[“ru”][“btn_invite”], TEXTS[“kk”][“btn_invite”]}))
async def menu_invite(message: Message):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
ref_count = await get_referral_count(db, message.from_user.id)
link = f”https://t.me/{BOT_USERNAME}?start=ref_{message.from_user.id}”
await message.answer(
t(lang, “invite_text”, link=link, count=ref_count),
parse_mode=ParseMode.HTML,
)
finally:
await db.close()

@router.message(F.text.in_({TEXTS[“ru”][“btn_help”], TEXTS[“kk”][“btn_help”]}))
async def menu_help(message: Message):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
await message.answer(t(lang, “help_text”), parse_mode=ParseMode.HTML)
finally:
await db.close()

@router.message(F.text.in_({TEXTS[“ru”][“btn_cooperate”], TEXTS[“kk”][“btn_cooperate”]}))
async def menu_cooperate(message: Message):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
await message.answer(t(lang, “cooperate_text”))
finally:
await db.close()

@router.message(F.text.in_({TEXTS[“ru”][“btn_manager”], TEXTS[“kk”][“btn_manager”]}))
async def menu_manager(message: Message):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_manager”), url=f”https://t.me/{MANAGER_LINK.lstrip(’@’)}”)
await message.answer(“👨‍💼”, reply_markup=kb.as_markup())
finally:
await db.close()

# ─── SECTIONS ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“section:”))
async def show_section(callback: CallbackQuery):
section_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
section = await get_section(db, section_id)
if not section:
await callback.answer(“Not found”, show_alert=True)
return

```
    # Проверить подписку
    if section["require_subscription"] and section["required_channel_username"]:
        channel = section["required_channel_username"]
        try:
            member = await callback.bot.get_chat_member(channel, callback.from_user.id)
            subscribed = member.status in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            )
        except Exception:
            subscribed = False

        if not subscribed:
            await callback.message.edit_text(
                t(lang, "subscribe_required") + f"\n{channel}",
                reply_markup=subscribe_keyboard(lang, channel, section_id),
            )
            await callback.answer()
            return

    # Показать тесты
    quizzes = await get_quizzes_for_section(db, section_id)
    title_field = "title_kk" if lang == "kk" else "title_ru"

    # Фильтровать приватные тесты
    visible_quizzes = []
    for q in quizzes:
        if q["access_type"] == "private":
            if await has_private_access(db, callback.from_user.id, q["id"]):
                visible_quizzes.append(q)
        else:
            visible_quizzes.append(q)

    if not visible_quizzes:
        await callback.message.edit_text(
            t(lang, "no_quizzes"),
            reply_markup=InlineKeyboardBuilder().button(
                text=t(lang, "btn_back"), callback_data="back:sections"
            ).as_markup(),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        t(lang, "quiz_list_title", section=section[title_field]),
        reply_markup=quizzes_keyboard(lang, visible_quizzes, section_id),
        parse_mode=ParseMode.HTML,
    )
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“check_sub:”))
async def check_subscription(callback: CallbackQuery):
section_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
section = await get_section(db, section_id)
if not section:
await callback.answer(“Not found”, show_alert=True)
return

```
    channel = section["required_channel_username"]
    try:
        member = await callback.bot.get_chat_member(channel, callback.from_user.id)
        subscribed = member.status in (
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        )
    except Exception:
        subscribed = False

    if not subscribed:
        await callback.answer(t(lang, "not_subscribed"), show_alert=True)
        return

    await callback.answer(t(lang, "subscribed_ok"), show_alert=False)
    await callback.message.edit_text(
        t(lang, "premium_promo"),
        reply_markup=premium_promo_keyboard(lang, section_id),
        parse_mode=ParseMode.HTML,
    )
finally:
    await db.close()
```

@router.callback_query(F.data.startswith(“section_back:”))
async def section_back(callback: CallbackQuery):
section_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
sections = await get_sections(db)
await callback.message.edit_text(
t(lang, “sections_title”),
reply_markup=sections_keyboard(lang, sections),
)
finally:
await db.close()
await callback.answer()

@router.callback_query(F.data == “back:sections”)
async def back_to_sections(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
sections = await get_sections(db)
await callback.message.edit_text(
t(lang, “sections_title”),
reply_markup=sections_keyboard(lang, sections),
)
finally:
await db.close()
await callback.answer()

@router.callback_query(F.data == “back:main”)
async def back_to_main(callback: CallbackQuery):
await callback.message.delete()
await callback.answer()

@router.callback_query(F.data == “premium_info”)
async def premium_info(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_manager”), url=f”https://t.me/{MANAGER_LINK.lstrip(’@’)}”)
await callback.message.answer(t(lang, “premium_promo”), parse_mode=ParseMode.HTML,
reply_markup=kb.as_markup())
finally:
await db.close()
await callback.answer()

# ─── QUIZ ACCESS ──────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“quiz:”))
async def handle_quiz_start(callback: CallbackQuery, state: FSMContext):
quiz_id = int(callback.data.split(”:”)[1])
user_id = callback.from_user.id

```
db = await get_db()
try:
    lang = await get_user_lang(db, user_id)
    quiz = await get_quiz(db, quiz_id)
    if not quiz:
        await callback.answer("Not found", show_alert=True)
        return

    access_type = quiz["access_type"]

    # Проверка доступа
    if access_type == "premium":
        if not await has_premium(db, user_id):
            await callback.answer(t(lang, "access_premium"), show_alert=True)
            return
    elif access_type == "stars":
        if not await has_purchased(db, user_id, quiz_id):
            stars_price = quiz["stars_price"]
            kb = InlineKeyboardBuilder()
            kb.button(
                text=t(lang, "btn_buy_stars", price=stars_price),
                callback_data=f"buy_stars:{quiz_id}",
            )
            await callback.message.answer(
                t(lang, "access_stars", price=stars_price),
                reply_markup=kb.as_markup(),
            )
            await callback.answer()
            return
    elif access_type == "private":
        if not await has_private_access(db, user_id, quiz_id):
            await callback.answer(t(lang, "access_private"), show_alert=True)
            return
        # Проверить количество попыток
        used = await get_attempt_count(db, user_id, quiz_id)
        max_att = await get_max_attempts(db, user_id, quiz_id)
        if used >= max_att:
            await callback.answer(t(lang, "attempts_exhausted"), show_alert=True)
            return

    # Проверить нет ли активной сессии
    session = await get_active_session(db, user_id)
    if session:
        await finish_quiz(callback.bot, db, user_id, early=True)

    questions = json.loads(quiz["data"])
    if not questions:
        await callback.answer("Тест пустой", show_alert=True)
        return

    await set_active_session(db, user_id, quiz_id)

    await callback.message.answer(
        t(lang, "test_start", title=quiz["title"], count=len(questions)),
        parse_mode=ParseMode.HTML,
    )

    await state.set_state(QuizState.running)
    await send_question(callback.bot, db, user_id, quiz_id, 0, questions, lang)

    # Кнопка группового теста (только free)
    if access_type == "free":
        kb = InlineKeyboardBuilder()
        kb.button(
            text="👥 Пройти в группе" if lang == "ru" else "👥 Топта өту",
            switch_inline_query=f"quiz_{quiz_id}",
        )
        await callback.message.answer(
            "💡 Можно пройти этот тест в группе:" if lang == "ru"
            else "💡 Бұл тестті топта өтуге болады:",
            reply_markup=kb.as_markup(),
        )
finally:
    await db.close()
await callback.answer()
```

# ─── STARS PAYMENT ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“buy_stars:”))
async def buy_stars(callback: CallbackQuery):
quiz_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
quiz = await get_quiz(db, quiz_id)
if not quiz:
await callback.answer(“Not found”, show_alert=True)
return
if await has_purchased(db, callback.from_user.id, quiz_id):
await callback.answer(t(lang, “already_purchased”), show_alert=True)
return

```
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title=t(lang, "purchase_title"),
        description=t(lang, "purchase_desc", title=quiz["title"]),
        payload=f"quiz_{quiz_id}",
        currency="XTR",
        prices=[LabeledPrice(label=quiz["title"], amount=quiz["stars_price"])],
    )
finally:
    await db.close()
await callback.answer()
```

@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
await query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
payload = message.successful_payment.invoice_payload
if payload.startswith(“quiz_”):
quiz_id = int(payload[5:])
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
await db.execute(
“INSERT OR IGNORE INTO purchased_tests (user_id, quiz_id) VALUES (?,?)”,
(message.from_user.id, quiz_id),
)
await db.commit()
await message.answer(t(lang, “purchase_success”))
finally:
await db.close()

# ─── QUIZ CONTROLS ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“quiz_ctrl:”))
async def quiz_control(callback: CallbackQuery, state: FSMContext):
action = callback.data.split(”:”)[1]
user_id = callback.from_user.id

```
db = await get_db()
try:
    lang = await get_user_lang(db, user_id)
    session = await get_active_session(db, user_id)
    if not session:
        await callback.answer(t(lang, "no_active_session"), show_alert=True)
        return

    if action == "pause":
        _cancel_timer(user_id)
        await update_session_field(db, user_id, missed_streak=0)
        await state.set_state(QuizState.paused)
        await callback.message.edit_reply_markup(reply_markup=paused_keyboard(lang))
        await callback.answer(t(lang, "paused"))

    elif action == "resume":
        quiz = await get_quiz(db, session["quiz_id"])
        questions = json.loads(quiz["data"])
        current_q = session["current_q"]
        await state.set_state(QuizState.running)
        # Удалить сообщение паузы
        try:
            await callback.message.edit_reply_markup(reply_markup=quiz_control_keyboard(lang))
        except Exception:
            pass
        await send_question(callback.bot, db, user_id, session["quiz_id"],
                            current_q, questions, lang)
        await callback.answer()

    elif action == "finish":
        await state.clear()
        await callback.answer()
        await finish_quiz(callback.bot, db, user_id, early=True)

    elif action == "appeal":
        _cancel_timer(user_id)
        await state.set_state(QuizState.appeal)
        q_num = session["current_q"] + 1
        await callback.message.answer(
            t(lang, "appeal_prompt", num=q_num),
            reply_markup=appeal_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )
        await callback.answer()
finally:
    await db.close()
```

@router.callback_query(F.data == “appeal:cancel”, QuizState.appeal)
async def appeal_cancel(callback: CallbackQuery, state: FSMContext):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
session = await get_active_session(db, callback.from_user.id)
await state.set_state(QuizState.running)
await callback.message.edit_text(t(lang, “appeal_cancelled”))
if session:
quiz = await get_quiz(db, session[“quiz_id”])
questions = json.loads(quiz[“data”])
await send_question(callback.bot, db, callback.from_user.id,
session[“quiz_id”], session[“current_q”], questions, lang)
finally:
await db.close()
await callback.answer()

@router.message(QuizState.appeal, F.text)
async def appeal_text(message: Message, state: FSMContext, bot: Bot):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
session = await get_active_session(db, message.from_user.id)
if not session:
await state.clear()
return

```
    quiz_id = session["quiz_id"]
    q_index = session["current_q"]
    quiz = await get_quiz(db, quiz_id)

    # Сохранить апелляцию
    await db.execute(
        """INSERT INTO appeals (user_id, quiz_id, question_index, message)
           VALUES (?, ?, ?, ?)""",
        (message.from_user.id, quiz_id, q_index, message.text),
    )
    await db.commit()

    # Получить ID апелляции
    async with db.execute("SELECT last_insert_rowid() as lid") as cur:
        row = await cur.fetchone()
        appeal_id = row["lid"]

    # Отправить уведомление админам раздела
    admin_text = t(
        "ru", "appeal_admin_msg",
        quiz=quiz["title"] if quiz else quiz_id,
        qnum=q_index + 1,
        user=f"{message.from_user.full_name} ({message.from_user.id})",
        text=message.text,
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=t("ru", "btn_delete_question"), callback_data=f"appeal_adm:del_q:{appeal_id}")
    kb.button(text=t("ru", "btn_change_answer"), callback_data=f"appeal_adm:change_ans:{appeal_id}")
    kb.button(text=t("ru", "btn_reject_appeal"), callback_data=f"appeal_adm:reject:{appeal_id}")
    kb.adjust(1)

    # Суперадмины
    for adm_id in SUPER_ADMIN_IDS:
        try:
            await bot.send_message(adm_id, admin_text, parse_mode=ParseMode.HTML,
                                   reply_markup=kb.as_markup())
        except Exception:
            pass

    # Секционные админы
    if quiz:
        async with db.execute(
            "SELECT user_id FROM section_admins WHERE section_id=?", (quiz["section_id"],)
        ) as cur:
            adm_rows = await cur.fetchall()
        for row in adm_rows:
            if row["user_id"] not in SUPER_ADMIN_IDS:
                try:
                    await bot.send_message(row["user_id"], admin_text,
                                           parse_mode=ParseMode.HTML, reply_markup=kb.as_markup())
                except Exception:
                    pass

    await message.answer(t(lang, "appeal_sent"))

    # Возобновить тест
    await state.set_state(QuizState.running)
    if quiz:
        questions = json.loads(quiz["data"])
        await send_question(bot, db, message.from_user.id, quiz_id,
                            q_index, questions, lang)
finally:
    await db.close()
```

# ─── POLL ANSWER ──────────────────────────────────────────────────────────

@router.poll_answer()
async def handle_poll_answer(poll_answer: PollAnswer, bot: Bot):
poll_id = poll_answer.poll_id
if poll_id not in _poll_map:
return

```
user_id, q_index = _poll_map[poll_id]
db = await get_db()
try:
    session = await get_active_session(db, user_id)
    if not session or session["current_q"] != q_index:
        return

    # Отменить таймер — пользователь ответил
    _cancel_timer(user_id)

    answers = json.loads(session["answers"])
    while len(answers) <= q_index:
        answers.append(None)
    answers[q_index] = poll_answer.option_ids[0] if poll_answer.option_ids else "missed"

    await update_session_field(db, user_id, answers=json.dumps(answers), missed_streak=0)

    lang = await get_user_lang(db, user_id)
    quiz = await get_quiz(db, session["quiz_id"])
    if not quiz:
        return
    questions = json.loads(quiz["data"])

    # Следующий вопрос
    await send_question(bot, db, user_id, session["quiz_id"], q_index + 1, questions, lang)
finally:
    await db.close()
```

# ─── INLINE MODE (группы) ─────────────────────────────────────────────────

@router.inline_query()
async def inline_query_handler(inline_query: InlineQuery):
query = inline_query.query.strip()
db = await get_db()
try:
lang = await get_user_lang(db, inline_query.from_user.id)

```
    results = []
    if query.startswith("quiz_"):
        try:
            quiz_id = int(query[5:])
            quiz = await get_quiz(db, quiz_id)
            if quiz and quiz["access_type"] == "free":
                questions = json.loads(quiz["data"])
                title_field = "title_kk" if lang == "kk" else "title_ru"
                section = await get_section(db, quiz["section_id"])
                section_title = section[title_field] if section else ""

                text = (
                    f"📝 <b>{quiz['title']}</b>\n"
                    f"📚 {section_title}\n"
                    f"❓ Вопросов: {len(questions)}\n"
                    f"⏱ 30 сек/вопрос\n\n"
                    f"Нажмите кнопку, чтобы участвовать!"
                )
                kb = InlineKeyboardBuilder()
                kb.button(
                    text=t(lang, "btn_join_group_test"),
                    url=f"https://t.me/{BOT_USERNAME}?start=gtest_{quiz_id}",
                )
                results.append(
                    InlineQueryResultArticle(
                        id=str(quiz_id),
                        title=quiz["title"],
                        description=f"Тест: {len(questions)} вопросов",
                        input_message_content=InputTextMessageContent(
                            message_text=text,
                            parse_mode=ParseMode.HTML,
                        ),
                        reply_markup=kb.as_markup(),
                    )
                )
            elif quiz and quiz["access_type"] != "free":
                # Платный тест — нельзя делиться
                results.append(
                    InlineQueryResultArticle(
                        id="blocked",
                        title="🔒 Платный тест",
                        description="Платные тесты доступны только внутри бота",
                        input_message_content=InputTextMessageContent(
                            message_text=t(lang, "private_tests_only_pm"),
                        ),
                    )
                )
        except (ValueError, TypeError):
            pass
    else:
        # Показать бесплатные тесты
        async with db.execute(
            "SELECT * FROM quizzes WHERE access_type='free' AND is_active=1 LIMIT 10"
        ) as cur:
            quizzes = await cur.fetchall()
        for q in quizzes:
            questions = json.loads(q["data"])
            results.append(
                InlineQueryResultArticle(
                    id=str(q["id"]),
                    title=q["title"],
                    description=f"{len(questions)} вопросов",
                    input_message_content=InputTextMessageContent(
                        message_text=f"📝 <b>{q['title']}</b>\n❓ {len(questions)} вопросов",
                        parse_mode=ParseMode.HTML,
                    ),
                )
            )
finally:
    await db.close()

await inline_query.answer(results, cache_time=30)
```

# ─── GROUP TEST via /start gtest_ID ───────────────────────────────────────

@router.message(Command(“start”))
async def start_gtest(message: Message, bot: Bot):
if not message.text:
return
args = message.text.split()
if len(args) < 2 or not args[1].startswith(“gtest_”):
return

```
try:
    quiz_id = int(args[1][6:])
except ValueError:
    return

# Только в личке — публикуем инструкцию
db = await get_db()
try:
    lang = await get_user_lang(db, message.from_user.id)
    quiz = await get_quiz(db, quiz_id)
    if not quiz or quiz["access_type"] != "free":
        await message.answer(t(lang, "private_tests_only_pm"))
        return

    questions = json.loads(quiz["data"])
    # Создать сессию группового теста (в личке как init)
    await db.execute(
        """INSERT INTO group_sessions (chat_id, quiz_id, created_by, participants)
           VALUES (?, ?, ?, ?)""",
        (message.chat.id, quiz_id, message.from_user.id, json.dumps([message.from_user.id])),
    )
    await db.commit()
    async with db.execute("SELECT last_insert_rowid() as lid") as cur:
        session_id = (await cur.fetchone())["lid"]

    text = (
        f"📝 <b>{quiz['title']}</b>\n"
        f"❓ Вопросов: {len(questions)} | ⏱ 30 сек/вопрос\n\n"
        f"Нажмите кнопку, чтобы участвовать:"
    )
    await message.answer(
        text,
        reply_markup=group_test_start_keyboard(lang, quiz_id, session_id),
        parse_mode=ParseMode.HTML,
    )
finally:
    await db.close()
```

@router.callback_query(F.data.startswith(“gtest_join:”))
async def gtest_join(callback: CallbackQuery, bot: Bot):
session_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
async with db.execute(
“SELECT * FROM group_sessions WHERE id=?”, (session_id,)
) as cur:
gsession = await cur.fetchone()

```
    if not gsession or gsession["status"] != "waiting":
        await callback.answer("Сессия недоступна", show_alert=True)
        return

    participants = json.loads(gsession["participants"])
    uid = callback.from_user.id
    if uid not in participants:
        participants.append(uid)
        await db.execute(
            "UPDATE group_sessions SET participants=? WHERE id=?",
            (json.dumps(participants), session_id),
        )
        await db.commit()

    count = len(participants)
    if count < 2:
        await callback.answer(t(lang, "group_waiting", count=count), show_alert=False)
        # Обновить кнопку
        try:
            await callback.message.edit_text(
                callback.message.text + f"\n\n👥 {count}/2",
                reply_markup=group_test_start_keyboard(lang, gsession["quiz_id"], session_id),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # Запустить тест
    await db.execute(
        "UPDATE group_sessions SET status='running' WHERE id=?", (session_id,)
    )
    await db.commit()

    quiz = await get_quiz(db, gsession["quiz_id"])
    questions = json.loads(quiz["data"])
    chat_id = gsession["chat_id"]

    # Отсчёт
    for n in (3, 2, 1):
        await bot.send_message(chat_id, t(lang, "group_countdown", n=n))
        await asyncio.sleep(1)

    await bot.send_message(chat_id, t(lang, "group_start"))

    # Запустить вопросы последовательно
    asyncio.create_task(
        run_group_quiz(bot, db, chat_id, session_id, gsession["quiz_id"],
                       questions, gsession["created_by"], lang)
    )
finally:
    await db.close()
await callback.answer()
```

async def run_group_quiz(bot: Bot, db, chat_id: int, session_id: int, quiz_id: int,
questions: list, creator_id: int, lang: str):
“”“Запустить групповой тест последовательно.”””
missed_streak = 0
paused = False

```
for i, q in enumerate(questions):
    if paused:
        break

    try:
        poll_msg = await bot.send_poll(
            chat_id=chat_id,
            question=f"[{i + 1}/{len(questions)}] {q['question']}",
            options=q["options"],
            type="quiz",
            correct_option_id=q["correct"],
            is_anonymous=False,
            open_period=30,
        )
    except Exception as e:
        log.error(f"Group quiz send error: {e}")
        break

    await asyncio.sleep(31)

    # Проверить статус сессии
    try:
        db2 = await get_db()
        async with db2.execute(
            "SELECT status, missed_streak FROM group_sessions WHERE id=?", (session_id,)
        ) as cur:
            gs = await cur.fetchone()
        await db2.close()
    except Exception:
        break

    if not gs or gs["status"] == "finished":
        break

    # Считаем пропуски упрощённо — если никто не голосовал
    # (в реальной реализации надо трекать poll answers)
    # Здесь условно — streak не растёт
    missed_streak = 0

    if missed_streak >= 2:
        kb = InlineKeyboardBuilder()
        kb.button(text=t(lang, "btn_resume"), callback_data=f"gtest_resume:{session_id}")
        kb.button(text=t(lang, "btn_finish"), callback_data=f"gtest_finish:{session_id}")
        await bot.send_message(chat_id, t(lang, "group_two_missed"), reply_markup=kb.as_markup())
        paused = True
        break

if not paused:
    try:
        db3 = await get_db()
        await db3.execute(
            "UPDATE group_sessions SET status='finished' WHERE id=?", (session_id,)
        )
        await db3.commit()
        await db3.close()
    except Exception:
        pass
    await bot.send_message(chat_id, t(lang, "group_finished"))
```

@router.callback_query(F.data.startswith(“gtest_finish:”))
async def gtest_finish(callback: CallbackQuery, bot: Bot):
session_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
async with db.execute(
“SELECT * FROM group_sessions WHERE id=?”, (session_id,)
) as cur:
gs = await cur.fetchone()

```
    if not gs:
        await callback.answer("Not found", show_alert=True)
        return

    # Только создатель или админ
    is_creator = gs["created_by"] == callback.from_user.id
    if not is_creator:
        try:
            member = await bot.get_chat_member(gs["chat_id"], callback.from_user.id)
            is_group_admin = member.status in (
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            )
        except Exception:
            is_group_admin = False
        if not is_group_admin:
            await callback.answer(t(lang, "only_initiator_can_finish"), show_alert=True)
            return

    await db.execute(
        "UPDATE group_sessions SET status='finished' WHERE id=?", (session_id,)
    )
    await db.commit()
    await callback.message.edit_text(t(lang, "group_finished"))
finally:
    await db.close()
await callback.answer()
```

# ─── ADMIN PANEL ──────────────────────────────────────────────────────────

@router.message(F.text.in_({TEXTS[“ru”][“btn_admin”], TEXTS[“kk”][“btn_admin”]}))
async def admin_panel(message: Message):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
uid = message.from_user.id

```
    if await is_super_admin(uid):
        await message.answer(
            t(lang, "admin_panel"),
            reply_markup=admin_main_keyboard(lang),
            parse_mode=ParseMode.HTML,
        )
    else:
        section_ids = await get_section_admin_sections(db, uid)
        if not section_ids:
            await message.answer(t(lang, "not_admin"))
            return

        sections = await get_sections(db)
        my_sections = [s for s in sections if s["id"] in section_ids]
        title_field = "title_kk" if lang == "kk" else "title_ru"

        kb = InlineKeyboardBuilder()
        for s in my_sections:
            kb.button(text=s[title_field], callback_data=f"adm_section:{s['id']}")
        kb.adjust(1)
        await message.answer(
            t(lang, "section_admin_panel"),
            reply_markup=kb.as_markup(),
            parse_mode=ParseMode.HTML,
        )
finally:
    await db.close()
```

@router.callback_query(F.data.startswith(“adm_section:”))
async def admin_section_panel(callback: CallbackQuery):
section_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_admin_of_section(db, callback.from_user.id, section_id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    section = await get_section(db, section_id)
    title_field = "title_kk" if lang == "kk" else "title_ru"
    await callback.message.edit_text(
        f"⚙️ {section[title_field]}",
        reply_markup=section_admin_keyboard(lang, section_id),
    )
finally:
    await db.close()
await callback.answer()
```

# ─── ADD SECTION ──────────────────────────────────────────────────────────

@router.callback_query(F.data == “adm:add_section”)
async def adm_add_section_start(callback: CallbackQuery, state: FSMContext):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_super_admin(callback.from_user.id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return
await callback.message.answer(t(lang, “section_name_prompt_ru”))
await state.set_state(AdminState.add_section_ru)
finally:
await db.close()
await callback.answer()

@router.message(AdminState.add_section_ru, F.text)
async def adm_section_name_ru(message: Message, state: FSMContext):
await state.update_data(title_ru=message.text)
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
await message.answer(t(lang, “section_name_prompt_kk”))
await state.set_state(AdminState.add_section_kk)
finally:
await db.close()

@router.message(AdminState.add_section_kk, F.text)
async def adm_section_name_kk(message: Message, state: FSMContext):
data = await state.get_data()
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
await db.execute(
“INSERT INTO sections (title_ru, title_kk) VALUES (?, ?)”,
(data[“title_ru”], message.text),
)
await db.commit()
await message.answer(t(lang, “section_saved”))
await state.clear()
finally:
await db.close()

# ─── SECTIONS LIST (ADMIN) ────────────────────────────────────────────────

@router.callback_query(F.data == “adm:sections_list”)
async def adm_sections_list(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_super_admin(callback.from_user.id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    sections = await get_sections(db)
    if not sections:
        await callback.message.edit_text(t(lang, "no_sections"))
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    title_field = "title_kk" if lang == "kk" else "title_ru"
    for s in sections:
        kb.button(text=f"✏️ {s[title_field]}", callback_data=f"adm_edit_section:{s['id']}")
        kb.button(text="🗑", callback_data=f"adm_del_section:{s['id']}")
    kb.button(text=t(lang, "btn_back"), callback_data="adm:back")
    kb.adjust(2)
    await callback.message.edit_text(t(lang, "admin_section_panel"), reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“adm_del_section:”))
async def adm_delete_section(callback: CallbackQuery):
section_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_super_admin(callback.from_user.id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return
await db.execute(“UPDATE sections SET is_active=0 WHERE id=?”, (section_id,))
await db.commit()
await callback.answer(t(lang, “section_deleted”), show_alert=True)
await adm_sections_list(callback)
finally:
await db.close()

# ─── ADD QUIZ ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == “adm:add_quiz_choose_section”)
async def adm_add_quiz_choose_section(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
uid = callback.from_user.id
sections = await get_sections(db)
if await is_super_admin(uid):
my_sections = sections
else:
section_ids = await get_section_admin_sections(db, uid)
my_sections = [s for s in sections if s[“id”] in section_ids]

```
    if not my_sections:
        await callback.answer(t(lang, "no_sections"), show_alert=True)
        return

    title_field = "title_kk" if lang == "kk" else "title_ru"
    kb = InlineKeyboardBuilder()
    for s in my_sections:
        kb.button(text=s[title_field], callback_data=f"adm:add_quiz:{s['id']}")
    kb.adjust(1)
    await callback.message.edit_text(t(lang, "prompt_section_choice"), reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“adm:add_quiz:”))
async def adm_add_quiz_start(callback: CallbackQuery, state: FSMContext):
section_id = int(callback.data.split(”:”)[2])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_admin_of_section(db, callback.from_user.id, section_id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return
await state.update_data(section_id=section_id, quiz_buffer=[], lang=lang)
await callback.message.answer(t(lang, “quiz_title_prompt”))
await state.set_state(AdminState.quiz_title)
finally:
await db.close()
await callback.answer()

@router.message(AdminState.quiz_title, F.text)
async def adm_quiz_title(message: Message, state: FSMContext):
await state.update_data(quiz_title=message.text)
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
kb = InlineKeyboardBuilder()
types = [
(“🆓 Free”, “free”),
(“💎 Premium”, “premium”),
(“⭐ Stars”, “stars”),
(“🔒 Private”, “private”),
]
for label, val in types:
kb.button(text=label, callback_data=f”adm_quiz_type:{val}”)
kb.adjust(2)
await message.answer(t(lang, “quiz_type_prompt”), reply_markup=kb.as_markup())
await state.set_state(AdminState.quiz_type)
finally:
await db.close()

@router.callback_query(F.data.startswith(“adm_quiz_type:”), AdminState.quiz_type)
async def adm_quiz_type(callback: CallbackQuery, state: FSMContext):
access_type = callback.data.split(”:”)[1]
await state.update_data(access_type=access_type)
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if access_type == “stars”:
await callback.message.answer(t(lang, “quiz_stars_price_prompt”))
await state.set_state(AdminState.quiz_stars_price)
else:
await state.update_data(stars_price=0)
await callback.message.answer(
t(lang, “quiz_add_questions”),
reply_markup=_quiz_builder_keyboard(lang, 0),
parse_mode=ParseMode.HTML,
)
await state.set_state(AdminState.quiz_adding_questions)
finally:
await db.close()
await callback.answer()

@router.message(AdminState.quiz_stars_price, F.text)
async def adm_quiz_stars_price(message: Message, state: FSMContext):
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
try:
price = int(message.text.strip())
except ValueError:
await message.answer(“Введите целое число.”)
return
await state.update_data(stars_price=price)
await message.answer(
t(lang, “quiz_add_questions”),
reply_markup=_quiz_builder_keyboard(lang, 0),
parse_mode=ParseMode.HTML,
)
await state.set_state(AdminState.quiz_adding_questions)
finally:
await db.close()

def _quiz_builder_keyboard(lang: str, count: int) -> InlineKeyboardMarkup:
kb = InlineKeyboardBuilder()
kb.button(text=t(lang, “btn_save_quiz”), callback_data=“adm_quiz:save”)
kb.button(text=t(lang, “btn_add_more”), callback_data=“adm_quiz:add_more”)
kb.button(text=t(lang, “btn_clear_all”), callback_data=“adm_quiz:clear”)
kb.button(text=t(lang, “btn_cancel”), callback_data=“adm_quiz:cancel”)
kb.adjust(2)
return kb.as_markup()

@router.message(AdminState.quiz_adding_questions)
async def adm_quiz_add_question(message: Message, state: FSMContext):
“”“Принять вопрос текстом или пересланным quiz poll.”””
data = await state.get_data()
lang = data.get(“lang”, “ru”)
buffer: list = data.get(“quiz_buffer”, [])
num = len(buffer) + 1

```
question = None
error = None

# Пересланный quiz poll
if message.forward_from_chat or message.poll:
    poll = message.poll
    if poll:
        parsed = parse_poll_question(poll)
        if parsed:
            question = parsed
        else:
            error = "Poll не является quiz типом"
else:
    # Текстовый формат
    try:
        question = parse_text_question(message.text or "")
    except ValueError as e:
        error = str(e)

db = await get_db()
try:
    if error:
        kb = InlineKeyboardBuilder()
        kb.button(text=t(lang, "btn_continue_adding"), callback_data="adm_quiz:add_more")
        kb.button(text=t(lang, "btn_save_quiz"), callback_data="adm_quiz:save")
        kb.button(text=t(lang, "btn_cancel"), callback_data="adm_quiz:cancel")
        kb.adjust(2)
        await message.answer(
            t(lang, "parse_error", num=num, detail=error),
            reply_markup=kb.as_markup(),
        )
        return

    buffer.append(question)
    await state.update_data(quiz_buffer=buffer)
    await message.answer(
        t(lang, "quiz_buffer", count=len(buffer)),
        reply_markup=_quiz_builder_keyboard(lang, len(buffer)),
    )
finally:
    await db.close()
```

@router.callback_query(F.data.startswith(“adm_quiz:”))
async def adm_quiz_action(callback: CallbackQuery, state: FSMContext):
action = callback.data.split(”:”)[1]
data = await state.get_data()
lang = data.get(“lang”, “ru”)

```
db = await get_db()
try:
    if action == "save":
        buffer = data.get("quiz_buffer", [])
        if not buffer:
            await callback.answer("Буфер пустой!", show_alert=True)
            return
        section_id = data.get("section_id")
        quiz_title = data.get("quiz_title", "Без названия")
        access_type = data.get("access_type", "free")
        stars_price = data.get("stars_price", 0)

        await db.execute(
            """INSERT INTO quizzes (section_id, title, data, access_type, stars_price, created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (section_id, quiz_title, json.dumps(buffer), access_type, stars_price,
             callback.from_user.id),
        )
        await db.commit()
        await callback.message.edit_text(t(lang, "quiz_saved", count=len(buffer)))
        await state.clear()

    elif action == "add_more":
        await callback.message.edit_text(
            t(lang, "quiz_add_questions"),
            reply_markup=_quiz_builder_keyboard(lang, len(data.get("quiz_buffer", []))),
            parse_mode=ParseMode.HTML,
        )
        await state.set_state(AdminState.quiz_adding_questions)

    elif action == "clear":
        await state.update_data(quiz_buffer=[])
        await callback.message.edit_text(
            t(lang, "quiz_cleared"),
            reply_markup=_quiz_builder_keyboard(lang, 0),
        )

    elif action == "cancel":
        await state.clear()
        await callback.message.edit_text(t(lang, "quiz_cancelled"))
finally:
    await db.close()
await callback.answer()
```

# ─── QUIZ LIST (ADMIN) ────────────────────────────────────────────────────

@router.callback_query(F.data == “adm:quizzes_list”)
async def adm_quizzes_list_all(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
uid = callback.from_user.id

```
    if await is_super_admin(uid):
        async with db.execute(
            "SELECT q.*, s.title_ru FROM quizzes q JOIN sections s ON q.section_id=s.id"
            " WHERE q.is_active=1 ORDER BY q.id DESC LIMIT 30"
        ) as cur:
            quizzes = await cur.fetchall()
    else:
        section_ids = await get_section_admin_sections(db, uid)
        if not section_ids:
            await callback.answer(t(lang, "not_admin"), show_alert=True)
            return
        placeholders = ",".join("?" * len(section_ids))
        async with db.execute(
            f"SELECT q.*, s.title_ru FROM quizzes q JOIN sections s ON q.section_id=s.id"
            f" WHERE q.section_id IN ({placeholders}) AND q.is_active=1 ORDER BY q.id DESC",
            section_ids,
        ) as cur:
            quizzes = await cur.fetchall()

    if not quizzes:
        await callback.message.edit_text(t(lang, "no_quizzes"))
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for q in quizzes:
        kb.button(
            text=f"{q['title']} ({q['access_type']})",
            callback_data=f"adm_quiz_detail:{q['id']}",
        )
    kb.button(text=t(lang, "btn_back"), callback_data="adm:back")
    kb.adjust(1)
    await callback.message.edit_text(t(lang, "btn_quiz_list"), reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“adm_quiz_detail:”))
async def adm_quiz_detail(callback: CallbackQuery):
quiz_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
quiz = await get_quiz(db, quiz_id)
if not quiz:
await callback.answer(“Not found”, show_alert=True)
return

```
    questions = json.loads(quiz["data"])
    text = (
        f"📝 <b>{quiz['title']}</b>\n"
        f"Тип: {quiz['access_type']}\n"
        f"Stars: {quiz['stars_price']}\n"
        f"Вопросов: {len(questions)}\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 Удалить тест", callback_data=f"adm_del_quiz:{quiz_id}")
    if quiz["access_type"] == "private":
        kb.button(text="👤 Выдать доступ", callback_data=f"adm_private_access:{quiz_id}")
        kb.button(text="📊 Результаты", callback_data=f"adm_private_results:{quiz_id}")
    kb.button(text="💰 Сменить тип", callback_data=f"adm_change_type:{quiz_id}")
    kb.button(text=t(lang, "btn_back"), callback_data="adm:quizzes_list")
    kb.adjust(2)
    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode=ParseMode.HTML)
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“adm_del_quiz:”))
async def adm_delete_quiz(callback: CallbackQuery):
quiz_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
quiz = await get_quiz(db, quiz_id)
if not quiz or not await is_admin_of_section(db, callback.from_user.id, quiz[“section_id”]):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return
await db.execute(“UPDATE quizzes SET is_active=0 WHERE id=?”, (quiz_id,))
await db.commit()
await callback.message.edit_text(t(lang, “section_deleted”))
finally:
await db.close()
await callback.answer()

# ─── ADMIN MANAGEMENT ─────────────────────────────────────────────────────

@router.callback_query(F.data == “adm:admins_menu”)
async def adm_admins_menu(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_super_admin(callback.from_user.id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить админа раздела", callback_data="adm:add_section_admin")
    kb.button(text="🗑 Удалить админа", callback_data="adm:remove_section_admin")
    kb.button(text=t(lang, "btn_back"), callback_data="adm:back")
    kb.adjust(1)
    await callback.message.edit_text("👥 Управление администраторами", reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data == “adm:add_section_admin”)
async def adm_add_section_admin_start(callback: CallbackQuery, state: FSMContext):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_super_admin(callback.from_user.id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return
await callback.message.answer(t(lang, “prompt_user_id”))
await state.set_state(AdminState.add_section_admin_uid)
finally:
await db.close()
await callback.answer()

@router.message(AdminState.add_section_admin_uid, F.text)
async def adm_add_section_admin_uid(message: Message, state: FSMContext):
try:
uid = int(message.text.strip())
except ValueError:
await message.answer(“Неверный ID”)
return
await state.update_data(target_uid=uid)

```
db = await get_db()
try:
    lang = await get_user_lang(db, message.from_user.id)
    sections = await get_sections(db)
    title_field = "title_kk" if lang == "kk" else "title_ru"
    kb = InlineKeyboardBuilder()
    for s in sections:
        kb.button(text=s[title_field], callback_data=f"adm_admin_section:{s['id']}")
    kb.adjust(1)
    await message.answer(t(lang, "prompt_section_choice"), reply_markup=kb.as_markup())
    await state.set_state(AdminState.add_section_admin_section)
finally:
    await db.close()
```

@router.callback_query(F.data.startswith(“adm_admin_section:”), AdminState.add_section_admin_section)
async def adm_add_section_admin_section(callback: CallbackQuery, state: FSMContext):
section_id = int(callback.data.split(”:”)[1])
data = await state.get_data()
target_uid = data[“target_uid”]

```
db = await get_db()
try:
    lang = await get_user_lang(db, callback.from_user.id)
    await db.execute(
        "INSERT OR IGNORE INTO section_admins (user_id, section_id) VALUES (?,?)",
        (target_uid, section_id),
    )
    await db.commit()
    await callback.message.answer(t(lang, "admin_added"))
    await state.clear()
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data == “adm:remove_section_admin”)
async def adm_remove_section_admin_start(callback: CallbackQuery, state: FSMContext):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_super_admin(callback.from_user.id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return
await callback.message.answer(t(lang, “prompt_user_id”))
await state.set_state(AdminState.remove_section_admin_uid)
finally:
await db.close()
await callback.answer()

@router.message(AdminState.remove_section_admin_uid, F.text)
async def adm_remove_section_admin_uid(message: Message, state: FSMContext):
try:
uid = int(message.text.strip())
except ValueError:
await message.answer(“Неверный ID”)
return

```
db = await get_db()
try:
    lang = await get_user_lang(db, message.from_user.id)
    await db.execute("DELETE FROM section_admins WHERE user_id=?", (uid,))
    await db.commit()
    await message.answer(t(lang, "admin_removed"))
    await state.clear()
finally:
    await db.close()
```

# ─── PRIVATE ACCESS ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“adm_private_access:”))
async def adm_private_access_start(callback: CallbackQuery, state: FSMContext):
quiz_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
quiz = await get_quiz(db, quiz_id)
if not quiz or not await is_admin_of_section(db, callback.from_user.id, quiz[“section_id”]):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return
await state.update_data(private_quiz_id=quiz_id)
await callback.message.answer(t(lang, “prompt_user_id”))
await state.set_state(AdminState.private_access_uid)
finally:
await db.close()
await callback.answer()

@router.message(AdminState.private_access_uid, F.text)
async def adm_private_access_uid(message: Message, state: FSMContext):
try:
uid = int(message.text.strip())
except ValueError:
await message.answer(“Неверный ID”)
return

```
data = await state.get_data()
quiz_id = data["private_quiz_id"]

db = await get_db()
try:
    lang = await get_user_lang(db, message.from_user.id)
    await db.execute(
        """INSERT OR REPLACE INTO private_access (user_id, quiz_id, granted_by, max_attempts)
           VALUES (?, ?, ?, 2)""",
        (uid, quiz_id, message.from_user.id),
    )
    await db.commit()
    await message.answer(t(lang, "private_access_granted", uid=uid))
    await state.clear()
finally:
    await db.close()
```

# ─── PRIVATE TEST RESULTS (ADMIN) ─────────────────────────────────────────

@router.callback_query(F.data.startswith(“adm_private_results:”))
async def adm_private_results(callback: CallbackQuery):
quiz_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
quiz = await get_quiz(db, quiz_id)
if not quiz or not await is_admin_of_section(db, callback.from_user.id, quiz[“section_id”]):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    # Получить всех пользователей с доступом
    async with db.execute(
        "SELECT * FROM private_access WHERE quiz_id=?", (quiz_id,)
    ) as cur:
        accesses = await cur.fetchall()

    text = t(lang, "private_test_results_title", title=quiz["title"]) + "\n\n"

    for acc in accesses:
        uid = acc["user_id"]
        async with db.execute(
            "SELECT * FROM users WHERE user_id=?", (uid,)
        ) as cur:
            user_row = await cur.fetchone()
        uname = user_row["first_name"] if user_row else str(uid)

        async with db.execute(
            "SELECT * FROM results WHERE user_id=? AND quiz_id=? ORDER BY attempt_num",
            (uid, quiz_id),
        ) as cur:
            attempts = await cur.fetchall()

        text += f"👤 <b>{uname}</b> ({uid})\n"
        if not attempts:
            text += f"  {t(lang, 'no_attempts')}\n"
        else:
            for att in attempts:
                text += (
                    f"  {t(lang, 'attempt', n=att['attempt_num'])}: "
                    f"{att['score']}/{att['total']} — {att['percent']:.1f}%"
                    f" | {att['completed_at'][:16]}\n"
                )
        text += "\n"

    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_reset_attempts"), callback_data=f"adm_reset_att:{quiz_id}")
    kb.button(text=t(lang, "btn_delete_results"), callback_data=f"adm_del_results:{quiz_id}")
    kb.button(text=t(lang, "btn_back"), callback_data=f"adm_quiz_detail:{quiz_id}")
    kb.adjust(1)

    await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode=ParseMode.HTML)
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“adm_reset_att:”))
async def adm_reset_attempts_start(callback: CallbackQuery, state: FSMContext):
quiz_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
await state.update_data(reset_quiz_id=quiz_id)
await callback.message.answer(t(lang, “prompt_user_id”))
await state.set_state(AdminState.reset_attempts_uid)
finally:
await db.close()
await callback.answer()

@router.message(AdminState.reset_attempts_uid, F.text)
async def adm_reset_attempts_uid(message: Message, state: FSMContext):
try:
uid = int(message.text.strip())
except ValueError:
await message.answer(“Неверный ID”)
return

```
data = await state.get_data()
quiz_id = data["reset_quiz_id"]

db = await get_db()
try:
    lang = await get_user_lang(db, message.from_user.id)
    # Удалить результаты (сброс попыток)
    await db.execute(
        "DELETE FROM results WHERE user_id=? AND quiz_id=?", (uid, quiz_id)
    )
    # Сбросить счётчик или увеличить max_attempts
    await db.execute(
        "UPDATE private_access SET max_attempts=max_attempts+2 WHERE user_id=? AND quiz_id=?",
        (uid, quiz_id),
    )
    await db.commit()
    await message.answer(t(lang, "attempts_reset"))
    await state.clear()
finally:
    await db.close()
```

@router.callback_query(F.data.startswith(“adm_del_results:”))
async def adm_del_results(callback: CallbackQuery):
quiz_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
kb = InlineKeyboardBuilder()
kb.button(
text=t(lang, “btn_confirm”),
callback_data=f”adm_del_results_confirm:{quiz_id}:all”,
)
kb.button(text=t(lang, “btn_cancel”), callback_data=f”adm_private_results:{quiz_id}”)
kb.adjust(1)
await callback.message.edit_text(
t(lang, “confirm_delete”, uid=“всех пользователей”),
reply_markup=kb.as_markup(),
)
finally:
await db.close()
await callback.answer()

@router.callback_query(F.data.startswith(“adm_del_results_confirm:”))
async def adm_del_results_confirm(callback: CallbackQuery):
parts = callback.data.split(”:”)
quiz_id = int(parts[1])
scope = parts[2]  # “all” or user_id

```
db = await get_db()
try:
    lang = await get_user_lang(db, callback.from_user.id)
    if scope == "all":
        await db.execute("DELETE FROM results WHERE quiz_id=?", (quiz_id,))
    else:
        uid = int(scope)
        await db.execute(
            "DELETE FROM results WHERE user_id=? AND quiz_id=?", (uid, quiz_id)
        )
    await db.commit()
    await callback.message.edit_text(t(lang, "results_deleted"))
finally:
    await db.close()
await callback.answer()
```

# ─── APPEALS (ADMIN) ──────────────────────────────────────────────────────

@router.callback_query(F.data == “adm:appeals”)
async def adm_appeals(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
uid = callback.from_user.id

```
    if await is_super_admin(uid):
        async with db.execute(
            "SELECT a.*, q.title as quiz_title FROM appeals a"
            " LEFT JOIN quizzes q ON a.quiz_id=q.id"
            " WHERE a.status='pending' ORDER BY a.created_at DESC LIMIT 20"
        ) as cur:
            appeals = await cur.fetchall()
    else:
        section_ids = await get_section_admin_sections(db, uid)
        if not section_ids:
            await callback.answer(t(lang, "not_admin"), show_alert=True)
            return
        placeholders = ",".join("?" * len(section_ids))
        async with db.execute(
            f"SELECT a.*, q.title as quiz_title FROM appeals a"
            f" LEFT JOIN quizzes q ON a.quiz_id=q.id"
            f" WHERE a.status='pending' AND q.section_id IN ({placeholders})"
            f" ORDER BY a.created_at DESC LIMIT 20",
            section_ids,
        ) as cur:
            appeals = await cur.fetchall()

    if not appeals:
        await callback.message.edit_text("Апелляций нет.")
        await callback.answer()
        return

    text = t(lang, "btn_appeals") + "\n\n"
    kb = InlineKeyboardBuilder()
    for ap in appeals:
        text += f"#{ap['id']} {ap['quiz_title']} Q{ap['question_index'] + 1}: {ap['message'][:50]}\n"
        kb.button(
            text=f"#{ap['id']} — {ap['quiz_title'][:20]}",
            callback_data=f"appeal_detail:{ap['id']}",
        )
    kb.button(text=t(lang, "btn_back"), callback_data="adm:back")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“appeal_detail:”))
async def appeal_detail(callback: CallbackQuery):
appeal_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
async with db.execute(“SELECT * FROM appeals WHERE id=?”, (appeal_id,)) as cur:
ap = await cur.fetchone()
if not ap:
await callback.answer(“Not found”, show_alert=True)
return

```
    quiz = await get_quiz(db, ap["quiz_id"])
    text = (
        f"⚖️ Апелляция #{appeal_id}\n"
        f"Тест: {quiz['title'] if quiz else ap['quiz_id']}\n"
        f"Вопрос: #{ap['question_index'] + 1}\n"
        f"Текст: {ap['message']}\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_delete_question"),
              callback_data=f"appeal_adm:del_q:{appeal_id}")
    kb.button(text=t(lang, "btn_change_answer"),
              callback_data=f"appeal_adm:change_ans:{appeal_id}")
    kb.button(text=t(lang, "btn_reject_appeal"),
              callback_data=f"appeal_adm:reject:{appeal_id}")
    kb.button(text=t(lang, "btn_back"), callback_data="adm:appeals")
    kb.adjust(1)
    await callback.message.edit_text(text, reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“appeal_adm:”))
async def appeal_admin_action(callback: CallbackQuery, state: FSMContext):
parts = callback.data.split(”:”)
action = parts[1]
appeal_id = int(parts[2])

```
db = await get_db()
try:
    lang = await get_user_lang(db, callback.from_user.id)
    async with db.execute("SELECT * FROM appeals WHERE id=?", (appeal_id,)) as cur:
        ap = await cur.fetchone()
    if not ap:
        await callback.answer("Not found", show_alert=True)
        return

    quiz = await get_quiz(db, ap["quiz_id"])

    if action == "reject":
        await db.execute(
            "UPDATE appeals SET status='rejected', handled_by=?, handled_at=datetime('now') WHERE id=?",
            (callback.from_user.id, appeal_id),
        )
        await db.commit()
        await callback.message.edit_text(t(lang, "appeal_resolved"))

    elif action == "del_q":
        # Пометить вопрос удалённым из теста
        if quiz:
            questions = json.loads(quiz["data"])
            q_idx = ap["question_index"]
            if 0 <= q_idx < len(questions):
                questions.pop(q_idx)
                await db.execute(
                    "UPDATE quizzes SET data=? WHERE id=?",
                    (json.dumps(questions), quiz["id"]),
                )
        await db.execute(
            "UPDATE appeals SET status='resolved', handled_by=?, handled_at=datetime('now') WHERE id=?",
            (callback.from_user.id, appeal_id),
        )
        await db.commit()
        await callback.message.edit_text(t(lang, "appeal_resolved"))

    elif action == "change_ans":
        await state.update_data(appeal_id=appeal_id, appeal_quiz_id=ap["quiz_id"],
                                appeal_q_idx=ap["question_index"])
        await callback.message.answer("Введите индекс правильного ответа (0-based, число):")
        await state.set_state(AdminState.appeal_change_answer)
finally:
    await db.close()
await callback.answer()
```

@router.message(AdminState.appeal_change_answer, F.text)
async def appeal_change_answer_input(message: Message, state: FSMContext):
try:
new_correct = int(message.text.strip())
except ValueError:
await message.answer(“Введите число.”)
return

```
data = await state.get_data()
db = await get_db()
try:
    lang = await get_user_lang(db, message.from_user.id)
    quiz = await get_quiz(db, data["appeal_quiz_id"])
    if quiz:
        questions = json.loads(quiz["data"])
        q_idx = data["appeal_q_idx"]
        if 0 <= q_idx < len(questions):
            questions[q_idx]["correct"] = new_correct
            await db.execute(
                "UPDATE quizzes SET data=? WHERE id=?",
                (json.dumps(questions), quiz["id"]),
            )
    await db.execute(
        "UPDATE appeals SET status='resolved', handled_by=?, handled_at=datetime('now') WHERE id=?",
        (message.from_user.id, data["appeal_id"]),
    )
    await db.commit()
    await message.answer(t(lang, "appeal_resolved"))
    await state.clear()
finally:
    await db.close()
```

# ─── CHANNELS (ADMIN) ─────────────────────────────────────────────────────

@router.callback_query(F.data == “adm:channels”)
async def adm_channels(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_super_admin(callback.from_user.id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    sections = await get_sections(db)
    title_field = "title_kk" if lang == "kk" else "title_ru"
    kb = InlineKeyboardBuilder()
    for s in sections:
        ch = s["required_channel_username"] or "нет"
        kb.button(
            text=f"{s[title_field]}: {ch}",
            callback_data=f"adm_set_channel:{s['id']}",
        )
    kb.button(text=t(lang, "btn_back"), callback_data="adm:back")
    kb.adjust(1)
    await callback.message.edit_text(t(lang, "btn_channels"), reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“adm_set_channel:”))
async def adm_set_channel_start(callback: CallbackQuery, state: FSMContext):
section_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
await state.update_data(channel_section_id=section_id)
await callback.message.answer(t(lang, “channel_prompt”))
await state.set_state(AdminState.set_channel)
finally:
await db.close()
await callback.answer()

@router.message(AdminState.set_channel, F.text)
async def adm_set_channel_input(message: Message, state: FSMContext):
data = await state.get_data()
section_id = data[“channel_section_id”]
db = await get_db()
try:
lang = await get_user_lang(db, message.from_user.id)
text = message.text.strip()
if text.lower() in (“нет”, “жоқ”, “no”, “-”):
await db.execute(
“UPDATE sections SET required_channel_username=NULL, require_subscription=0 WHERE id=?”,
(section_id,),
)
else:
channel = text if text.startswith(”@”) else “@” + text
await db.execute(
“UPDATE sections SET required_channel_username=?, require_subscription=1 WHERE id=?”,
(channel, section_id),
)
await db.commit()
await message.answer(t(lang, “channel_saved”))
await state.clear()
finally:
await db.close()

# ─── STATS (ADMIN) ────────────────────────────────────────────────────────

@router.callback_query(F.data == “adm:stats”)
async def adm_stats(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_super_admin(callback.from_user.id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    async with db.execute(
        """SELECT u.user_id, u.first_name, u.last_active_at,
                  r.quiz_id, q.title as quiz_title, r.score, r.total, r.percent, r.early
           FROM users u
           LEFT JOIN results r ON u.user_id=r.user_id
           LEFT JOIN quizzes q ON r.quiz_id=q.id
           ORDER BY u.last_active_at DESC LIMIT 20"""
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        await callback.message.edit_text(t(lang, "no_stats"))
        await callback.answer()
        return

    text = t(lang, "stats_title") + "\n\n"
    for r in rows:
        early = " ⚠️" if r["early"] else ""
        quiz_info = (
            f"  📝 {r['quiz_title']}: {r['score']}/{r['total']} ({r['percent']:.1f}%){early}\n"
            if r["quiz_title"]
            else "  (нет тестов)\n"
        )
        text += (
            f"👤 {r['first_name']} ({r['user_id']})\n"
            f"  🕐 {r['last_active_at'][:16]}\n"
            f"{quiz_info}\n"
        )

    kb = InlineKeyboardBuilder()
    kb.button(text=t(lang, "btn_back"), callback_data="adm:back")
    await callback.message.edit_text(
        text[:4000], reply_markup=kb.as_markup(), parse_mode=ParseMode.HTML
    )
finally:
    await db.close()
await callback.answer()
```

# ─── BACK ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == “adm:back”)
async def adm_back(callback: CallbackQuery):
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
await callback.message.edit_text(
t(lang, “admin_panel”),
reply_markup=admin_main_keyboard(lang),
parse_mode=ParseMode.HTML,
)
finally:
await db.close()
await callback.answer()

# ─── CHANGE QUIZ TYPE ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“adm_change_type:”))
async def adm_change_type(callback: CallbackQuery):
quiz_id = int(callback.data.split(”:”)[1])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
quiz = await get_quiz(db, quiz_id)
if not quiz or not await is_admin_of_section(db, callback.from_user.id, quiz[“section_id”]):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    kb = InlineKeyboardBuilder()
    for label, val in [("🆓 Free", "free"), ("💎 Premium", "premium"),
                       ("⭐ Stars", "stars"), ("🔒 Private", "private")]:
        kb.button(text=label, callback_data=f"adm_set_type:{quiz_id}:{val}")
    kb.adjust(2)
    await callback.message.edit_text(t(lang, "quiz_type_prompt"), reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

@router.callback_query(F.data.startswith(“adm_set_type:”))
async def adm_set_type(callback: CallbackQuery):
parts = callback.data.split(”:”)
quiz_id = int(parts[1])
new_type = parts[2]
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
await db.execute(
“UPDATE quizzes SET access_type=? WHERE id=?”, (new_type, quiz_id)
)
await db.commit()
await callback.message.edit_text(f”✅ Тип изменён на {new_type}”)
finally:
await db.close()
await callback.answer()

# ─── SECTION ADMIN QUIZZES ────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“adm:quizzes:”))
async def adm_section_quizzes(callback: CallbackQuery):
section_id = int(callback.data.split(”:”)[2])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_admin_of_section(db, callback.from_user.id, section_id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    quizzes = await get_quizzes_for_section(db, section_id)
    if not quizzes:
        await callback.message.edit_text(t(lang, "no_quizzes"))
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for q in quizzes:
        kb.button(
            text=f"{q['title']} ({q['access_type']})",
            callback_data=f"adm_quiz_detail:{q['id']}",
        )
    kb.button(text=t(lang, "btn_back"), callback_data=f"adm_section:{section_id}")
    kb.adjust(1)
    await callback.message.edit_text(t(lang, "btn_quiz_list"), reply_markup=kb.as_markup())
finally:
    await db.close()
await callback.answer()
```

# ─── SECTION ADMIN RESULTS ────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“adm:results:”))
async def adm_section_results(callback: CallbackQuery):
section_id = int(callback.data.split(”:”)[2])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_admin_of_section(db, callback.from_user.id, section_id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    async with db.execute(
        """SELECT r.*, u.first_name, q.title as quiz_title
           FROM results r
           JOIN users u ON r.user_id=u.user_id
           JOIN quizzes q ON r.quiz_id=q.id
           WHERE r.section_id=? ORDER BY r.completed_at DESC LIMIT 30""",
        (section_id,),
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        await callback.message.edit_text(t(lang, "no_stats"))
        await callback.answer()
        return

    text = t(lang, "stats_title") + "\n\n"
    for r in rows:
        text += (
            f"👤 {r['first_name']} | {r['quiz_title']}\n"
            f"  {r['score']}/{r['total']} — {r['percent']:.1f}%"
            f" | {r['completed_at'][:16]}\n\n"
        )

    await callback.message.edit_text(text[:4000], parse_mode=ParseMode.HTML)
finally:
    await db.close()
await callback.answer()
```

# ─── SECTION ADMIN APPEALS ────────────────────────────────────────────────

@router.callback_query(F.data.startswith(“adm:appeals:”))
async def adm_section_appeals(callback: CallbackQuery):
section_id = int(callback.data.split(”:”)[2])
db = await get_db()
try:
lang = await get_user_lang(db, callback.from_user.id)
if not await is_admin_of_section(db, callback.from_user.id, section_id):
await callback.answer(t(lang, “not_admin”), show_alert=True)
return

```
    async with db.execute(
        """SELECT a.*, q.title as quiz_title FROM appeals a
           LEFT JOIN quizzes q ON a.quiz_id=q.id
           WHERE a.status='pending' AND q.section_id=?
           ORDER BY a.created_at DESC LIMIT 20""",
        (section_id,),
    ) as cur:
        appeals = await cur.fetchall()

    if not appeals:
        await callback.message.edit_text("Апелляций нет.")
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for ap in appeals:
        kb.button(
            text=f"#{ap['id']} {ap['quiz_title'][:20]}",
            callback_data=f"appeal_detail:{ap['id']}",
        )
    kb.adjust(1)
    await callback.message.edit_text(
        f"Апелляций: {len(appeals)}", reply_markup=kb.as_markup()
    )
finally:
    await db.close()
await callback.answer()
```

# ─── TOUCH ACTIVE ─────────────────────────────────────────────────────────

@router.message()
async def touch_active(message: Message):
“”“Обновить last_active_at при любом сообщении.”””
db = await get_db()
try:
await db.execute(
“UPDATE users SET last_active_at=datetime(‘now’) WHERE user_id=?”,
(message.from_user.id,),
)
await db.commit()
finally:
await db.close()

# ─── MAIN ─────────────────────────────────────────────────────────────────

async def main():
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)

```
# Инициализация БД
db = await get_db()
try:
    await init_db(db)
    log.info("База данных инициализирована.")
finally:
    await db.close()

log.info("Бот запущен.")
await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
```

if **name** == “**main**”:
asyncio.run(main())
