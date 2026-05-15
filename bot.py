import os
import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from aiogram.filters.callback_data import CallbackData

import database as db
import excel_utils as excel

# Настройка логирования
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMINS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id]

bot = Bot(token=TOKEN)
dp = Dispatcher()

def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# --- СТРУКТУРЫ ДАННЫХ (Каллбеки и Состояния) ---

class BetCallback(CallbackData, prefix="bet"):
    game_id: int
    action: str # 'start', 't1', 't2', 'draw'

class BetForm(StatesGroup):
    waiting_for_amount = State()

# --- ФОНОВЫЕ ЗАДАЧИ ---

async def fetch_games_job():
    while True:
        await db.create_mock_game_if_empty()
        await asyncio.sleep(3600)

# --- НАСТРОЙКА МЕНЮ КОМАНД ---

async def set_commands(bot: Bot):
    user_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="games", description="Доступные матчи"),
    ]
    
    admin_commands = user_commands + [
        BotCommand(command="creategame", description="Создать матч (Админ)"),
        BotCommand(command="deletegame", description="Удалить матч (Админ)"),
        BotCommand(command="gamebets", description="Ставки на матч (Админ)"),
        BotCommand(command="setodds", description="Изменить коэффициенты (Админ)"),
        BotCommand(command="setresult", description="Завершить матч (Админ)"),
    ]

    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    
    for admin_id in ADMINS:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception as e:
            logging.error(f"Не удалось установить команды для админа {admin_id}: {e}")

# --- ХЕНДЛЕРЫ ПОЛЬЗОВАТЕЛЕЙ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await db.get_user_balance(message.from_user.id) # Регистрируем пользователя, если его нет в БД
    text = (f"🏒 Добро пожаловать на ставки ЧМ 2026 по хоккею!\n\n"
            f"Этот бот позволяет делать виртуальные ставки на матчи турнира. Угадывайте исходы, проверяйте свою интуицию и зарабатывайте $GUM!\n\n"
            f"Используйте /games чтобы посмотреть список доступных матчей.")
    await message.answer(text)

@dp.message(Command("games"))
async def cmd_games(message: types.Message):
    games = await db.get_active_games()
    if not games:
        await message.answer("Сейчас нет доступных матчей.")
        return

    for g in games:
        # g = (id, team1, team2, start_time, odds1, odds2, odds_draw, status, result)
        text = (f"🥅 <b>[ID: {g[0]}] {g[1]} vs {g[2]}</b>\n"
                f"🕒 Начало: {g[3]}\n\n"
                f"Коэффициенты:\n"
                f"Победа 1 ({g[1]}): {g[4]}\n"
                f"Ничья: {g[6]}\n"
                f"Победа 2 ({g[2]}): {g[5]}")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Сделать ставку 💵", callback_data=BetCallback(game_id=g[0], action="start").pack())]
        ])
        
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

# Нажатие на "Сделать ставку"
@dp.callback_query(BetCallback.filter(F.action == "start"))
async def process_bet_start(callback: types.CallbackQuery, callback_data: BetCallback):
    game = await db.get_game(callback_data.game_id)
    if not game:
        await callback.answer("Игра не найдена.", show_alert=True)
        return

    if game[7] == 'finished':
        await callback.answer("Этот матч уже завершен и недоступен для ставок.", show_alert=True)
        return
        
    if await db.has_user_bet(callback.from_user.id, callback_data.game_id):
        await callback.answer("Вы уже сделали ставку на этот матч! Можно ставить только один раз.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"П1 ({game[4]})", callback_data=BetCallback(game_id=game[0], action="t1").pack()),
            InlineKeyboardButton(text=f"Х ({game[6]})", callback_data=BetCallback(game_id=game[0], action="draw").pack()),
            InlineKeyboardButton(text=f"П2 ({game[5]})", callback_data=BetCallback(game_id=game[0], action="t2").pack())
        ]
    ])
    await callback.message.edit_text(f"Выберите исход матча <b>[ID: {game[0]}] {game[1]} vs {game[2]}</b>:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# Выбор исхода матча (П1, Х, П2)
@dp.callback_query(BetCallback.filter(F.action.in_({"t1", "t2", "draw"})))
async def process_bet_choice(callback: types.CallbackQuery, callback_data: BetCallback, state: FSMContext):
    game = await db.get_game(callback_data.game_id)
    
    if game[7] == 'finished':
        await callback.answer("Этот матч уже завершен и недоступен для ставок.", show_alert=True)
        return

    # Проверка времени (за 30 минут)
    start_time = datetime.strptime(game[3], "%Y-%m-%d %H:%M:%S")
    if start_time - datetime.now() <= timedelta(minutes=30):
        await callback.answer("Ставки закрыты! До начала осталось менее 30 минут.", show_alert=True)
        return

    # Сохраняем выбор в машину состояний
    await state.update_data(game_id=callback_data.game_id, choice=callback_data.action, team1=game[1], team2=game[2])
    await state.set_state(BetForm.waiting_for_amount)
    
    await callback.message.answer("Введите сумму ставки в $GUM (от 1000 до 100 000):")
    await callback.answer()

# Ввод суммы ставки
@dp.message(BetForm.waiting_for_amount)
async def process_bet_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if not (1000 <= amount <= 100000):
            await message.answer("Пожалуйста, введите сумму от 1000 до 100000 $GUM.")
            return
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число.")
        return

    data = await state.get_data()
    user_id = message.from_user.id
    
    if await db.has_user_bet(user_id, data['game_id']):
        await message.answer("Вы уже сделали ставку на этот матч! Можно ставить только один раз.")
        await state.clear()
        return
        
    balance = await db.get_user_balance(user_id)

    # Добавляем ставку
    await db.add_bet(user_id, data['game_id'], data['choice'], amount)
    
    choice_str = data['team1'] if data['choice'] == 't1' else data['team2'] if data['choice'] == 't2' else 'Ничья'
    await message.answer(f"✅ Ставка успешно принята!\nМатч: [ID: {data['game_id']}] {data['team1']} - {data['team2']}\nИсход: {choice_str}\nСумма: {amount:.2f} $GUM")
    
    await state.clear()

# --- ХЕНДЛЕРЫ АДМИНИСТРАТОРА ---

@dp.message(Command("creategame"))
async def admin_create_game(message: types.Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    # Ожидаем: /creategame Команда1 Команда2 YYYY-MM-DD HH:MM П1 П2 Ничья
    if len(args) != 8:
        await message.answer("Формат: /creategame <Команда1> <Команда2> <YYYY-MM-DD> <HH:MM> <П1> <П2> <Ничья>\n"
                             "Пример: /creategame Канада США 2026-05-15 20:00 1.5 2.5 4.0\n"
                             "Если название команды из двух слов, пишите слитно или через дефис (например, Чехия-U20).")
        return
    
    try:
        team1, team2 = args[1], args[2]
        start_time = f"{args[3]} {args[4]}:00"
        t1, t2, draw = float(args[5]), float(args[6]), float(args[7])
        
        # Проверяем формат времени
        datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
        
        await db.add_game(team1, team2, start_time, t1, t2, draw)
        await message.answer(f"✅ Матч <b>{team1} - {team2}</b> успешно создан!\nНачало: {start_time}\nКэфы: П1({t1}) П2({t2}) Х({draw})", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Ошибка формата данных. Убедитесь, что дата введена как YYYY-MM-DD HH:MM, а коэффициенты - числа (через точку).")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("deletegame"))
async def admin_delete_game(message: types.Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Формат: /deletegame <ID игры>")
        return
    
    try:
        game_id = int(args[1])
        game = await db.get_game(game_id)
        if not game:
            await message.answer("Игра не найдена.")
            return
        
        await db.delete_game(game_id)
        await message.answer(f"✅ Игра {game_id} (<b>{game[1]} - {game[2]}</b>) и все связанные с ней ставки успешно удалены!", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Ошибка: ID игры должен быть числом.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("gamebets"))
async def admin_game_bets(message: types.Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Формат: /gamebets <ID игры>")
        return
    
    try:
        game_id = int(args[1])
        game = await db.get_game(game_id)
        if not game:
            await message.answer("Игра не найдена.")
            return
        
        bets = await db.get_game_bets(game_id)
        if not bets:
            await message.answer(f"На матч {game_id} (<b>{game[1]} - {game[2]}</b>) пока нет ставок.", parse_mode="HTML")
            return
        
        text = f"📊 Ставки на матч <b>{game[1]} - {game[2]}</b> (ID: {game_id}):\n\n"
        total_amount = 0
        for user_id, choice, amount in bets:
            choice_str = game[1] if choice == 't1' else game[2] if choice == 't2' else 'Ничья'
            try:
                chat_info = await bot.get_chat(user_id)
                username = f"@{chat_info.username}" if chat_info.username else chat_info.first_name
            except Exception:
                username = "Неизвестно"
                
            text += f"👤 {username} (ID: {user_id}): {amount:.2f} $GUM на {choice_str}\n"
            total_amount += amount
        
        text += f"\n💰 Общая сумма ставок: {total_amount:.2f} $GUM"
        await message.answer(text, parse_mode="HTML")
        
    except ValueError:
        await message.answer("❌ Ошибка: ID игры должен быть числом.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@dp.message(Command("setodds"))
async def admin_set_odds(message: types.Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 5:
        await message.answer("Формат: /setodds <ID игры> <П1> <П2> <Ничья>")
        return
    try:
        game_id, t1, t2, draw = map(float, args[1:])
        await db.update_odds(int(game_id), t1, t2, draw)
        await message.answer(f"✅ Коэффициенты для игры {int(game_id)} обновлены!")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")

@dp.message(Command("setresult"))
async def admin_set_result(message: types.Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 3:
        await message.answer("Формат: /setresult <ID игры> <t1|t2|draw>")
        return

    game_id = int(args[1])
    result = args[2].lower()

    if result not in ['t1', 't2', 'draw']:
        await message.answer("Неверный исход. Используйте: t1, t2 или draw.")
        return

    game = await db.get_game(game_id)
    if not game:
        await message.answer("Игра не найдена.")
        return

    winning_odds = game[4] if result == 't1' else game[5] if result == 't2' else game[6]

    # Фиксируем результат и генерируем отчет
    await db.set_game_result(game_id, result) # Это должно быть до process_game_results, чтобы статус был "finished"
    excel_path = await excel.process_game_results(bot, game_id, result, winning_odds, game[1], game[2])
    
    # Отправляем файл
    file = FSInputFile(excel_path)
    await message.answer_document(document=file, caption=f"✅ Матч {game_id} завершен.\nПобедный исход: {result}\nОтчет прикреплен.")
    
    # Удаляем локальный файл после отправки
    os.remove(excel_path)

async def main():
    await db.init_db()
    asyncio.create_task(fetch_games_job()) # Запуск парсера в фоне
    await set_commands(bot)
    logging.info("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную.")
