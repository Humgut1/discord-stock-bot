import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from typing import Literal

from . import toss_api, chart
from . import contest_db as cdb

MARKET_CHOICES = [
    app_commands.Choice(name="전체 (제한없음)", value="전체"),
    app_commands.Choice(name="국내 (코스피+코스닥)", value="국내"),
    app_commands.Choice(name="코스피", value="코스피"),
    app_commands.Choice(name="코스닥", value="코스닥"),
    app_commands.Choice(name="미국 (나스닥+NYSE)", value="미국"),
]

PERIOD_CHOICES = [
    app_commands.Choice(name="1일", value=1),
    app_commands.Choice(name="3일", value=3),
    app_commands.Choice(name="1주일", value=7),
    app_commands.Choice(name="2주일", value=14),
    app_commands.Choice(name="1달", value=30),
]

CASH_CHOICES = [
    app_commands.Choice(name="100만원",   value=1_000_000),
    app_commands.Choice(name="1000만원",  value=10_000_000),
    app_commands.Choice(name="1억원",     value=100_000_000),
]


def fmt(n: float) -> str:
    return f"{int(n):,}"


def _bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, int((pct + 30) / 60 * width)))
    return "█" * filled + "░" * (width - filled)


def _check_market(symbol: str, market: str, stock_info: dict) -> bool:
    """해당 종목이 설정된 시장에 속하는지 확인"""
    if market == "전체":
        return True
    stock_market = stock_info.get("market", "")
    currency     = stock_info.get("currency", "")
    if market == "국내":
        return currency == "KRW"
    if market == "미국":
        return currency == "USD"
    if market == "코스피":
        return stock_market == "KOSPI"
    if market == "코스닥":
        return stock_market == "KOSDAQ"
    return False


def _cur_to_krw(price: float, currency: str) -> float:
    """가격을 원화로 환산 (USD면 환율 적용)"""
    if currency == "USD":
        return price * toss_api.get_exchange_rate()
    return price


async def _calc_scores(contest_id: int) -> list[tuple]:
    """(username, discord_id, total_eval_krw, pnl, pct) 리스트, 수익률 내림차순"""
    contest      = cdb.get_contest(contest_id)
    init_cash    = contest["init_cash"]
    participants = cdb.get_all_participants(contest_id)

    scores = []
    for p in participants:
        holdings   = cdb.get_holdings(contest_id, p["discord_id"])
        eval_total = p["cash"]
        for h in holdings:
            price_data = toss_api.get_price(h["symbol"])
            if price_data:
                cur_raw  = float(price_data.get("lastPrice", h["avg_price"]))
                currency = price_data.get("currency", "KRW")
                cur_krw  = _cur_to_krw(cur_raw, currency)
            else:
                cur_krw = h["avg_price"]   # avg_price는 이미 원화로 저장
            eval_total += cur_krw * h["qty"]
        pnl = eval_total - init_cash
        pct = pnl / init_cash * 100
        scores.append((p["username"], p["discord_id"], eval_total, pnl, pct))

    scores.sort(key=lambda x: x[3], reverse=True)
    return scores


def _rank_embed(contest, scores: list, invoker_id: str | None = None) -> discord.Embed:
    now      = datetime.now()
    end_at   = datetime.fromisoformat(contest["end_at"])
    days_left = max(0, (end_at - now).days)

    status_str = {
        "WAITING": "대기 중",
        "ACTIVE":  "진행 중",
        "ENDED":   "종료",
    }.get(contest["status"], contest["status"])

    embed = discord.Embed(
        title=f"🏆 {contest['name']} 랭킹",
        description=f"**{status_str}** · D-{days_left} · 참가자 {len(scores)}명 · 시장: {contest['market']}",
        color=discord.Color.gold(),
    )

    medals = ["🥇", "🥈", "🥉"]
    for i, (uname, uid, total, pnl, pct) in enumerate(scores):
        medal  = medals[i] if i < 3 else f"`{i+1}.`"
        me_tag = " ← 나" if uid == invoker_id else ""
        sign   = "▲" if pnl >= 0 else "▼"
        cls    = "+" if pnl >= 0 else ""
        bar    = _bar(pct)
        embed.add_field(
            name=f"{medal} {uname}{me_tag}",
            value=f"{sign} {fmt(abs(pnl))}원 ({cls}{pct:.2f}%)  {bar}\n총평가 {fmt(total)}원",
            inline=False,
        )

    embed.set_footer(text=f"기준 자본금 {fmt(contest['init_cash'])}원 · 3분 캐시")
    return embed


def setup(bot: commands.Bot):
    tree = bot.tree

    # ─────────────────────────────────────────
    # /대회생성
    # ─────────────────────────────────────────
    @tree.command(name="대회생성", description="모의투자 대회를 생성합니다 (관리자 전용)")
    @app_commands.describe(
        이름="대회 이름",
        자본금="초기 자본금",
        기간="대회 기간 (일)",
        시장="거래 가능 시장",
    )
    @app_commands.choices(자본금=CASH_CHOICES, 기간=PERIOD_CHOICES, 시장=MARKET_CHOICES)
    @app_commands.default_permissions(manage_channels=True)
    async def cmd_create(
        interaction: discord.Interaction,
        이름: str,
        자본금: app_commands.Choice[int],
        기간: app_commands.Choice[int],
        시장: app_commands.Choice[str],
    ):
        await interaction.response.defer()

        now      = datetime.now()
        end_at   = now + timedelta(days=기간.value)
        guild    = interaction.guild

        # DB 생성
        contest_id = cdb.create_contest(
            name=이름,
            guild_id=str(guild.id),
            init_cash=자본금.value,
            market=시장.value,
            start_at=now.isoformat(),
            end_at=end_at.isoformat(),
            created_by=str(interaction.user.id),
        )
        cdb.start_contest(contest_id)

        # 카테고리 + 채널 자동 생성
        category = await guild.create_category(f"📈 {이름}")
        info_ch  = await guild.create_text_channel("대회-정보",   category=category)
        trade_ch = await guild.create_text_channel("매수-매도",   category=category)
        fill_ch  = await guild.create_text_channel("체결-알림",   category=category)
        rank_ch  = await guild.create_text_channel("실시간-랭킹", category=category)

        cdb.set_contest_channels(contest_id, category.id, info_ch.id, trade_ch.id, fill_ch.id, rank_ch.id)

        # #대회-정보 채널에 공지 게시
        info_embed = discord.Embed(
            title=f"🏁 {이름} 대회 시작!",
            color=discord.Color.green(),
        )
        info_embed.add_field(name="자본금",   value=f"{fmt(자본금.value)}원", inline=True)
        info_embed.add_field(name="기간",     value=f"{기간.name}", inline=True)
        info_embed.add_field(name="시장",     value=시장.value, inline=True)
        info_embed.add_field(name="시작",     value=now.strftime("%Y-%m-%d %H:%M"), inline=True)
        info_embed.add_field(name="종료",     value=end_at.strftime("%Y-%m-%d %H:%M"), inline=True)
        info_embed.add_field(name="대회 ID",  value=f"`{contest_id}`", inline=True)
        info_embed.add_field(
            name="참가 방법",
            value=f"`/대회참가 {contest_id}` 를 입력하세요\n매수·매도는 {trade_ch.mention} 채널에서!",
            inline=False,
        )
        await info_ch.send(embed=info_embed)

        await interaction.followup.send(
            f"✅ **{이름}** 대회가 생성됐어요!\n"
            f"카테고리 **📈 {이름}** 을 확인하고 {info_ch.mention} 에서 참가 안내를 확인하세요.\n"
            f"참가 명령어: `/대회참가 {contest_id}`"
        )

    # ─────────────────────────────────────────
    # /대회참가
    # ─────────────────────────────────────────
    @tree.command(name="대회참가", description="대회에 참가합니다")
    @app_commands.describe(대회id="대회 ID (/대회목록 에서 확인)")
    async def cmd_join(interaction: discord.Interaction, 대회id: int):
        await interaction.response.defer(ephemeral=True)
        contest = cdb.get_contest(대회id)
        if not contest:
            await interaction.followup.send("❌ 대회를 찾을 수 없어요.", ephemeral=True)
            return
        if contest["status"] == "ENDED":
            await interaction.followup.send("❌ 이미 종료된 대회예요.", ephemeral=True)
            return
        if str(contest["guild_id"]) != str(interaction.guild_id):
            await interaction.followup.send("❌ 이 서버의 대회가 아니에요.", ephemeral=True)
            return

        ok = cdb.join_contest(대회id, str(interaction.user.id), interaction.user.display_name, contest["init_cash"])
        if not ok:
            await interaction.followup.send("이미 참가 중인 대회예요.", ephemeral=True)
            return

        trade_ch = interaction.guild.get_channel(int(contest["trade_channel_id"])) if contest["trade_channel_id"] else None
        embed = discord.Embed(title="🎉 대회 참가 완료!", color=discord.Color.green())
        embed.add_field(name="대회",   value=contest["name"], inline=True)
        embed.add_field(name="자본금", value=f"{fmt(contest['init_cash'])}원", inline=True)
        embed.add_field(name="시장",   value=contest["market"], inline=True)
        if trade_ch:
            embed.add_field(name="매수/매도", value=f"{trade_ch.mention} 에서 주문하세요", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

        # 공개 알림
        if trade_ch:
            await trade_ch.send(f"👋 **{interaction.user.display_name}**님이 대회에 참가했어요!")

    # ─────────────────────────────────────────
    # /대회목록
    # ─────────────────────────────────────────
    @tree.command(name="대회목록", description="현재 서버의 대회 목록을 조회합니다")
    async def cmd_list(interaction: discord.Interaction):
        await interaction.response.defer()
        contests = cdb.get_all_contests(str(interaction.guild_id))
        if not contests:
            await interaction.followup.send("현재 진행 중인 대회가 없어요.")
            return

        embed = discord.Embed(title="📋 대회 목록", color=discord.Color.blurple())
        status_emoji = {"WAITING": "⏳", "ACTIVE": "🟢", "ENDED": "🔴"}
        for c in contests:
            end_at    = datetime.fromisoformat(c["end_at"])
            days_left = max(0, (end_at - datetime.now()).days)
            emoji     = status_emoji.get(c["status"], "❓")
            participants = len(cdb.get_all_participants(c["id"]))
            embed.add_field(
                name=f"{emoji} [{c['id']}] {c['name']}",
                value=f"자본금 {fmt(c['init_cash'])}원 · {c['market']} · D-{days_left} · {participants}명 참가",
                inline=False,
            )
        embed.set_footer(text="/대회참가 [ID] 로 참가하세요")
        await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────
    # /대회정보
    # ─────────────────────────────────────────
    @tree.command(name="대회정보", description="대회 상세 정보를 조회합니다")
    @app_commands.describe(대회id="대회 ID")
    async def cmd_info(interaction: discord.Interaction, 대회id: int):
        await interaction.response.defer()
        contest = cdb.get_contest(대회id)
        if not contest:
            await interaction.followup.send("❌ 대회를 찾을 수 없어요.")
            return

        participants = cdb.get_all_participants(대회id)
        end_at       = datetime.fromisoformat(contest["end_at"])
        days_left    = max(0, (end_at - datetime.now()).days)

        embed = discord.Embed(title=f"📋 {contest['name']}", color=discord.Color.blurple())
        embed.add_field(name="자본금",   value=f"{fmt(contest['init_cash'])}원", inline=True)
        embed.add_field(name="시장",     value=contest["market"], inline=True)
        embed.add_field(name="참가자",   value=f"{len(participants)}명", inline=True)
        embed.add_field(name="종료까지", value=f"D-{days_left}", inline=True)
        embed.add_field(name="종료일",   value=end_at.strftime("%Y-%m-%d %H:%M"), inline=True)

        names = ", ".join(p["username"] for p in participants) or "없음"
        embed.add_field(name="참가자 목록", value=names, inline=False)
        await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────
    # /랭킹
    # ─────────────────────────────────────────
    @tree.command(name="랭킹", description="대회 실시간 수익률 랭킹을 조회합니다")
    @app_commands.describe(대회id="대회 ID")
    async def cmd_ranking(interaction: discord.Interaction, 대회id: int):
        await interaction.response.defer()
        contest = cdb.get_contest(대회id)
        if not contest:
            await interaction.followup.send("❌ 대회를 찾을 수 없어요.")
            return

        scores = await _calc_scores(대회id)
        if not scores:
            await interaction.followup.send("아직 참가자가 없어요. `/대회참가`로 먼저 등록하세요!")
            return

        embed = _rank_embed(contest, scores, str(interaction.user.id))
        await interaction.followup.send(embed=embed)

    # ─────────────────────────────────────────
    # /대회매수
    # ─────────────────────────────────────────
    @tree.command(name="대회매수", description="대회에서 지정가 매수 주문을 등록합니다")
    @app_commands.describe(
        대회id="대회 ID",
        종목="종목명 또는 코드",
        수량="매수할 주 수",
        가격="주문 가격",
    )
    async def cmd_buy(interaction: discord.Interaction, 대회id: int, 종목: str, 수량: int, 가격: float):
        await interaction.response.defer(ephemeral=True)
        contest = cdb.get_contest(대회id)
        if not contest or contest["status"] != "ACTIVE":
            await interaction.followup.send("❌ 진행 중인 대회가 아니에요.", ephemeral=True)
            return

        participant = cdb.get_participant(대회id, str(interaction.user.id))
        if not participant:
            await interaction.followup.send(f"❌ 대회에 먼저 참가해주세요. `/대회참가 {대회id}`", ephemeral=True)
            return

        symbol     = toss_api.resolve_symbol(종목)
        price_data = toss_api.get_price(symbol)
        stock_info = toss_api.get_stock_info(symbol)

        if not price_data:
            await interaction.followup.send(f"❌ **{종목}** 종목을 찾을 수 없어요.", ephemeral=True)
            return

        if not _check_market(symbol, contest["market"], stock_info):
            await interaction.followup.send(
                f"❌ **{symbol}** 은 이 대회의 허용 시장({contest['market']})에 속하지 않아요.", ephemeral=True
            )
            return

        currency  = price_data.get("currency", "KRW")
        is_usd    = currency == "USD"
        unit      = "$" if is_usd else "원"
        name      = stock_info.get("name", 종목)

        # 주문가 원화 환산
        rate      = toss_api.get_exchange_rate() if is_usd else 1.0
        가격_krw  = 가격 * rate
        total_krw = 가격_krw * 수량

        if total_krw > participant["cash"]:
            rate_str = f" (환율 {fmt(rate)}원/달러)" if is_usd else ""
            await interaction.followup.send(
                f"❌ 잔고 부족\n"
                f"필요: **{fmt(total_krw)}원** ({fmt(가격)}{unit} × {수량}주{rate_str})\n"
                f"보유: **{fmt(participant['cash'])}원**",
                ephemeral=True,
            )
            return

        # 주문은 원화 기준 avg_price 로 저장 (잔고 계산 일원화)
        cdb.update_cash(대회id, str(interaction.user.id), -total_krw)
        order_id = cdb.create_order(
            대회id, str(interaction.user.id), interaction.user.display_name,
            symbol, name, "buy", 수량, 가격_krw,   # DB엔 원화 가격 저장
        )

        cur_raw  = float(price_data.get("lastPrice", 0))
        cur_krw  = cur_raw * rate
        imm      = cur_raw <= 가격   # 비교는 원래 통화로
        if imm:
            cdb.fill_order(order_id)
            cdb.upsert_holding(대회id, str(interaction.user.id), symbol, name, 수량, 가격_krw)

        rate_info = f" (환율 {fmt(rate)}원/$)" if is_usd else ""
        embed = discord.Embed(
            title="✅ 즉시 체결!" if imm else "⏳ 매수 주문 접수",
            color=discord.Color.green(),
        )
        embed.add_field(name="종목",       value=name, inline=True)
        embed.add_field(name="수량",       value=f"{수량}주", inline=True)
        embed.add_field(name="주문가",     value=f"{fmt(가격)}{unit}", inline=True)
        embed.add_field(name="현재가",     value=f"{fmt(cur_raw)}{unit}", inline=True)
        embed.add_field(name="원화 환산",  value=f"≈ {fmt(total_krw)}원{rate_info}", inline=True)
        embed.set_footer(text=f"주문번호 #{order_id} · 잔여 {fmt(participant['cash'] - total_krw)}원")
        await interaction.followup.send(embed=embed, ephemeral=True)

        # 체결 알림 채널 공개
        fill_ch = interaction.guild.get_channel(int(contest["fill_channel_id"])) if contest["fill_channel_id"] else None
        if fill_ch and imm:
            await fill_ch.send(
                f"🟢 **{interaction.user.display_name}**님 · **{name}** {수량}주 매수 체결 @ {fmt(가격)}{unit}"
            )

    # ─────────────────────────────────────────
    # /대회매도
    # ─────────────────────────────────────────
    @tree.command(name="대회매도", description="대회에서 지정가 매도 주문을 등록합니다")
    @app_commands.describe(
        대회id="대회 ID",
        종목="종목명 또는 코드",
        수량="매도할 주 수",
        가격="주문 가격",
    )
    async def cmd_sell(interaction: discord.Interaction, 대회id: int, 종목: str, 수량: int, 가격: float):
        await interaction.response.defer(ephemeral=True)
        contest = cdb.get_contest(대회id)
        if not contest or contest["status"] != "ACTIVE":
            await interaction.followup.send("❌ 진행 중인 대회가 아니에요.", ephemeral=True)
            return

        participant = cdb.get_participant(대회id, str(interaction.user.id))
        if not participant:
            await interaction.followup.send(f"❌ 대회에 먼저 참가해주세요. `/대회참가 {대회id}`", ephemeral=True)
            return

        symbol     = toss_api.resolve_symbol(종목)
        price_data = toss_api.get_price(symbol)
        stock_info = toss_api.get_stock_info(symbol)

        if not price_data:
            await interaction.followup.send(f"❌ **{종목}** 종목을 찾을 수 없어요.", ephemeral=True)
            return

        currency  = price_data.get("currency", "KRW")
        is_usd    = currency == "USD"
        unit      = "$" if is_usd else "원"
        name      = stock_info.get("name", 종목)
        rate      = toss_api.get_exchange_rate() if is_usd else 1.0

        holdings = {h["symbol"]: h for h in cdb.get_holdings(대회id, str(interaction.user.id))}
        holding  = holdings.get(symbol)

        if not holding or holding["qty"] < 수량:
            have = holding["qty"] if holding else 0
            await interaction.followup.send(
                f"❌ 보유 수량 부족\n보유: **{have}주** / 매도 시도: **{수량}주**", ephemeral=True
            )
            return

        가격_krw  = 가격 * rate
        total_krw = 가격_krw * 수량

        cdb.reduce_holding(대회id, str(interaction.user.id), symbol, 수량)
        order_id = cdb.create_order(
            대회id, str(interaction.user.id), interaction.user.display_name,
            symbol, name, "sell", 수량, 가격_krw,  # DB엔 원화 가격 저장
        )

        cur_raw = float(price_data.get("lastPrice", 0))
        imm     = cur_raw >= 가격
        if imm:
            cdb.fill_order(order_id)
            cdb.update_cash(대회id, str(interaction.user.id), total_krw)

        # 손익 계산 (avg_price는 원화로 저장돼 있음)
        pnl_krw = (가격_krw - holding["avg_price"]) * 수량

        embed = discord.Embed(
            title="✅ 즉시 체결!" if imm else "⏳ 매도 주문 접수",
            color=discord.Color.red(),
        )
        embed.add_field(name="종목",      value=name, inline=True)
        embed.add_field(name="수량",      value=f"{수량}주", inline=True)
        embed.add_field(name="주문가",    value=f"{fmt(가격)}{unit}", inline=True)
        embed.add_field(name="현재가",    value=f"{fmt(cur_raw)}{unit}", inline=True)
        embed.add_field(name="원화 환산", value=f"≈ {fmt(total_krw)}원", inline=True)
        if imm:
            sign = "+" if pnl_krw >= 0 else ""
            embed.add_field(name="실현 손익", value=f"{sign}{fmt(pnl_krw)}원", inline=True)
        embed.set_footer(text=f"주문번호 #{order_id}")
        await interaction.followup.send(embed=embed, ephemeral=True)

        fill_ch = interaction.guild.get_channel(int(contest["fill_channel_id"])) if contest["fill_channel_id"] else None
        if fill_ch and imm:
            sign = "+" if pnl_krw >= 0 else ""
            await fill_ch.send(
                f"🔴 **{interaction.user.display_name}**님 · **{name}** {수량}주 매도 체결 @ {fmt(가격)}{unit} "
                f"({sign}{fmt(pnl)}원)"
            )

    # ─────────────────────────────────────────
    # /내잔고
    # ─────────────────────────────────────────
    @tree.command(name="내잔고", description="대회 내 내 포트폴리오를 조회합니다")
    @app_commands.describe(대회id="대회 ID")
    async def cmd_mybalance(interaction: discord.Interaction, 대회id: int):
        await interaction.response.defer(ephemeral=True)
        contest     = cdb.get_contest(대회id)
        participant = cdb.get_participant(대회id, str(interaction.user.id))
        if not participant:
            await interaction.followup.send(f"❌ 이 대회에 참가하지 않았어요. `/대회참가 {대회id}`", ephemeral=True)
            return

        holdings   = cdb.get_holdings(대회id, str(interaction.user.id))
        eval_total = participant["cash"]
        embed      = discord.Embed(
            title=f"💼 {interaction.user.display_name}의 포트폴리오 · {contest['name']}",
            color=discord.Color.blurple(),
        )

        for h in holdings:
            price_data = toss_api.get_price(h["symbol"])
            if price_data:
                cur_raw  = float(price_data.get("lastPrice", h["avg_price"]))
                currency = price_data.get("currency", "KRW")
                cur_krw  = _cur_to_krw(cur_raw, currency)
                unit     = "$" if currency == "USD" else "원"
            else:
                cur_krw = h["avg_price"]
                cur_raw = h["avg_price"]
                unit    = "원"
            # avg_price는 원화로 저장돼 있으므로 바로 비교
            pnl = (cur_krw - h["avg_price"]) * h["qty"]
            pct = (cur_krw - h["avg_price"]) / h["avg_price"] * 100 if h["avg_price"] else 0
            eval_total += cur_krw * h["qty"]
            sign = "▲" if pnl >= 0 else "▼"
            embed.add_field(
                name=f"{h['name']} ({h['qty']}주)",
                value=f"현재 {fmt(cur_raw)}{unit} · 평균 {fmt(h['avg_price'])}원\n{sign} {fmt(abs(pnl))}원 ({pct:+.2f}%)",
                inline=True,
            )

        total_pnl = eval_total - contest["init_cash"]
        sign      = "▲" if total_pnl >= 0 else "▼"
        embed.add_field(name="​", value="​", inline=False)
        embed.add_field(name="현금",        value=f"{fmt(participant['cash'])}원", inline=True)
        embed.add_field(name="총 평가금액", value=f"{fmt(eval_total)}원", inline=True)
        embed.add_field(name="총 손익",     value=f"{sign} {fmt(abs(total_pnl))}원 ({total_pnl/contest['init_cash']*100:+.2f}%)", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────
    # /주문대기
    # ─────────────────────────────────────────
    @tree.command(name="대회주문대기", description="대회 미체결 주문을 조회합니다")
    @app_commands.describe(대회id="대회 ID")
    async def cmd_pending(interaction: discord.Interaction, 대회id: int):
        await interaction.response.defer(ephemeral=True)
        orders = cdb.get_user_pending_orders(대회id, str(interaction.user.id))
        embed  = discord.Embed(title="📋 미체결 주문", color=discord.Color.blurple())
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
            embed.set_footer(text="/대회주문취소 [번호] 로 취소")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────
    # /대회주문취소
    # ─────────────────────────────────────────
    @tree.command(name="대회주문취소", description="대회 미체결 주문을 취소합니다")
    @app_commands.describe(주문번호="취소할 주문번호")
    async def cmd_cancel(interaction: discord.Interaction, 주문번호: int):
        await interaction.response.defer(ephemeral=True)
        row = cdb.cancel_order(주문번호, str(interaction.user.id))
        if row:
            await interaction.followup.send(f"✅ 주문 **#{주문번호}** 취소 완료 (예약금 반환됨)", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ 주문 **#{주문번호}**을 찾을 수 없거나 이미 체결된 주문이에요.", ephemeral=True)
