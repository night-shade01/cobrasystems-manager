import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import random

class Giveaways(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(title=title, description=description, color=color or self.bot.embed_color, timestamp=datetime.utcnow())
        embed.set_footer(text=self.bot.footer)
        return embed

    @commands.has_permissions(manage_guild=True)
    @commands.hybrid_command(name="startgiveaway", description="Start a giveaway: duration (e.g. 1h) | winners | prize")
    async def startgiveaway(self, ctx: commands.Context, duration: str, winners: int, *, prize: str):
        # parse duration
        unit = duration[-1].lower()
        amount = int(duration[:-1])
        mult = {"s":1, "m":60, "h":3600, "d":86400}.get(unit, 0)
        seconds = amount * mult
        if seconds <= 0:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Invalid duration.", 0xFFAA00))
        end = int(datetime.utcnow().timestamp()) + seconds
        gid = str(ctx.guild.id)
        data = {"guild_id": gid, "channel_id": ctx.channel.id, "message_id": None, "end": end, "winners": winners, "prize": prize}
        if hasattr(self.bot, "db"):
            res = await self.bot.db["giveaways"].insert_one(data)
            gidb = str(res.inserted_id)
            data["_id"] = gidb
        else:
            self.bot.config.setdefault("giveaways", []).append(data)
            self.bot.save_config()
        embed = self.get_embed("🎉 Giveaway", f"Prize: {prize}\nEnds in: {duration}\nWinners: {winners}")
        msg = await ctx.send(embed=embed, ephemeral=False)
        # store message id
        if hasattr(self.bot, "db"):
            await self.bot.db["giveaways"].update_one({"_id": data.get("_id")}, {"$set": {"message_id": msg.id}})
        else:
            for g in self.bot.config.get("giveaways", []):
                if g.get("prize") == prize and g.get("end") == end:
                    g["message_id"] = msg.id
            self.bot.save_config()
        await msg.add_reaction("🎉")

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        now = int(datetime.utcnow().timestamp())
        if hasattr(self.bot, "db"):
            docs = await self.bot.db["giveaways"].find({"end": {"$lte": now}}).to_list(length=None)
            for d in docs:
                try:
                    guild = self.bot.get_guild(int(d.get("guild_id")))
                    channel = guild.get_channel(d.get("channel_id"))
                    msg = await channel.fetch_message(d.get("message_id"))
                    users = [r.user async for r in msg.reactions if getattr(r, 'emoji', None) == '🎉']
                except Exception:
                    users = []
                # pick winners
                try:
                    entries = []
                    for react in msg.reactions:
                        if str(react.emoji) == "🎉":
                            entries = [u async for u in react.users() if not u.bot]
                    winners = []
                    if entries:
                        winners = random.sample(entries, min(d.get("winners", 1), len(entries)))
                    text = "No valid entrants." if not winners else ", ".join(w.mention for w in winners)
                    await channel.send(embed=self.get_embed("🎊 Giveaway Ended", f"Prize: {d.get('prize')}\nWinners: {text}"))
                except Exception:
                    pass
                await self.bot.db["giveaways"].delete_one({"_id": d.get("_id")})
        else:
            to_remove = []
            for g in list(self.bot.config.get("giveaways", [])):
                if g.get("end") <= now:
                    try:
                        guild = self.bot.get_guild(int(g.get("guild_id")))
                        channel = guild.get_channel(g.get("channel_id"))
                        msg = await channel.fetch_message(g.get("message_id"))
                        entries = []
                        for react in msg.reactions:
                            if str(react.emoji) == "🎉":
                                entries = [u async for u in react.users() if not u.bot]
                        winners = []
                        if entries:
                            winners = random.sample(entries, min(g.get("winners", 1), len(entries)))
                        text = "No valid entrants." if not winners else ", ".join(w.mention for w in winners)
                        await channel.send(embed=self.get_embed("🎊 Giveaway Ended", f"Prize: {g.get('prize')}\nWinners: {text}"))
                    except Exception:
                        pass
                    to_remove.append(g)
            for r in to_remove:
                self.bot.config.get("giveaways", []).remove(r)
            if to_remove:
                self.bot.save_config()

async def setup(bot):
    await bot.add_cog(Giveaways(bot))
