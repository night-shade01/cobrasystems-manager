import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import random

class Leveling(commands.Cog):
    """Basic leveling system: awards XP per message and allows checking level."""
    def __init__(self, bot):
        self.bot = bot

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(title=title, description=description, color=color or self.bot.embed_color, timestamp=datetime.utcnow())
        embed.set_footer(text=self.bot.footer)
        return embed

    async def _add_xp(self, user_id: str, amount: int):
        if hasattr(self.bot, "db"):
            doc = await self.bot.db["levels"].find_one({"user_id": user_id})
            if not doc:
                await self.bot.db["levels"].insert_one({"user_id": user_id, "xp": amount})
            else:
                await self.bot.db["levels"].update_one({"user_id": user_id}, {"$inc": {"xp": amount}})
        else:
            cfg = self.bot.config.setdefault("levels", {})
            cfg[user_id] = cfg.get(user_id, 0) + amount
            self.bot.save_config()

    async def _get_xp(self, user_id: str):
        if hasattr(self.bot, "db"):
            doc = await self.bot.db["levels"].find_one({"user_id": user_id})
            return doc.get("xp", 0) if doc else 0
        else:
            return self.bot.config.get("levels", {}).get(user_id, 0)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        # small chance to award xp to reduce spam
        if random.random() < 0.35:
            xp = random.randint(5, 15)
            await self._add_xp(str(message.author.id), xp)

    @commands.hybrid_command(name="level", description="Show a member's XP/level", aliases=["rank"])
    async def level(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        xp = await self._get_xp(str(member.id))
        level = int((xp // 100) ** 0.5 * 10)  # simple progression
        await ctx.send(embed=self.get_embed("📈 Level", f"{member.mention}: Level **{level}** • XP **{xp}**"))

    @commands.hybrid_command(name="levels", description="Show the server XP leaderboard", aliases=["xptop", "leveltop"])
    async def levels(self, ctx: commands.Context):
        if hasattr(self.bot, "db"):
            docs = await self.bot.db["levels"].find().sort("xp", -1).limit(10).to_list(length=10)
            rows = [(int(d.get("xp", 0)), str(d.get("user_id"))) for d in docs]
        else:
            cfg = self.bot.config.get("levels", {})
            rows = sorted(((int(xp), str(uid)) for uid, xp in cfg.items()), reverse=True)[:10]

        if not rows:
            return await ctx.send(embed=self.get_embed("📈 Levels", "Nobody has earned XP yet. Start chatting!"))

        lines = []
        for index, (xp, uid) in enumerate(rows, 1):
            level = int((xp // 100) ** 0.5 * 10)
            lines.append(f"**{index}.** <@{uid}> — Level **{level}** • {xp} XP")
        await ctx.send(embed=self.get_embed("📈 XP Leaderboard", "\n".join(lines)))

async def setup(bot):
    await bot.add_cog(Leveling(bot))
