import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import platform
import time
import os
import json
import uuid
import asyncio
import ast
import operator

REMINDERS_FILE = "data/reminders.json"

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        self.use_db = hasattr(bot, "db")
        self.reminders = {} if self.use_db else self.load_reminders()
        # channel_id -> last deleted message snapshot for /snipe
        self.sniped_messages = {}
        # start background reminder loop
        try:
            self.bot.loop.create_task(self._reminder_loop())
        except Exception:
            pass

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.bot.embed_color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=self.bot.footer)
        return embed

    def load_reminders(self):
        if not os.path.exists(REMINDERS_FILE):
            return {}
        try:
            with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def save_reminders(self):
        os.makedirs("data", exist_ok=True)
        with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.reminders, f, indent=2)

    def _parse_duration(self, text: str):
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        try:
            amount = int(text[:-1])
            unit = text[-1].lower()
            return amount * units[unit]
        except Exception:
            return None

    async def _reminder_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = int(time.time())
            # If using DB, pull due reminders from collection; otherwise use local store
            if self.use_db:
                try:
                    coll = self.bot.db["reminders"]
                    docs = await coll.find({"timestamp": {"$lte": now}}).to_list(length=None)
                    for d in docs:
                        try:
                            user = await self.bot.fetch_user(int(d.get("user_id")))
                            msg = d.get("message", "Reminder")
                            embed = self.get_embed("⏰ Reminder", msg)
                            await user.send(embed=embed)
                        except Exception:
                            pass
                        # remove delivered reminder
                        await coll.delete_one({"_id": d.get("_id")})
                except Exception:
                    pass
            else:
                changed = False
                for user_id, items in list(self.reminders.items()):
                    for r in list(items):
                        if r.get("timestamp") <= now:
                            try:
                                user = await self.bot.fetch_user(int(user_id))
                                msg = r.get("message", "Reminder")
                                embed = self.get_embed("⏰ Reminder", msg)
                                await user.send(embed=embed)
                            except Exception:
                                pass
                            items.remove(r)
                            changed = True
                    if not items:
                        self.reminders.pop(user_id, None)
                if changed:
                    self.save_reminders()
            await asyncio.sleep(5)

    # ==================== HELP ====================
    @commands.hybrid_command(name="help", description="Show all available commands")
    async def help(self, ctx: commands.Context):
        embed = self.get_embed(
            "🐍 Cobra Systems™ Manager — Help",
            "A powerful server management bot.\nUse `/command` or `!command`.\nReplies are hidden so only you can see them."
        )

        embed.add_field(
            name="🛡️ Moderation",
            value=(
                "`ban` `unban` `kick` `softban`\n"
                "`mute` / `timeout` `unmute` `nick`\n"
                "`warn` `warnings` `clearwarns`\n"
                "`purge` `lock` `unlock` `slowmode`\n"
                "`nuke` `hide` `show` `steal`"
            ),
            inline=True
        )
        embed.add_field(
            name="🎭 Roles & Setup",
            value=(
                "`autorole` `welcome` `setlog`\n"
                "`reactionrole` / `rr`\n"
                "`removereactionrole`\n"
                "`giverole` `takerole`\n"
                "`ticketpanel` `ticketclose` `ticketrename`"
            ),
            inline=True
        )
        embed.add_field(
            name="🔧 Utility",
            value=(
                "`help` `ping` `uptime` `botinfo`\n"
                "`userinfo` `serverinfo` `membercount`\n"
                "`avatar` `roleinfo` `invite`\n"
                "`embed` `say` `calc` `snipe`\n"
                "`remindme` `reminders` `cancelreminder`"
            ),
            inline=True
        )
        embed.add_field(
            name="🎉 Fun",
            value=(
                "`coin` `roll` `choose` `rps`\n"
                "`8ball` `rate` `ship` `joke`\n"
                "`mock` `emojify` `reverse` `clap`\n"
                "`catfact` `dogpic`"
            ),
            inline=True
        )

        embed.add_field(
            name="� Tasks",
            value=(
                "`task` `tasks` `taskinfo`\n"
                "`taskcomplete` `taskremove`\n"
                "`tag` `tagcreate` `tagdelete` `taglist`"
            ),
            inline=True
        )

        embed.add_field(
            name="🛠️ Server Management",
            value=(
                "`announce` `setservername`\n"
                "`channelinfo` `dm` `createrole`\n"
                "`poll` `startgiveaway` `setstarboard`"
            ),
            inline=True
        )

        embed.add_field(
            name="�💰 Economy",
            value=(
                "`balance` `give` `daily` `work`\n"
                "`slots` `coinflip`\n"
                "`leaderboard` `level` / `rank` `levels`\n"
                "Admin: `addmoney` `removemoney`\n"
                "`setmoney` `resetmoney`"
            ),
            inline=True
        )

        embed.add_field(
            name="📌 Quick Setup",
            value=(
                "1. `/setlog #mod-logs` — Enable logging\n"
                "2. `/welcome #welcome` — Welcome messages\n"
                "3. `/autorole @Member` — Auto role on join\n"
                "4. `/reactionrole` — Create reaction roles\n"
                "5. `/ticketpanel #tickets` — Post a ticket panel\n"
                "6. `/ticketpanel #tickets #ticket-logs` — Add ticket transcripts/logs"
            ),
            inline=False
        )

        await ctx.send(embed=embed)

    # ==================== PING ====================
    @commands.hybrid_command(name="ping", description="Check the bot's latency")
    async def ping(self, ctx: commands.Context):
        latency = round(self.bot.latency * 1000)
        embed = self.get_embed("🏓 Pong!", f"Latency: **{latency}ms**")
        await ctx.send(embed=embed)

    # ==================== UPTIME ====================
    @commands.hybrid_command(name="uptime", description="Show how long the bot has been online")
    async def uptime(self, ctx: commands.Context):
        seconds = int(time.time() - self.start_time)
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        embed = self.get_embed("⏱️ Uptime", f"Online for **{uptime_str}**")
        await ctx.send(embed=embed)

    # ==================== REMINDERS ====================
    @commands.hybrid_command(name="remindme", description="Set a reminder for yourself (e.g. 10m, 1h, 2d)")
    @app_commands.describe(duration="How long until the reminder (10m, 1h, 2d)", message="What to remind you about")
    async def remindme(self, ctx: commands.Context, duration: str, *, message: str = "Reminder!"):
        seconds = self._parse_duration(duration)
        if seconds is None:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid Duration", "Use format like `10m`, `1h`, `2d`.", 0xFFAA00))
        ts = int(time.time()) + seconds
        rid = uuid.uuid4().hex[:8]
        user_id = str(ctx.author.id)
        if self.use_db:
            try:
                coll = self.bot.db["reminders"]
                await coll.insert_one({
                    "user_id": user_id,
                    "id": rid,
                    "timestamp": ts,
                    "message": message,
                    "created_at": int(time.time())
                })
            except Exception:
                return await ctx.send(embed=self.get_embed("❌ Error", "Failed to save reminder to database.", 0xFF0000))
        else:
            if user_id not in self.reminders:
                self.reminders[user_id] = []
            self.reminders[user_id].append({
                "id": rid,
                "timestamp": ts,
                "message": message,
                "created_at": int(time.time())
            })
            self.save_reminders()
        await ctx.send(embed=self.get_embed("✅ Reminder Set", f"I'll remind you in **{duration}** — ID: `{rid}`"))

    @commands.hybrid_command(name="reminders", description="List your active reminders")
    async def reminders_list(self, ctx: commands.Context):
        user_id = str(ctx.author.id)
        if self.use_db:
            try:
                coll = self.bot.db["reminders"]
                docs = await coll.find({"user_id": user_id}).to_list(length=None)
                items = docs
            except Exception:
                items = []
        else:
            items = self.reminders.get(user_id, [])
        if not items:
            return await ctx.send(embed=self.get_embed("⏳ Reminders", "You have no active reminders."))
        desc = ""
        for r in items:
            remain = r.get("timestamp") - int(time.time())
            if remain < 0:
                remain = 0
            m, s = divmod(remain, 60)
            h, m = divmod(m, 60)
            d, h = divmod(h, 24)
            timestr = f"{d}d {h}h {m}m {s}s"
            desc += f"• `{r['id']}` in **{timestr}** — {r.get('message')}\n"
        await ctx.send(embed=self.get_embed("⏳ Your Reminders", desc))

    @commands.hybrid_command(name="cancelreminder", description="Cancel a reminder by ID")
    async def cancelreminder(self, ctx: commands.Context, reminder_id: str):
        user_id = str(ctx.author.id)
        if self.use_db:
            try:
                coll = self.bot.db["reminders"]
                res = await coll.delete_one({"user_id": user_id, "id": reminder_id})
                if res.deleted_count:
                    return await ctx.send(embed=self.get_embed("✅ Cancelled", f"Cancelled reminder `{reminder_id}`."))
                else:
                    return await ctx.send(embed=self.get_embed("❌ Not Found", "No reminder found with that ID.", 0xFF0000))
            except Exception:
                return await ctx.send(embed=self.get_embed("❌ Error", "Failed to cancel reminder.", 0xFF0000))
        else:
            items = self.reminders.get(user_id, [])
            for r in list(items):
                if r.get("id") == reminder_id:
                    items.remove(r)
                    if not items:
                        self.reminders.pop(user_id, None)
                    self.save_reminders()
                    return await ctx.send(embed=self.get_embed("✅ Cancelled", f"Cancelled reminder `{reminder_id}`."))
            await ctx.send(embed=self.get_embed("❌ Not Found", "No reminder found with that ID.", 0xFF0000))

    # ==================== USERINFO ====================
    @commands.hybrid_command(name="userinfo", description="Get information about a user", aliases=["ui", "whois"])
    @app_commands.describe(member="The member to lookup (defaults to you)")
    async def userinfo(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        roles = [r.mention for r in member.roles if r != ctx.guild.default_role]
        roles_str = ", ".join(roles[::-1][:10]) if roles else "None"
        if len(roles) > 10:
            roles_str += f" (+{len(roles)-10} more)"

        embed = self.get_embed(f"User Info — {member}")
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Nickname", value=member.nick or "None", inline=True)
        embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
        embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Top Role", value=member.top_role.mention, inline=True)
        embed.add_field(name=f"Roles [{len(roles)}]", value=roles_str or "None", inline=False)

        if member.timed_out_until:
            embed.add_field(name="Timed Out Until", value=f"<t:{int(member.timed_out_until.timestamp())}:R>", inline=False)

        await ctx.send(embed=embed)

    # ==================== SERVERINFO ====================
    @commands.hybrid_command(name="serverinfo", description="Get information about the server", aliases=["si", "guildinfo"])
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        embed = self.get_embed(f"Server Info — {guild.name}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.add_field(name="ID", value=guild.id, inline=True)
        embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Channels", value=len(guild.channels), inline=True)
        embed.add_field(name="Roles", value=len(guild.roles), inline=True)
        embed.add_field(name="Boost Level", value=guild.premium_tier, inline=True)
        embed.add_field(name="Boosts", value=guild.premium_subscription_count or 0, inline=True)
        embed.add_field(name="Verification", value=str(guild.verification_level).title(), inline=True)

        await ctx.send(embed=embed)

    # ==================== AVATAR ====================
    @commands.hybrid_command(name="avatar", description="Get a user's avatar", aliases=["av", "pfp"])
    @app_commands.describe(member="The member (defaults to you)")
    async def avatar(self, ctx: commands.Context, member: discord.Member = None):
        member = member or ctx.author
        embed = self.get_embed(f"Avatar — {member}")
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    # ==================== ROLEINFO ====================
    @commands.hybrid_command(name="roleinfo", description="Get information about a role")
    @app_commands.describe(role="The role to lookup")
    async def roleinfo(self, ctx: commands.Context, role: discord.Role):
        embed = self.get_embed(f"Role Info — {role.name}")
        embed.color = role.color if role.color.value != 0 else self.bot.embed_color
        embed.add_field(name="ID", value=role.id, inline=True)
        embed.add_field(name="Color", value=str(role.color), inline=True)
        embed.add_field(name="Position", value=role.position, inline=True)
        embed.add_field(name="Members", value=len(role.members), inline=True)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="Created", value=f"<t:{int(role.created_at.timestamp())}:R>", inline=True)
        await ctx.send(embed=embed)

    # ==================== EMBED BUILDER ====================
    @commands.hybrid_command(name="embed", description="Build and post a custom embed (posted silently)")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @app_commands.describe(
        title="Embed title",
        description="Embed body text (use \\n for line breaks)",
        channel="Channel to post in (defaults to this one)",
        color="Hex color like #00ff9f",
        image="Large image URL",
        thumbnail="Small thumbnail URL",
        footer="Footer text"
    )
    async def embed(self, ctx: commands.Context, title: str, description: str, channel: discord.TextChannel = None, color: str = None, image: str = None, thumbnail: str = None, footer: str = None):
        parsed_color = self.bot.embed_color
        if color:
            try:
                parsed_color = int(color.strip().lstrip("#"), 16)
            except ValueError:
                return await ctx.send(embed=self.get_embed("⚠️ Invalid Color", "Use a hex color like `#00ff9f`.", 0xFFAA00))

        custom_embed = discord.Embed(
            title=title,
            description=description.replace("\\n", "\n"),
            color=parsed_color,
            timestamp=datetime.utcnow()
        )
        if image:
            custom_embed.set_image(url=image)
        if thumbnail:
            custom_embed.set_thumbnail(url=thumbnail)
        custom_embed.set_footer(text=footer or self.bot.footer)

        target = channel or ctx.channel
        if channel is not None and channel.id != ctx.channel.id:
            await target.send(embed=custom_embed)
            await ctx.send(embed=self.get_embed("✅ Embed Posted", f"Your embed was posted in {target.mention}."))
        else:
            # Silent public post: no "user used command" indicator
            await ctx.send(embed=custom_embed, ephemeral=False)

    # ==================== SAY ====================
    @commands.hybrid_command(name="say", description="Make the bot say something (posted silently)")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(message="What the bot should say", channel="Channel to send it in (defaults to this one)")
    async def say(self, ctx: commands.Context, message: str, channel: discord.TextChannel = None):
        target = channel or ctx.channel
        if channel is not None and channel.id != ctx.channel.id:
            await target.send(message)
            await ctx.send(embed=self.get_embed("✅ Sent", f"Message sent to {target.mention}."))
        else:
            if ctx.interaction is None:
                try:
                    await ctx.message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
            await ctx.send(message, ephemeral=False)

    # ==================== BOTINFO ====================
    @commands.hybrid_command(name="botinfo", description="Show information about the bot", aliases=["about"])
    async def botinfo(self, ctx: commands.Context):
        seconds = int(time.time() - self.start_time)
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"

        total_users = sum(g.member_count or 0 for g in self.bot.guilds)
        embed = self.get_embed("🐍 Bot Info", None)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="Servers", value=len(self.bot.guilds), inline=True)
        embed.add_field(name="Users", value=total_users, inline=True)
        embed.add_field(name="Commands", value=len(self.bot.tree.get_commands()), inline=True)
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)}ms", inline=True)
        embed.add_field(name="Python", value=platform.python_version(), inline=True)
        embed.add_field(name="discord.py", value=discord.__version__, inline=True)
        embed.add_field(name="Database", value="MongoDB" if hasattr(self.bot, "db") else "JSON files", inline=True)
        await ctx.send(embed=embed)

    # ==================== INVITE ====================
    @commands.hybrid_command(name="invite", description="Get the bot's invite link")
    async def invite(self, ctx: commands.Context):
        url = discord.utils.oauth_url(
            self.bot.user.id,
            permissions=discord.Permissions(administrator=True),
            scopes=("bot", "applications.commands"),
        )
        embed = self.get_embed("🔗 Invite Me", f"[Click here to invite the bot]({url})")
        await ctx.send(embed=embed)

    # ==================== MEMBERCOUNT ====================
    @commands.hybrid_command(name="membercount", description="Show member counts for the server", aliases=["members"])
    async def membercount(self, ctx: commands.Context):
        guild = ctx.guild
        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)
        embed = self.get_embed("👥 Member Count", None)
        embed.add_field(name="Total", value=guild.member_count, inline=True)
        embed.add_field(name="Humans", value=humans, inline=True)
        embed.add_field(name="Bots", value=bots, inline=True)
        await ctx.send(embed=embed)

    # ==================== CALC ====================
    _CALC_OPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    def _calc_eval(self, node):
        if isinstance(node, ast.Expression):
            return self._calc_eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._CALC_OPS:
            return self._CALC_OPS[type(node.op)](self._calc_eval(node.left), self._calc_eval(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self._calc_eval(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        raise ValueError("Unsupported expression")

    @commands.hybrid_command(name="calc", description="Do quick math (e.g. 2+2*10)", aliases=["math"])
    @app_commands.describe(expression="Math expression like 2+2*10 or (5*3)/2")
    async def calc(self, ctx: commands.Context, *, expression: str):
        try:
            tree = ast.parse(expression, mode="eval")
            result = self._calc_eval(tree)
            await ctx.send(embed=self.get_embed("🧮 Calculator", f"`{expression}` = **{result}**"))
        except Exception:
            await ctx.send(embed=self.get_embed("⚠️ Invalid Expression", "I can only handle basic math: `+ - * / // % **` and parentheses.", 0xFFAA00))

    # ==================== SNIPE ====================
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        self.sniped_messages[message.channel.id] = {
            "content": message.content or "",
            "author": str(message.author),
            "author_id": message.author.id,
            "avatar": message.author.display_avatar.url,
            "attachments": [a.url for a in message.attachments],
            "deleted_at": int(time.time()),
        }

    @commands.hybrid_command(name="snipe", description="Show the last deleted message in this channel")
    @commands.has_permissions(manage_messages=True)
    async def snipe(self, ctx: commands.Context):
        data = self.sniped_messages.get(ctx.channel.id)
        if not data:
            return await ctx.send(embed=self.get_embed("🔭 Snipe", "Nothing to snipe here."))
        description = data["content"] or "*(no text content)*"
        if data["attachments"]:
            description += "\n\n**Attachments:** " + " ".join(data["attachments"])
        embed = self.get_embed("🔭 Sniped Message", description)
        embed.set_author(name=data["author"], icon_url=data["avatar"])
        embed.set_footer(text=f"{self.bot.footer} • Deleted at")
        embed.timestamp = datetime.fromtimestamp(data["deleted_at"])
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Utility(bot))