import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

from bot import database as db
from bot import contest_db
from bot.commands import setup
from bot.contest_commands import setup as contest_setup
from bot import scheduler, contest_scheduler

load_dotenv()

DISCORD_TOKEN   = os.environ["DISCORD_TOKEN"]
FILL_CHANNEL_ID = int(os.environ.get("FILL_CHANNEL_ID", "0"))


class StockBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True          # 채널 생성에 필요
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        db.init_db()
        contest_db.init_contest_tables()
        setup(self)
        contest_setup(self)
        await self.tree.sync()
        print("[봇] 슬래시 커맨드 동기화 완료")
        self.loop.create_task(scheduler.run(self, FILL_CHANNEL_ID))
        self.loop.create_task(contest_scheduler.run(self))

    async def on_ready(self):
        print(f"[봇] {self.user} 로그인 완료")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="주식 시세 👀",
            )
        )


if __name__ == "__main__":
    bot = StockBot()
    bot.run(DISCORD_TOKEN)
