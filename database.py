import aiosqlite
from datetime import datetime, timedelta

DB_NAME = "hockey_bets.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица пользователей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 1000.0
            )
        ''')
        # Таблица игр
        await db.execute('''
            CREATE TABLE IF NOT EXISTS games (
                game_id INTEGER PRIMARY KEY AUTOINCREMENT,
                team1 TEXT,
                team2 TEXT,
                start_time TIMESTAMP,
                odds_t1 REAL,
                odds_t2 REAL,
                odds_draw REAL,
                status TEXT DEFAULT 'pending',
                result TEXT
            )
        ''')
        # Таблица ставок
        await db.execute('''
            CREATE TABLE IF NOT EXISTS bets (
                bet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_id INTEGER,
                choice TEXT,
                amount REAL,
                status TEXT DEFAULT 'pending'
            )
        ''')
        await db.commit()

async def get_user_balance(user_id: int) -> float:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0]
            # Если пользователя нет, создаем и даем 1000 $GUM
            await db.execute('INSERT INTO users (user_id) VALUES (?)', (user_id,))
            await db.commit()
            return 1000.0

async def has_user_bet(user_id: int, game_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM bets WHERE user_id = ? AND game_id = ?", (user_id, game_id)) as cursor:
            return await cursor.fetchone() is not None

async def add_bet(user_id: int, game_id: int, choice: str, amount: float):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (amount, user_id))
        await db.execute('INSERT INTO bets (user_id, game_id, choice, amount) VALUES (?, ?, ?, ?)',
                         (user_id, game_id, choice, amount))
        await db.commit()

async def get_active_games():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM games WHERE status != 'finished'") as cursor:
            return await cursor.fetchall()

async def get_game(game_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)) as cursor:
            return await cursor.fetchone()

async def update_odds(game_id: int, t1: float, t2: float, draw: float):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE games SET odds_t1=?, odds_t2=?, odds_draw=? WHERE game_id=?', 
                         (t1, t2, draw, game_id))
        await db.commit()

async def set_game_result(game_id: int, result: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE games SET result=?, status='finished' WHERE game_id=?", (result, game_id))
        await db.commit()

async def add_game(team1: str, team2: str, start_time: str, odds_t1: float, odds_t2: float, odds_draw: float):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT INTO games (team1, team2, start_time, odds_t1, odds_t2, odds_draw)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (team1, team2, start_time, odds_t1, odds_t2, odds_draw))
        await db.commit()

async def delete_game(game_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM games WHERE game_id = ?", (game_id,))
        await db.execute("DELETE FROM bets WHERE game_id = ?", (game_id,))
        await db.commit()

async def get_game_bets(game_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, choice, amount FROM bets WHERE game_id = ?", (game_id,)) as cursor:
            return await cursor.fetchall()
