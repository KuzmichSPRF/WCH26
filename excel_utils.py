import pandas as pd
import aiosqlite
from database import DB_NAME
import os
from aiogram import Bot

async def process_game_results(bot: Bot, game_id: int, result: str, odds: float, team1: str, team2: str) -> str:
    """Рассчитывает выигрыши, обновляет балансы и возвращает путь к Excel файлу."""
    data = []
    total_staked = 0.0
    total_winnings = 0.0
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT user_id, choice, amount FROM bets WHERE game_id = ?"
        async with db.execute(query, (game_id,)) as cursor:
            bets = await cursor.fetchall()
            
        for user_id, choice, amount in bets:
            total_staked += amount
            is_winner = (choice == result)
            winnings = round(amount * odds, 2) if is_winner else 0
            if is_winner:
                total_winnings += winnings
            
            try:
                chat_info = await bot.get_chat(user_id)
                username = f"@{chat_info.username}" if chat_info.username else chat_info.first_name
            except Exception:
                username = "Неизвестно"
            
            status = 'won' if is_winner else 'lost'
            await db.execute("UPDATE bets SET status=? WHERE user_id=? AND game_id=?", 
                             (status, user_id, game_id))
            if is_winner:
                await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", 
                                 (winnings, user_id))

            # Отправка уведомления пользователю
            if is_winner:
                notification_text = (f"🎉 Ваша ставка на матч <b>[ID: {game_id}] {team1} - {team2}</b> выиграла!\n"
                                     f"Ваш выигрыш: <b>{winnings:.2f} $GUM</b>.\n"
                                     f"Выигрыш будет начислен в течение 24 часов.")
            else:
                notification_text = (f"😢 Ваша ставка на матч <b>[ID: {game_id}] {team1} - {team2}</b> проиграла.\n"
                                     f"Удачи в следующий раз!")
            
            try:
                await bot.send_message(chat_id=user_id, text=notification_text, parse_mode="HTML")
            except Exception:
                pass # Игнорируем ошибки (например, если пользователь заблокировал бота)
                
            data.append({
                "ID Игрока": user_id,
                "Юзернейм": username,
                "Ставка ($GUM)": amount,
                "Выбор": choice,
                "Статус": "Выигрыш" if is_winner else "Проигрыш",
                "Выигрыш ($GUM)": winnings
            })

        await db.commit() # Сохраняем все изменения БД разом

    net_result = total_staked - total_winnings
    financial_summary_text = (
        f"\n--- Финансовый результат для бота ---\n"
        f"💰 Всего поставлено: {total_staked:.2f} $GUM\n"
        f"💸 Всего выплат: {total_winnings:.2f} $GUM\n"
        f"📊 Результат бота: {net_result:+.2f} $GUM"
    )

    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=["ID Игрока", "Юзернейм", "Ставка ($GUM)", "Выбор", "Статус", "Выигрыш ($GUM)"])
        
    filename = f"report_game_{game_id}.xlsx"
    df.to_excel(filename, index=False)
    return filename, financial_summary_text
