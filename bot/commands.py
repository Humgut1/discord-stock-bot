import discord
from discord import app_commands
from discord.ext import commands

from . import toss_api, database as db, chart

SEASON = 1
INIT_CASH = 1_000_000


def fmt(n: float) -> str:
    return f"{int(n):,}"


def setup(bot: commands.Bot):
    tree = bot.tree

    # ────────────────────────────────────────────
    # /종목
    # ────────────────────────────────────────────
    @tree.command(name="종목", description="종목 현재가와 차트를 조회합니다")
    @app_commands.describe(이름="종목명 또는 종목코드 (예: 삼성전자, NVDA)")
    async def cmd_stock(interaction: discord.Interaction, 이름: str):
        await interaction.response.defer()

        symbol = toss_api.resolve_symbol(이름)
        price_data = toss_api.get_price(symbol)
        if not price_data:
            await interaction.followup.send(f"❌ **{이름}** 종목을 찾을 수 없어요.\n종목코드로 직접 입력해보세요 (예: `005930`, `AAPL`)")
            return

        stock_info = toss_api.get_stock_info(symbol)
        cur   = float(price_data.get("lastPrice", 0))
        name  = stock_info.get("name", 이름)
        unit  = "$" if price_data.get("currency") == "USD" else "원"
        color = discord.Color.blurple()

        candles = toss_api.get_candles(symbol, "1d", 30)
        chart_file = chart.make_chart(candles, f"{name} 30일 일봉") if candles else None

        embed = discord.Embed(title=f"📈 {name} ({symbol})", color=color)
        embed.add_field(name="현재가", value=f"**{fmt(cur)}{unit}**", inline=True)
        embed.add_field(name="시장",   value=stock_info.get("market", "-"), inline=True)
        embed.add_field(name="통화",   value=price_data.get("currency", "-"), inline=True)
        embed.set_footer(text="📡 토스증권 API · 3분 캐시")

        if chart_file:
            embed.set_image(url="attachment://chart.png")
            await interaction.followup.send(embed=embed, file=chart_file)
        else:
            await interaction.followup.send(embed=embed)

    # ────────────────────────────────────────────
    # /매수
    # ────────────────────────────────────────────
    @tree.command(name="매수", description="지정가 매수 주문을 등록합니다")
    @app_commands.describe(
        종목="종목명 또는 코드",
        수량="매수할 주 수",
        가격="주문 가격 (이 가격 이하로 떨어지면 체결)",
    )
    async def cmd_buy(interaction: discord.Interaction, 종목: str, 수량: int, 가격: float):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        db.ensure_user(str(user.id), user.display_name, SEASON)
        row = db.get_user(str(user.id))

        symbol = toss_api.resolve_symbol(종목)
        price_data = toss_api.get_price(symbol)
        if not price_data:
            await interaction.followup.send(f"❌ **{종목}** 종목을 찾을 수 없어요.", ephemeral=True)
            return

        stock_info = toss_api.get_stock_info(symbol)
        name = stock_info.get("name", 종목)
        total = 가격 * 수량
        unit  = "$" if price_data.get("currency") == "USD" else "원"

        if total > row["cash"]:
            await interaction.followup.send(
                f"❌ 잔고 부족\n필요: **{fmt(total)}원** / 보유: **{fmt(row['cash'])}원**",
                ephemeral=True,
            )
            return

        if 수량 <= 0 or 가격 <= 0:
            await interaction.followup.send("❌ 수량과 가격은 0보다 커야 해요.", ephemeral=True)
            return

        # 주문 금액 선차감 (예약)
        db.update_cash(str(user.id), -total)
        order_id = db.create_order(str(user.id), user.display_name, symbol, name, "buy", 수량, 가격, SEASON)

        cur = float(price_data.get("lastPrice", 0))
        embed = discord.Embed(title="⏳ 매수 주문 접수", color=discord.Color.green())
        embed.add_field(name="종목",   value=name, inline=True)
        embed.add_field(name="수량",   value=f"{수량}주", inline=True)
        embed.add_field(name="주문가", value=f"{fmt(가격)}{unit}", inline=True)
        embed.add_field(name="현재가", value=f"{fmt(cur)}{unit}", inline=True)
        embed.add_field(name="총금액", value=f"{fmt(total)}원 예약", inline=True)
        embed.set_footer(text=f"주문번호 #{order_id} · 현재가 ≤ {fmt(가격)}{unit} 되면 체결")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ────────────────────────────────────────────
    # /매도
    # ────────────────────────────────────────────
    @tree.command(name="매도", description="지정가 매도 주문을 등록합니다")
    @app_commands.describe(
        종목="종목명 또는 코드",
        수량="매도할 주 수",
        가격="주문 가격 (이 가격 이상이 되면 체결)",
    )
    async def cmd_sell(interaction: discord.Interaction, 종목: str, 수량: int, 가격: float):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        db.ensure_user(str(user.id), user.display_name, SEASON)

        symbol = toss_api.resolve_symbol(종목)
        price_data = toss_api.get_price(symbol)
        if not price_data:
            await interaction.followup.send(f"❌ **{종목}** 종목을 찾을 수 없어요.", ephemeral=True)
            return

        stock_info = toss_api.get_stock_info(symbol)
        name = stock_info.get("name", 종목)
        holdings = {h["symbol"]: h for h in db.get_holdings(str(user.id), SEASON)}
        holding  = holdings.get(symbol)
        unit     = "$" if price_data.get("currency") == "USD" else "원"

        if not holding or holding["qty"] < 수량:
            have = holding["qty"] if holding else 0
            await interaction.followup.send(
                f"❌ 보유 수량 부족\n보유: **{have}주** / 매도 시도: **{수량}주**",
                ephemeral=True,
            )
            return

        # 보유 수량 선차감 (예약)
        db.reduce_holding(str(user.id), symbol, 수량, SEASON)
        order_id = db.create_order(str(user.id), user.display_name, symbol, name, "sell", 수량, 가격, SEASON)

        cur = float(price_data.get("lastPrice", 0))
        embed = discord.Embed(title="⏳ 매도 주문 접수", color=discord.Color.red())
        embed.add_field(name="종목",   value=name, inline=True)
        embed.add_field(name="수량",   value=f"{수량}주", inline=True)
        embed.add_field(name="주문가", value=f"{fmt(가격)}{unit}", inline=True)
        embed.add_field(name="현재가", value=f"{fmt(cur)}{unit}", inline=True)
        embed.set_footer(text=f"주문번호 #{order_id} · 현재가 ≥ {fmt(가격)}{unit} 되면 체결")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ────────────────────────────────────────────
    # /잔고
    # ────────────────────────────────────────────
    @tree.command(name="잔고", description="내 포트폴리오와 평가손익을 조회합니다")
    async def cmd_balance(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        db.ensure_user(str(user.id), user.display_name, SEASON)
        row      = db.get_user(str(user.id))
        holdings = db.get_holdings(str(user.id), SEASON)

        eval_total = row["cash"]
        embed = discord.Embed(title=f"💼 {user.display_name}의 포트폴리오", color=discord.Color.blurple())

        if holdings:
            for h in holdings:
                price_data = toss_api.get_price(h["symbol"])
                cur = float(price_data.get("lastPrice", h["avg_price"])) if price_data else h["avg_price"]
                pnl = (cur - h["avg_price"]) * h["qty"]
                pct = (cur - h["avg_price"]) / h["avg_price"] * 100
                eval_total += cur * h["qty"]
                sign = "▲" if pnl >= 0 else "▼"
                embed.add_field(
                    name=f"{h['name']} ({h['qty']}주)",
                    value=f"평균 {fmt(h['avg_price'])}원\n{sign} {fmt(abs(pnl))}원 ({pct:+.2f}%)",
                    inline=True,
                )
        else:
            embed.description = "보유 종목 없음"

        total_pnl = eval_total - INIT_CASH
        sign = "▲" if total_pnl >= 0 else "▼"
        embed.add_field(name="​", value="​", inline=False)
        embed.add_field(name="현금",       value=f"{fmt(row['cash'])}원", inline=True)
        embed.add_field(name="총 평가금액", value=f"{fmt(eval_total)}원", inline=True)
        embed.add_field(name="총 손익",    value=f"{sign} {fmt(abs(total_pnl))}원 ({total_pnl/INIT_CASH*100:+.2f}%)", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ────────────────────────────────────────────
    # /주문대기
    # ────────────────────────────────────────────
    @tree.command(name="주문대기", description="미체결 주문 목록을 조회합니다")
    async def cmd_pending(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        db.ensure_user(str(user.id), user.display_name, SEASON)
        orders = db.get_user_pending_orders(str(user.id), SEASON)

        embed = discord.Embed(title="📋 미체결 주문", color=discord.Color.og_blurple())
        if not orders:
            embed.description = "대기 중인 주문이 없어요."
        else:
            for o in orders:
                t = "🟢 매수" if o["order_type"] == "buy" else "🔴 매도"
                embed.add_field(
                    name=f"#{o['id']} {t} {o['name']}",
                    value=f"{o['qty']}주 @ {fmt(o['price'])}원\n_{o['created_at']}_",
                    inline=False,
                )
            embed.set_footer(text="/주문취소 [번호] 로 취소 가능")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ────────────────────────────────────────────
    # /주문취소
    # ────────────────────────────────────────────
    @tree.command(name="주문취소", description="미체결 주문을 취소합니다")
    @app_commands.describe(번호="취소할 주문번호 (/주문대기 에서 확인)")
    async def cmd_cancel(interaction: discord.Interaction, 번호: int):
        await interaction.response.defer(ephemeral=True)
        success = db.cancel_order(번호, str(interaction.user.id))
        if success:
            await interaction.followup.send(f"✅ 주문 **#{번호}** 취소 완료 (예약금 반환됨)", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ 주문 **#{번호}**을 찾을 수 없거나 이미 체결된 주문이에요.", ephemeral=True)

