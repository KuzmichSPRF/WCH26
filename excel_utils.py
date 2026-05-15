import pandas as pd
import aiosqlite
from database import DB_NAME
import os

async def process_game_results(game_id: int, result: str, odds: float) -> str:
    """Рассчитывает выигрыши, обновляет балансы и возвращает путь к Excel файлу."""
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT user_id, choice, amount FROM bets WHERE game_id = ?"
        async with db.execute(query, (game_id,)) as cursor:
            bets = await cursor.fetchall()
            
    data = []
    for user_id, choice, amount in bets:
        is_winner = (choice == result)
        winnings = round(amount * odds, 2) if is_winner else 0
        
        async with aiosqlite.connect(DB_NAME) as db:
            status = 'won' if is_winner else 'lost'
            await db.execute("UPDATE bets SET status=? WHERE user_id=? AND game_id=?", 
                             (status, user_id, game_id))
            if is_winner:
                await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", 
                                 (winnings, user_id))
            await db.commit()
            
        data.append({
            "ID Игрока": user_id,
            "Ставка ($GUM)": amount,
            "Выбор": choice,
            "Статус": "Выигрыш" if is_winner else "Проигрыш",
            "Выигрыш ($GUM)": winnings
        })

    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=["ID Игрока", "Ставка ($GUM)", "Выбор", "Статус", "Выигрыш ($GUM)"])
        
    filename = f"report_game_{game_id}.xlsx"
    df.to_excel(filename, index=False)
    return filename
