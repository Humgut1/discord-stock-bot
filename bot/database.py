import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "game.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id  TEXT PRIMARY KEY,
            username    TEXT,
            cash        REAL NOT NULL DEFAULT 1000000,
            season      INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS holdings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id  TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            name        TEXT NOT NULL,
            qty         INTEGER NOT NULL,
            avg_price   REAL NOT NULL,
            season      INTEGER NOT NULL DEFAULT 1,
            UNIQUE(discord_id, symbol, season)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id  TEXT NOT NULL,
            username    TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            name        TEXT NOT NULL,
            order_type  TEXT NOT NULL,  -- buy / sell
            qty         INTEGER NOT NULL,
            price       REAL NOT NULL,
            filled      INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            season      INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS seasons (
            id          INTEGER PRIMARY KEY,
            start_date  TEXT NOT NULL,
            end_date    TEXT NOT NULL,
            init_cash   REAL NOT NULL DEFAULT 1000000,
            active      INTEGER NOT NULL DEFAULT 1
        );

        INSERT OR IGNORE INTO seasons(id, start_date, end_date) VALUES(1, date('now'), date('now','+7 days'));
        """)


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ── 유저 ──

def ensure_user(discord_id: str, username: str, season: int = 1):
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO users(discord_id, username, season) VALUES(?,?,?)",
            (discord_id, username, season),
        )


def get_user(discord_id: str) -> sqlite3.Row | None:
    with _conn() as con:
        return con.execute("SELECT * FROM users WHERE discord_id=?", (discord_id,)).fetchone()


# ── 보유 종목 ──

def get_holdings(discord_id: str, season: int = 1) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM holdings WHERE discord_id=? AND season=?",
            (discord_id, season),
        ).fetchall()


def upsert_holding(discord_id: str, symbol: str, name: str, qty: int, avg_price: float, season: int = 1):
    with _conn() as con:
        existing = con.execute(
            "SELECT * FROM holdings WHERE discord_id=? AND symbol=? AND season=?",
            (discord_id, symbol, season),
        ).fetchone()
        if existing:
            new_qty = existing["qty"] + qty
            if new_qty <= 0:
                con.execute(
                    "DELETE FROM holdings WHERE discord_id=? AND symbol=? AND season=?",
                    (discord_id, symbol, season),
                )
            else:
                new_avg = (existing["avg_price"] * existing["qty"] + avg_price * qty) / new_qty
                con.execute(
                    "UPDATE holdings SET qty=?, avg_price=? WHERE discord_id=? AND symbol=? AND season=?",
                    (new_qty, new_avg, discord_id, symbol, season),
                )
        else:
            con.execute(
                "INSERT INTO holdings(discord_id, symbol, name, qty, avg_price, season) VALUES(?,?,?,?,?,?)",
                (discord_id, symbol, name, qty, avg_price, season),
            )


def reduce_holding(discord_id: str, symbol: str, qty: int, season: int = 1):
    with _conn() as con:
        existing = con.execute(
            "SELECT qty FROM holdings WHERE discord_id=? AND symbol=? AND season=?",
            (discord_id, symbol, season),
        ).fetchone()
        if not existing:
            raise ValueError("보유 종목 없음")
        new_qty = existing["qty"] - qty
        if new_qty < 0:
            raise ValueError("보유 수량 부족")
        if new_qty == 0:
            con.execute(
                "DELETE FROM holdings WHERE discord_id=? AND symbol=? AND season=?",
                (discord_id, symbol, season),
            )
        else:
            con.execute(
                "UPDATE holdings SET qty=? WHERE discord_id=? AND symbol=? AND season=?",
                (new_qty, discord_id, symbol, season),
            )


# ── 현금 ──

def update_cash(discord_id: str, delta: float):
    with _conn() as con:
        con.execute("UPDATE users SET cash = cash + ? WHERE discord_id=?", (delta, discord_id))


# ── 주문 ──

def create_order(discord_id: str, username: str, symbol: str, name: str,
                 order_type: str, qty: int, price: float, season: int = 1) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO orders(discord_id, username, symbol, name, order_type, qty, price, season)
               VALUES(?,?,?,?,?,?,?,?)""",
            (discord_id, username, symbol, name, order_type, qty, price, season),
        )
        return cur.lastrowid


def get_pending_orders(season: int = 1) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM orders WHERE filled=0 AND season=?", (season,)
        ).fetchall()


def get_user_pending_orders(discord_id: str, season: int = 1) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM orders WHERE discord_id=? AND filled=0 AND season=?",
            (discord_id, season),
        ).fetchall()


def fill_order(order_id: int):
    with _conn() as con:
        con.execute("UPDATE orders SET filled=1 WHERE id=?", (order_id,))


def cancel_order(order_id: int, discord_id: str) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM orders WHERE id=? AND discord_id=? AND filled=0",
            (order_id, discord_id),
        ).fetchone()
        if not row:
            return False
        con.execute("DELETE FROM orders WHERE id=?", (order_id,))
        # 매수 주문 취소 시 예약금 반환
        if row["order_type"] == "buy":
            con.execute(
                "UPDATE users SET cash = cash + ? WHERE discord_id=?",
                (row["price"] * row["qty"], discord_id),
            )
        return True


# ── 랭킹 ──

def get_all_users(season: int = 1) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM users WHERE season=? ORDER BY cash DESC", (season,)
        ).fetchall()
