import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import random


def economy_manager():
    """Allow the bot owner, server owner, or a server administrator."""
    async def predicate(ctx: commands.Context):
        if await ctx.bot.is_owner(ctx.author):
            return True
        return bool(
            ctx.guild
            and (
                ctx.author.id == ctx.guild.owner_id
                or ctx.author.guild_permissions.administrator
            )
        )

    return commands.check(predicate)

class Economy(commands.Cog):
    """Global coin economy with safe owner/admin management tools."""
    def __init__(self, bot):
        self.bot = bot

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(title=title, description=description, color=color or self.bot.embed_color, timestamp=datetime.utcnow())
        embed.set_footer(text=self.bot.footer)
        return embed

    async def _get_balance(self, user_id: str):
        if hasattr(self.bot, "db"):
            doc = await self.bot.db["economy"].find_one({"user_id": user_id})
            return int(doc.get("balance", 0)) if doc else 0

        value = self.bot.config.setdefault("economy", {}).get(user_id, 0)
        # Support both the original integer format and the newer metadata format.
        return int(value.get("balance", 0) if isinstance(value, dict) else value)

    def _json_entry(self, user_id: str):
        economy = self.bot.config.setdefault("economy", {})
        value = economy.get(user_id, 0)
        if not isinstance(value, dict):
            value = {"balance": int(value), "last_daily": 0, "last_work": 0}
            economy[user_id] = value
        value.setdefault("balance", 0)
        value.setdefault("last_daily", 0)
        value.setdefault("last_work", 0)
        return value

    async def _set_balance(self, user_id: str, amount: int):
        amount = max(0, int(amount))
        if hasattr(self.bot, "db"):
            await self.bot.db["economy"].update_one({"user_id": user_id}, {"$set": {"balance": amount}}, upsert=True)
        else:
            self._json_entry(user_id)["balance"] = amount
            self.bot.save_config()

    async def _adjust_balance(self, user_id: str, amount: int):
        balance = await self._get_balance(user_id)
        new_balance = balance + int(amount)
        if new_balance < 0:
            return None
        await self._set_balance(user_id, new_balance)
        return new_balance

    @commands.hybrid_command(name="balance", description="Check your balance")
    async def balance(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        bal = await self._get_balance(str(member.id))
        await ctx.send(embed=self.get_embed("💰 Balance", f"{member.mention} has **{bal}** coins."))

    @commands.hybrid_command(name="give", description="Give coins to another user")
    async def give(self, ctx: commands.Context, member: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Amount must be positive.", 0xFFAA00))
        if member.bot or member.id == ctx.author.id:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Choose another human member.", 0xFFAA00))
        user_id = str(ctx.author.id)
        target_id = str(member.id)
        bal = await self._get_balance(user_id)
        if bal < amount:
            return await ctx.send(embed=self.get_embed("⚠️ Insufficient", "You don't have enough coins.", 0xFFAA00))
        await self._set_balance(user_id, bal - amount)
        targ_bal = await self._get_balance(target_id)
        await self._set_balance(target_id, targ_bal + amount)
        await ctx.send(embed=self.get_embed("✅ Sent", f"Sent **{amount}** coins to {member.mention}."))

    @commands.hybrid_command(name="work", description="Work for a random coin reward")
    async def work(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        now = int(datetime.utcnow().timestamp())
        if hasattr(self.bot, "db"):
            doc = await self.bot.db["economy"].find_one({"user_id": uid}) or {}
            last_work = int(doc.get("last_work", 0))
        else:
            last_work = int(self._json_entry(uid).get("last_work", 0))
        remaining = 3600 - (now - last_work)
        if remaining > 0:
            return await ctx.send(embed=self.get_embed("⏳ Slow down", f"You can work again in **{remaining // 60}m {remaining % 60}s**.", 0xFFAA00))

        reward = random.randint(50, 150)
        await self._adjust_balance(uid, reward)
        if hasattr(self.bot, "db"):
            await self.bot.db["economy"].update_one({"user_id": uid}, {"$set": {"last_work": now}}, upsert=True)
        else:
            self._json_entry(uid)["last_work"] = now
            self.bot.save_config()
        await ctx.send(embed=self.get_embed("💼 Work complete", f"You earned **{reward}** coins!"))

    @commands.hybrid_command(name="leaderboard", description="Show the richest members in this server")
    async def leaderboard(self, ctx: commands.Context):
        if not ctx.guild:
            return await ctx.send(embed=self.get_embed("⚠️ Server only", "The leaderboard is only available in a server.", 0xFFAA00))
        rows = [(await self._get_balance(str(member.id)), member) for member in ctx.guild.members if not member.bot]
        rows = sorted(rows, key=lambda row: row[0], reverse=True)[:10]
        if not rows or rows[0][0] == 0:
            return await ctx.send(embed=self.get_embed("🏆 Leaderboard", "Nobody has coins yet. Claim `/daily` or use `/work`!"))
        text = "\n".join(f"**{index}.** {member.mention} — **{balance}** coins" for index, (balance, member) in enumerate(rows, 1))
        await ctx.send(embed=self.get_embed("🏆 Coin Leaderboard", text))

    @economy_manager()
    @commands.hybrid_command(name="addmoney", description="Add coins to a member (owner/admin only)")
    @app_commands.describe(member="Member receiving coins", amount="Positive number of coins")
    async def addmoney(self, ctx: commands.Context, member: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Amount must be positive.", 0xFFAA00))
        balance = await self._adjust_balance(str(member.id), amount)
        await ctx.send(embed=self.get_embed("✅ Money added", f"Added **{amount}** coins to {member.mention}.\nNew balance: **{balance}** coins."))

    @economy_manager()
    @commands.hybrid_command(name="removemoney", description="Remove coins from a member (owner/admin only)")
    @app_commands.describe(member="Member losing coins", amount="Positive number of coins")
    async def removemoney(self, ctx: commands.Context, member: discord.Member, amount: int):
        if amount <= 0:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Amount must be positive.", 0xFFAA00))
        current = await self._get_balance(str(member.id))
        if amount > current:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", f"{member.mention} only has **{current}** coins.", 0xFFAA00))
        balance = await self._adjust_balance(str(member.id), -amount)
        await ctx.send(embed=self.get_embed("✅ Money removed", f"Removed **{amount}** coins from {member.mention}.\nNew balance: **{balance}** coins."))

    @economy_manager()
    @commands.hybrid_command(name="setmoney", description="Set a member's balance (owner/admin only)")
    @app_commands.describe(member="Member whose balance changes", amount="New balance, zero or higher")
    async def setmoney(self, ctx: commands.Context, member: discord.Member, amount: int):
        if amount < 0:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Balance cannot be negative.", 0xFFAA00))
        await self._set_balance(str(member.id), amount)
        await ctx.send(embed=self.get_embed("✅ Balance updated", f"Set {member.mention}'s balance to **{amount}** coins."))

    @economy_manager()
    @commands.hybrid_command(name="resetmoney", description="Reset a member's balance to zero (owner/admin only)")
    async def resetmoney(self, ctx: commands.Context, member: discord.Member):
        await self._set_balance(str(member.id), 0)
        await ctx.send(embed=self.get_embed("✅ Balance reset", f"Reset {member.mention}'s balance to **0** coins."))

    @commands.hybrid_command(name="daily", description="Claim your daily coins")
    async def daily(self, ctx: commands.Context):
        uid = str(ctx.author.id)
        if hasattr(self.bot, "db"):
            doc = await self.bot.db["economy"].find_one({"user_id": uid})
            last = doc.get("last_daily", 0) if doc else 0
            bal = doc.get("balance", 0) if doc else 0
            now = int(datetime.utcnow().timestamp())
            if now - last < 86400:
                return await ctx.send(embed=self.get_embed("⏳ Wait", "You can only claim daily once every 24 hours.", 0xFFAA00))
            bal += 100
            await self.bot.db["economy"].update_one({"user_id": uid}, {"$set": {"balance": bal, "last_daily": now}}, upsert=True)
            await ctx.send(embed=self.get_embed("✅ Claimed", "You claimed **100** coins."))
        else:
            ent = self._json_entry(uid)
            now = int(datetime.utcnow().timestamp())
            if now - ent.get("last_daily", 0) < 86400:
                return await ctx.send(embed=self.get_embed("⏳ Wait", "You can only claim daily once every 24 hours.", 0xFFAA00))
            ent["balance"] = ent.get("balance", 0) + 100
            ent["last_daily"] = now
            self.bot.save_config()
            await ctx.send(embed=self.get_embed("✅ Claimed", "You claimed **100** coins."))

    # ==================== GAMBLING ====================
    @commands.hybrid_command(name="slots", description="Bet coins on the slot machine")
    @app_commands.describe(bet="Amount of coins to bet")
    async def slots(self, ctx: commands.Context, bet: int):
        if bet <= 0:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Bet must be positive.", 0xFFAA00))
        uid = str(ctx.author.id)
        bal = await self._get_balance(uid)
        if bal < bet:
            return await ctx.send(embed=self.get_embed("⚠️ Insufficient", f"You only have **{bal}** coins.", 0xFFAA00))

        emojis = ["🍒", "🍋", "🍇", "⭐", "💎", "7️⃣"]
        reels = [random.choice(emojis) for _ in range(3)]
        display = " | ".join(reels)

        if len(set(reels)) == 1:
            multiplier = 10 if reels[0] in ("💎", "7️⃣") else 5
            winnings = bet * multiplier
            await self._adjust_balance(uid, winnings - bet)
            new_bal = await self._get_balance(uid)
            result = f"🎰 **JACKPOT!** You won **{winnings}** coins!"
        elif len(set(reels)) == 2:
            await self._adjust_balance(uid, bet)
            new_bal = await self._get_balance(uid)
            result = f"Nice! Two of a kind — you won **{bet * 2}** coins!"
        else:
            await self._adjust_balance(uid, -bet)
            new_bal = await self._get_balance(uid)
            result = f"No match — you lost **{bet}** coins."

        await ctx.send(embed=self.get_embed(
            "🎰 Slots",
            f"**{display}**\n\n{result}\nBalance: **{new_bal}** coins"
        ))

    @commands.hybrid_command(name="coinflip", description="Bet coins on a coin flip")
    @app_commands.describe(bet="Amount of coins to bet", choice="heads or tails")
    async def coinflip(self, ctx: commands.Context, bet: int, choice: str):
        choice = choice.lower()
        if choice not in ("heads", "tails"):
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Choose `heads` or `tails`.", 0xFFAA00))
        if bet <= 0:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Bet must be positive.", 0xFFAA00))
        uid = str(ctx.author.id)
        bal = await self._get_balance(uid)
        if bal < bet:
            return await ctx.send(embed=self.get_embed("⚠️ Insufficient", f"You only have **{bal}** coins.", 0xFFAA00))

        result = random.choice(["heads", "tails"])
        if result == choice:
            await self._adjust_balance(uid, bet)
            outcome = f"It landed on **{result}** — you won **{bet}** coins! 🎉"
        else:
            await self._adjust_balance(uid, -bet)
            outcome = f"It landed on **{result}** — you lost **{bet}** coins. 😢"
        new_bal = await self._get_balance(uid)
        await ctx.send(embed=self.get_embed("🪙 Coin Flip", f"{outcome}\nBalance: **{new_bal}** coins"))

async def setup(bot):
    await bot.add_cog(Economy(bot))
