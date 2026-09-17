import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
import json
import os
import re
import aiohttp

WARNINGS_FILE = "data/warnings.json"

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # If bot.db is available, use MongoDB; otherwise fall back to JSON file
        self.use_db = hasattr(bot, "db")
        if not self.use_db:
            self.warnings = self.load_warnings()
        else:
            self.warnings = None

    def load_warnings(self):
        if not os.path.exists(WARNINGS_FILE):
            return {}
        try:
            with open(WARNINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def save_warnings(self):
        os.makedirs("data", exist_ok=True)
        with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.warnings, f, indent=2)

    # Helper: add warning to DB
    async def _db_add_warning(self, guild_id: str, user_id: str, warn_data: dict):
        coll = self.bot.db["warnings"]
        await coll.update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"$push": {"warnings": warn_data}},
            upsert=True
        )

    async def _db_get_warnings(self, guild_id: str, user_id: str):
        coll = self.bot.db["warnings"]
        doc = await coll.find_one({"guild_id": guild_id, "user_id": user_id})
        return doc.get("warnings", []) if doc else []

    async def _db_clear_warnings(self, guild_id: str, user_id: str):
        coll = self.bot.db["warnings"]
        await coll.delete_one({"guild_id": guild_id, "user_id": user_id})

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.bot.embed_color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=self.bot.footer)
        return embed

    # ==================== BAN ====================
    @commands.hybrid_command(name="ban", description="Ban a member from the server")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(member="The member to ban", reason="Reason for the ban", delete_days="Delete messages from the last X days (0-7)")
    async def ban(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided", delete_days: int = 0):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "You cannot ban someone with equal or higher role.", 0xFF0000))
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot ban someone with equal or higher role than me.", 0xFF0000))
        if member.id == ctx.guild.owner_id:
            return await ctx.send(embed=self.get_embed("⛔ Error", "You cannot ban the server owner.", 0xFF0000))

        delete_days = max(0, min(7, delete_days))
        try:
            await member.ban(reason=f"{reason} | By: {ctx.author}", delete_message_days=delete_days)
            embed = self.get_embed(
                "🔨 Member Banned",
                f"**User:** {member} (`{member.id}`)\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}"
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== UNBAN ====================
    @commands.hybrid_command(name="unban", description="Unban a user by ID")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(user_id="The ID of the user to unban", reason="Reason for the unban")
    async def unban(self, ctx: commands.Context, user_id: str, reason: str = "No reason provided"):
        try:
            user = await self.bot.fetch_user(int(user_id))
            await ctx.guild.unban(user, reason=f"{reason} | By: {ctx.author}")
            embed = self.get_embed(
                "✅ Member Unbanned",
                f"**User:** {user} (`{user.id}`)\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}"
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== KICK ====================
    @commands.hybrid_command(name="kick", description="Kick a member from the server")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    @app_commands.describe(member="The member to kick", reason="Reason for the kick")
    async def kick(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "You cannot kick someone with equal or higher role.", 0xFF0000))
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot kick someone with equal or higher role than me.", 0xFF0000))

        try:
            await member.kick(reason=f"{reason} | By: {ctx.author}")
            embed = self.get_embed(
                "👢 Member Kicked",
                f"**User:** {member} (`{member.id}`)\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}"
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== TIMEOUT / MUTE ====================
    @commands.hybrid_command(name="mute", description="Timeout (mute) a member", aliases=["timeout"])
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to mute", duration="Duration (e.g. 10m, 1h, 1d)", reason="Reason for the mute")
    async def mute(self, ctx: commands.Context, member: discord.Member, duration: str = "10m", reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "You cannot mute someone with equal or higher role.", 0xFF0000))
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot mute someone with equal or higher role than me.", 0xFF0000))

        # Parse duration
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        try:
            amount = int(duration[:-1])
            unit = duration[-1].lower()
            seconds = amount * units[unit]
            if seconds > 2419200:  # Discord max ~28 days
                return await ctx.send(embed=self.get_embed("⚠️ Invalid Duration", "Maximum timeout is 28 days.", 0xFFAA00))
            delta = timedelta(seconds=seconds)
        except (ValueError, KeyError):
            return await ctx.send(embed=self.get_embed("⚠️ Invalid Duration", "Use format like `10m`, `1h`, `2d`.", 0xFFAA00))

        try:
            await member.timeout(delta, reason=f"{reason} | By: {ctx.author}")
            embed = self.get_embed(
                "🔇 Member Muted",
                f"**User:** {member.mention} (`{member.id}`)\n**Duration:** {duration}\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}"
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== UNMUTE ====================
    @commands.hybrid_command(name="unmute", description="Remove timeout from a member")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to unmute", reason="Reason for the unmute")
    async def unmute(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided"):
        try:
            await member.timeout(None, reason=f"{reason} | By: {ctx.author}")
            embed = self.get_embed(
                "🔊 Member Unmuted",
                f"**User:** {member.mention} (`{member.id}`)\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}"
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== WARN ====================
    @commands.hybrid_command(name="warn", description="Warn a member")
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to warn", reason="Reason for the warning")
    async def warn(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided"):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)

        if guild_id not in self.warnings:
            self.warnings[guild_id] = {}
        if user_id not in self.warnings[guild_id]:
            self.warnings[guild_id][user_id] = []

        warn_data = {
            "reason": reason,
            "moderator": str(ctx.author.id),
            "timestamp": datetime.utcnow().isoformat()
        }
        if self.use_db:
            await self._db_add_warning(guild_id, user_id, warn_data)
            warns = await self._db_get_warnings(guild_id, user_id)
            count = len(warns)
        else:
            self.warnings[guild_id][user_id].append(warn_data)
            self.save_warnings()
            count = len(self.warnings[guild_id][user_id])
        embed = self.get_embed(
            "⚠️ Member Warned",
            f"**User:** {member.mention} (`{member.id}`)\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}\n**Total Warnings:** {count}"
        )
        await ctx.send(embed=embed)

        try:
            dm_embed = self.get_embed(
                f"You were warned in {ctx.guild.name}",
                f"**Reason:** {reason}\n**Moderator:** {ctx.author}\n**Total Warnings:** {count}"
            )
            await member.send(embed=dm_embed)
        except:
            pass

    # ==================== WARNINGS ====================
    @commands.hybrid_command(name="warnings", description="View warnings for a member")
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="The member to check")
    async def warnings(self, ctx: commands.Context, member: discord.Member):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        if self.use_db:
            user_warns = await self._db_get_warnings(guild_id, user_id)
        else:
            user_warns = self.warnings.get(guild_id, {}).get(user_id, [])

        if not user_warns:
            return await ctx.send(embed=self.get_embed("📋 Warnings", f"{member.mention} has no warnings."))

        description = ""
        for i, w in enumerate(user_warns, 1):
            mod = ctx.guild.get_member(int(w["moderator"]))
            mod_name = mod.mention if mod else f"<@{w['moderator']}>"
            description += f"**{i}.** {w['reason']}\n└ Moderator: {mod_name} • <t:{int(datetime.fromisoformat(w['timestamp']).timestamp())}:R>\n\n"

        embed = self.get_embed(f"📋 Warnings for {member}", description)
        embed.set_footer(text=f"Total: {len(user_warns)} • {self.bot.footer}")
        await ctx.send(embed=embed)

    # ==================== CLEARWARN ====================
    @commands.hybrid_command(name="clearwarns", description="Clear all warnings for a member")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(member="The member to clear warnings for")
    async def clearwarns(self, ctx: commands.Context, member: discord.Member):
        guild_id = str(ctx.guild.id)
        user_id = str(member.id)
        if self.use_db:
            await self._db_clear_warnings(guild_id, user_id)
            await ctx.send(embed=self.get_embed("✅ Cleared", f"All warnings for {member.mention} have been cleared."))
        else:
            if guild_id in self.warnings and user_id in self.warnings[guild_id]:
                del self.warnings[guild_id][user_id]
                self.save_warnings()
                await ctx.send(embed=self.get_embed("✅ Cleared", f"All warnings for {member.mention} have been cleared."))
            else:
                await ctx.send(embed=self.get_embed("📋 Warnings", f"{member.mention} has no warnings."))

    # ==================== PURGE ====================
    @commands.hybrid_command(name="purge", description="Delete a number of messages", aliases=["clear", "prune"])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    @app_commands.describe(amount="Number of messages to delete (1-100)", member="Only delete messages from this member")
    async def purge(self, ctx: commands.Context, amount: int, member: discord.Member = None):
        if amount < 1 or amount > 100:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid Amount", "Please provide a number between 1 and 100.", 0xFFAA00))

        if ctx.interaction is not None and not ctx.interaction.response.is_done():
            await ctx.send(
                embed=self.get_embed(
                    "🧹 Purging Messages",
                    f"Deleting up to **{amount}** message(s)...",
                    0xFFAA00,
                ),
                ephemeral=True,
            )

        def check(msg):
            if member:
                return msg.author.id == member.id
            return True

        # Delete the command message first if prefix
        if ctx.interaction is None:
            try:
                await ctx.message.delete()
            except:
                pass

        deleted = await ctx.channel.purge(limit=amount, check=check)
        embed = self.get_embed("🧹 Purged", f"Deleted **{len(deleted)}** message(s).")
        msg = await ctx.channel.send(embed=embed)
        await msg.delete(delay=3)

    # ==================== LOCK / UNLOCK ====================
    @commands.hybrid_command(name="lock", description="Lock the current channel")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=self.get_embed("🔒 Channel Locked", f"{ctx.channel.mention} has been locked."))

    @commands.hybrid_command(name="unlock", description="Unlock the current channel")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=self.get_embed("🔓 Channel Unlocked", f"{ctx.channel.mention} has been unlocked."))

    # ==================== SLOWMODE ====================
    @commands.hybrid_command(name="slowmode", description="Set slowmode for the channel")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable, max 21600)")
    async def slowmode(self, ctx: commands.Context, seconds: int):
        if seconds < 0 or seconds > 21600:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Slowmode must be between 0 and 21600 seconds.", 0xFFAA00))
        await ctx.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await ctx.send(embed=self.get_embed("🐢 Slowmode Disabled", f"Slowmode has been disabled in {ctx.channel.mention}."))
        else:
            await ctx.send(embed=self.get_embed("🐢 Slowmode Set", f"Slowmode set to **{seconds}** seconds in {ctx.channel.mention}."))

    # ==================== NICKNAME ====================
    @commands.hybrid_command(name="nick", description="Change a member's nickname", aliases=["nickname", "setnick"])
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    @app_commands.describe(member="The member to rename", nickname="New nickname (leave empty to reset)")
    async def nick(self, ctx: commands.Context, member: discord.Member, *, nickname: str = None):
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot change that member's nickname.", 0xFF0000))
        try:
            await member.edit(nick=nickname, reason=f"Nickname changed by {ctx.author}")
            if nickname:
                await ctx.send(embed=self.get_embed("✅ Nickname Set", f"{member.mention} is now known as **{nickname}**."))
            else:
                await ctx.send(embed=self.get_embed("✅ Nickname Reset", f"{member.mention}'s nickname was reset."))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== SOFTBAN ====================
    @commands.hybrid_command(name="softban", description="Ban then instantly unban a member to wipe their messages")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(member="The member to softban", reason="Reason for the softban")
    async def softban(self, ctx: commands.Context, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "You cannot softban someone with equal or higher role.", 0xFF0000))
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot softban someone with equal or higher role than me.", 0xFF0000))
        try:
            await member.ban(reason=f"Softban: {reason} | By: {ctx.author}", delete_message_days=7)
            await ctx.guild.unban(member, reason=f"Softban release | By: {ctx.author}")
            await ctx.send(embed=self.get_embed(
                "🧹 Member Softbanned",
                f"**User:** {member} (`{member.id}`)\n**Moderator:** {ctx.author.mention}\n**Reason:** {reason}\nTheir recent messages were deleted and they can rejoin."
            ))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== NUKE ====================
    @commands.hybrid_command(name="nuke", description="Clone and recreate the current channel, wiping all messages")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def nuke(self, ctx: commands.Context):
        channel = ctx.channel
        if not isinstance(channel, discord.TextChannel):
            return await ctx.send(embed=self.get_embed("❌ Invalid Channel", "Only text channels can be nuked.", 0xFF0000))
        try:
            new_channel = await channel.clone(reason=f"Channel nuked by {ctx.author}")
            await new_channel.edit(position=channel.position)
            await channel.delete(reason=f"Channel nuked by {ctx.author}")
            embed = self.get_embed("💥 Channel Nuked", "This channel has been wiped clean.")
            embed.set_image(url="https://media.giphy.com/media/HhTXt43pk1I1W/giphy.gif")
            await new_channel.send(embed=embed)
        except discord.Forbidden:
            await ctx.send(embed=self.get_embed("❌ Missing Permissions", "I need **Manage Channels** to nuke this channel.", 0xFF0000))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== STEAL EMOJI ====================
    @commands.hybrid_command(name="steal", description="Add a custom emoji from another server to this one", aliases=["addemoji"])
    @commands.has_permissions(manage_expressions=True)
    @commands.bot_has_permissions(manage_expressions=True)
    @app_commands.describe(emoji="The custom emoji to steal", name="Name for the new emoji (defaults to the original name)")
    async def steal(self, ctx: commands.Context, emoji: str, name: str = None):
        match = re.match(r"<(a?):([a-zA-Z0-9_]+):(\d+)>", emoji.strip())
        if not match:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Please provide a custom emoji, not a standard one.", 0xFFAA00))

        animated = bool(match.group(1))
        emoji_name = name or match.group(2)
        emoji_id = match.group(3)
        extension = "gif" if animated else "png"
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}"

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return await ctx.send(embed=self.get_embed("❌ Failed", "Couldn't download that emoji.", 0xFF0000))
                    image_data = await resp.read()
            created = await ctx.guild.create_custom_emoji(
                name=emoji_name,
                image=image_data,
                reason=f"Emoji stolen by {ctx.author}",
            )
            await ctx.send(embed=self.get_embed("✅ Emoji Added", f"Added {created} as `{created.name}`."))
        except discord.Forbidden:
            await ctx.send(embed=self.get_embed("❌ Missing Permissions", "I need **Manage Expressions** to add emojis.", 0xFF0000))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    # ==================== HIDE / SHOW ====================
    @commands.hybrid_command(name="hide", description="Hide the current channel from @everyone")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def hide(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=self.get_embed("🙈 Channel Hidden", f"{ctx.channel.mention} is now hidden from @everyone."))

    @commands.hybrid_command(name="show", description="Make a hidden channel visible to @everyone again")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def show(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=self.get_embed("👁️ Channel Visible", f"{ctx.channel.mention} is visible to @everyone again."))

async def setup(bot):
    await bot.add_cog(Moderation(bot))