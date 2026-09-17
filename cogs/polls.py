import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta

class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(title=title, description=description, color=color or self.bot.embed_color, timestamp=datetime.utcnow())
        embed.set_footer(text=self.bot.footer)
        return embed

    @commands.hybrid_command(name="poll", description="Create a poll with options separated by | (e.g. Question | A | B | C)")
    @commands.has_permissions(manage_guild=True)
    async def poll(self, ctx: commands.Context, *, text: str):
        parts = [p.strip() for p in text.split("|") if p.strip()]
        if len(parts) < 2:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Provide a question and at least one option.", 0xFFAA00))
        question = parts[0]
        options = parts[1:]
        if len(options) > 10:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Max 10 options.", 0xFFAA00))
        emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        desc = "\n".join(f"{emojis[i]} {opt}" for i,opt in enumerate(options))
        embed = self.get_embed(question, desc)
        msg = await ctx.send(embed=embed, ephemeral=False)
        for i in range(len(options)):
            try:
                await msg.add_reaction(emojis[i])
            except Exception:
                pass

async def setup(bot):
    await bot.add_cog(Polls(bot))
