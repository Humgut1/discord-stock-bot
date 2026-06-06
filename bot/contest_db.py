import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "game.db")

MARKETS = ["전체", "국내", "코스피", "코스닥", "미국"]

# 시장별 허용 종목코드 패턴
MARKET_FILTER = {
    "전체":   None,                         # 제한 없음
    "국내":   ["KR"],                        # currency=KRW
    "코스피": ["KOSPI"],
    "코스닥": ["KOSDAQ"],
    "미국":   ["NYSE", "NASDAQ", "AMEX"],
}


@contextmanager
def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_contest_tables():
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS contests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            guild_id        TEXT NOT NULL,
            category_id     TEXT,
            info_channel_id TEXT,
            trade_channel_id TEXT,
            fill_channel_id  TEXT,
            rank_channel_id  TEXT,
            init_cash       REAL NOT NULL DEFAULT 1000000,
            market          TEXT NOT NULL DEFAULT '전체',
            start_at        TEXT NOT NULL,
            end_at          TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'WAITING',
            created_by      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS contest_participants (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id  INTEGER NOT NULL,
            discord_id  TEXT NOT NULL,
            username    TEXT NOT NULL,
            cash        REAL NOT NULL,
            joined_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(contest_id, discord_id)
        );

        CREATE TABLE IF NOT EXISTS contest_holdings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id  INTEGER NOT NULL,
            discord_id  TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            name        TEXT NOT NULL,
            qty         INTEGER NOT NULL,
            avg_price   REAL NOT NULL,
            UNIQUE(contest_id, discord_id, symbol)
        );

        CREATE TABLE IF NOT EXISTS contest_orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id  INTEGER NOT NULL,
            discord_id  TEXT NOT NULL,
            username    TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            name        TEXT NOT NULL,
            order_type  TEXT NOT NULL,
            qty         INTEGER NOT NULL,
            price       REAL NOT NULL,
            filled      INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        """)


# ── 대회 ──

def create_contest(name, guild_id, init_cash, market, start_at, end_at, created_by) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO contests(name, guild_id, init_cash, market, start_at, end_at, created_by)
               VALUES(?,?,?,?,?,?,?)""",
            (name, guild_id, init_cash, market, start_at, end_at, created_by),
        )
        return cur.lastrowid


def set_contest_channels(contest_id, category_id, info_ch, trade_ch, fill_ch, rank_ch):
    with _conn() as con:
        con.execute(
            """UPDATE contests SET category_id=?, info_channel_id=?, trade_channel_id=?,
               fill_channel_id=?, rank_channel_id=? WHERE id=?""",
            (str(category_id), str(info_ch), str(trade_ch), str(fill_ch), str(rank_ch), contest_id),
        )


def get_contest(contest_id: int):
    with _conn() as con:
        return con.execute("SELECT * FROM contests WHERE id=?", (contest_id,)).fetchone()


def get_active_contests(guild_id: str) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM contests WHERE guild_id=? AND status IN ('WAITING','ACTIVE') ORDER BY id DESC",
            (guild_id,),
        ).fetchall()


def get_all_contests(guild_id: str) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM contests WHERE guild_id=? ORDER BY id DESC LIMIT 10",
            (guild_id,),
        ).fetchall()


def start_contest(contest_id: int):
    with _conn() as con:
        con.execute("UPDATE contests SET status='ACTIVE' WHERE id=?", (contest_id,))


def end_contest(contest_id: int):
    with _conn() as con:
        con.execute("UPDATE contests SET status='ENDED' WHERE id=?", (contest_id,))


# ── 참가자 ──

def join_contest(contest_id, discord_id, username, init_cash) -> bool:
    try:
        with _conn() as con:
            con.execute(
                """INSERT INTO contest_participants(contest_id, discord_id, username, cash)
                   VALUES(?,?,?,?)""",
                (contest_id, discord_id, username, init_cash),
            )
        return True
    except sqlite3.IntegrityError:
        return False  # 이미 참가


def get_participant(contest_id, discord_id):
    with _conn() as con:
        return con.execute(
            "SELECT * FROM contest_participants WHERE contest_id=? AND discord_id=?",
            (contest_id, discord_id),
        ).fetchone()


def get_all_participants(contest_id) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM contest_participants WHERE contest_id=?", (contest_id,)
        ).fetchall()


def update_cash(contest_id, discord_id, delta):
    with _conn() as con:
        con.execute(
            "UPDATE contest_participants SET cash = cash + ? WHERE contest_id=? AND discord_id=?",
            (delta, contest_id, discord_id),
        )


# ── 보유 종목 ──

def get_holdings(contest_id, discord_id) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM contest_holdings WHERE contest_id=? AND discord_id=?",
            (contest_id, discord_id),
        ).fetchall()


def upsert_holding(contest_id, discord_id, symbol, name, qty, avg_price):
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM contest_holdings WHERE contest_id=? AND discord_id=? AND symbol=?",
            (contest_id, discord_id, symbol),
        ).fetchone()
        if row:
            new_qty = row["qty"] + qty
            if new_qty <= 0:
                con.execute(
                    "DELETE FROM contest_holdings WHERE contest_id=? AND discord_id=? AND symbol=?",
                    (contest_id, discord_id, symbol),
                )
            else:
                new_avg = (row["avg_price"] * row["qty"] + avg_price * qty) / new_qty
                con.execute(
                    "UPDATE contest_holdings SET qty=?, avg_price=? WHERE contest_id=? AND discord_id=? AND symbol=?",
                    (new_qty, new_avg, contest_id, discord_id, symbol),
                )
        else:
            con.execute(
                "INSERT INTO contest_holdings(contest_id, discord_id, symbol, name, qty, avg_price) VALUES(?,?,?,?,?,?)",
                (contest_id, discord_id, symbol, name, qty, avg_price),
            )


def reduce_holding(contest_id, discord_id, symbol, qty):
    with _conn() as con:
        row = con.execute(
            "SELECT qty FROM contest_holdings WHERE contest_id=? AND discord_id=? AND symbol=?",
            (contest_id, discord_id, symbol),
        ).fetchone()
        if not row or row["qty"] < qty:
            raise ValueError("보유 수량 부족")
        new_qty = row["qty"] - qty
        if new_qty == 0:
            con.execute(
                "DELETE FROM contest_holdings WHERE contest_id=? AND discord_id=? AND symbol=?",
                (contest_id, discord_id, symbol),
            )
        else:
            con.execute(
                "UPDATE contest_holdings SET qty=? WHERE contest_id=? AND discord_id=? AND symbol=?",
                (new_qty, contest_id, discord_id, symbol),
            )


# ── 주문 ──

def create_order(contest_id, discord_id, username, symbol, name, order_type, qty, price) -> int:
    with _conn() as con:
        cur = con.execute(
            """INSERT INTO contest_orders(contest_id, discord_id, username, symbol, name, order_type, qty, price)
               VALUES(?,?,?,?,?,?,?,?)""",
            (contest_id, discord_id, username, symbol, name, order_type, qty, price),
        )
        return cur.lastrowid


def get_pending_orders(contest_id) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM contest_orders WHERE contest_id=? AND filled=0", (contest_id,)
        ).fetchall()


def get_user_pending_orders(contest_id, discord_id) -> list:
    with _conn() as con:
        return con.execute(
            "SELECT * FROM contest_orders WHERE contest_id=? AND discord_id=? AND filled=0",
            (contest_id, discord_id),
        ).fetchall()


def fill_order(order_id):
    with _conn() as con:
        con.execute("UPDATE contest_orders SET filled=1 WHERE id=?", (order_id,))


def cancel_order(order_id, discord_id) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM contest_orders WHERE id=? AND discord_id=? AND filled=0",
            (order_id, discord_id),
        ).fetchone()
        if not row:
            return None
        con.execute("DELETE FROM contest_orders WHERE id=?", (order_id,))
        if row["order_type"] == "buy":
            con.execute(
                "UPDATE contest_participants SET cash = cash + ? WHERE contest_id=? AND discord_id=?",
                (row["price"] * row["qty"], row["contest_id"], discord_id),
            )
        return dict(row)
