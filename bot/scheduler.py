import asyncio
import discord
from . import toss_api, database as db

SEASON = 1
POLL_INTERVAL = 180  # 3분


async def run(bot: discord.Client, fill_channel_id: int):
    """3분마다 미체결 주문을 체크해 체결 처리하고 알림을 보냄"""
    await bot.wait_until_ready()
    channel = bot.get_channel(fill_channel_id)

    while not bot.is_closed():
        try:
            await _check_orders(channel)
        except Exception as e:
            print(f"[scheduler] 오류: {e}")
        await asyncio.sleep(POLL_INTERVAL)


async def _check_orders(channel: discord.TextChannel | None):
    pending = db.get_pending_orders(SEASON)
    if not pending:
        return

    # 종목별로 묶어 API 호출 최소화
    symbols = list({o["symbol"] for o in pending})
    prices  = {}
    for sym in symbols:
        data = toss_api.get_price(sym)
        if data:
            prices[sym] = float(data.get("lastPrice", 0))

    for order in pending:
        sym = order["symbol"]
        cur = prices.get(sym)
        if cur is None:
            continue

        hit = (
            (order["order_type"] == "buy"  and cur <= order["price"]) or
            (order["order_type"] == "sell" and cur >= order["price"])
        )
        if not hit:
            continue

        # 체결 처리
        db.fill_order(order["id"])

        if order["order_type"] == "buy":
            db.upsert_holding(
                order["discord_id"], order["symbol"], order["name"],
                order["qty"], order["price"], SEASON,
            )
            # 예약금은 이미 차감됨 → 추가 처리 불필요
        else:
            db.update_cash(order["discord_id"], order["price"] * order["qty"])

        # 체결 알림
        if channel:
            embed = _fill_embed(order, cur)
            try:
                await channel.send(
                    content=f"<@{order['discord_id']}>",
                    embed=embed,
                )
            except Exception as e:
                print(f"[scheduler] 알림 전송 실패: {e}")


def _fill_embed(order, filled_price: float) -> discord.Embed:
    t_type  = "매수" if order["order_type"] == "buy" else "매도"
    color   = discord.Color.green() if order["order_type"] == "buy" else discord.Color.red()
    symbol  = "🟢" if order["order_type"] == "buy" else "🔴"
    total   = filled_price * order["qty"]

    embed = discord.Embed(title=f"{symbol} {t_type} 체결!", color=color)
    embed.add_field(name="종목",   value=order["name"],            inline=True)
    embed.add_field(name="수량",   value=f"{order['qty']}주",      inline=True)
    embed.add_field(name="체결가", value=f"{int(filled_price):,}원", inline=True)
    embed.add_field(name="체결금액", value=f"{int(total):,}원",    inline=True)
    embed.set_footer(text=f"주문번호 #{order['id']}")
    return embed
