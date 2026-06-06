import asyncio
from datetime import datetime
import discord

from . import toss_api
from . import contest_db as cdb
from .contest_commands import _calc_scores, _rank_embed

POLL_INTERVAL = 180  # 3분


async def run(bot: discord.Client):
    """3분마다 미체결 주문 체크 + 매일 9시 랭킹 공지 + 대회 종료 처리"""
    await bot.wait_until_ready()
    last_daily = None

    while not bot.is_closed():
        try:
            now = datetime.now()

            # 매일 오전 9시 랭킹 자동 공지
            if now.hour == 9 and now.minute < 3:
                today = now.date()
                if last_daily != today:
                    last_daily = today
                    await _post_daily_rankings(bot)

            await _check_all_orders(bot)
            await _check_ended_contests(bot)

        except Exception as e:
            print(f"[contest_scheduler] 오류: {e}")

        await asyncio.sleep(POLL_INTERVAL)


async def _check_all_orders(bot: discord.Client):
    """모든 진행 중 대회의 미체결 주문 체결 체크"""
    from .database import init_db
    import sqlite3, os
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "game.db")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    active = con.execute("SELECT * FROM contests WHERE status='ACTIVE'").fetchall()
    con.close()

    for contest in active:
        pending = cdb.get_pending_orders(contest["id"])
        if not pending:
            continue

        # 종목별로 묶어 API 호출 최소화
        symbols = list({o["symbol"] for o in pending})
        prices  = {}
        for sym in symbols:
            data = toss_api.get_price(sym)
            if data:
                prices[sym] = float(data.get("lastPrice", 0))

        guild    = bot.get_guild(int(contest["guild_id"]))
        fill_ch  = guild.get_channel(int(contest["fill_channel_id"])) if guild and contest["fill_channel_id"] else None

        for order in pending:
            cur = prices.get(order["symbol"])
            if not cur:
                continue

            hit = (
                (order["order_type"] == "buy"  and cur <= order["price"]) or
                (order["order_type"] == "sell" and cur >= order["price"])
            )
            if not hit:
                continue

            cdb.fill_order(order["id"])

            if order["order_type"] == "buy":
                cdb.upsert_holding(
                    order["contest_id"], order["discord_id"],
                    order["symbol"], order["name"],
                    order["qty"], order["price"],
                )
            else:
                cdb.update_cash(order["contest_id"], order["discord_id"], order["price"] * order["qty"])

            if fill_ch:
                t    = "🟢 매수" if order["order_type"] == "buy" else "🔴 매도"
                unit = "원"
                await fill_ch.send(
                    f"{t} 체결! **{order['username']}**님 · **{order['name']}** "
                    f"{order['qty']}주 @ {int(order['price']):,}{unit}"
                )


async def _post_daily_rankings(bot: discord.Client):
    """매일 9시 모든 진행 중 대회 랭킹을 rank 채널에 자동 게시"""
    import sqlite3, os
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "game.db")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    active = con.execute("SELECT * FROM contests WHERE status='ACTIVE'").fetchall()
    con.close()

    for contest in active:
        guild   = bot.get_guild(int(contest["guild_id"]))
        rank_ch = guild.get_channel(int(contest["rank_channel_id"])) if guild and contest["rank_channel_id"] else None
        if not rank_ch:
            continue

        scores = await _calc_scores(contest["id"])
        if not scores:
            continue

        embed = _rank_embed(contest, scores)
        embed.title = f"📅 {datetime.now().strftime('%m/%d')} 일일 랭킹 · {contest['name']}"
        await rank_ch.send(embed=embed)


async def _check_ended_contests(bot: discord.Client):
    """종료 시간이 지난 대회 자동 종료 처리"""
    import sqlite3, os
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "game.db")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    active = con.execute("SELECT * FROM contests WHERE status='ACTIVE'").fetchall()
    con.close()

    for contest in active:
        end_at = datetime.fromisoformat(contest["end_at"])
        if datetime.now() < end_at:
            continue

        cdb.end_contest(contest["id"])

        guild   = bot.get_guild(int(contest["guild_id"]))
        rank_ch = guild.get_channel(int(contest["rank_channel_id"])) if guild and contest["rank_channel_id"] else None
        if not rank_ch:
            continue

        scores = await _calc_scores(contest["id"])
        embed  = _rank_embed(contest, scores)
        embed.title  = f"🏁 {contest['name']} 최종 결과!"
        embed.color  = discord.Color.gold()

        medals = ["🥇", "🥈", "🥉"]
        if scores:
            winner = scores[0]
            embed.description = (
                f"🎉 우승자: **{winner[0]}**\n"
                f"수익: **{'+' if winner[3] >= 0 else ''}{int(winner[3]):,}원** ({winner[4]:+.2f}%)"
            )

        await rank_ch.send("@everyone", embed=embed)
