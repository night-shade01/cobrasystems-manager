import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import json
import os
import time
import uuid

TASKS_FILE = "data/tasks.json"

class ServerManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.use_db = hasattr(bot, "db")
        self.tasks = {} if not self.use_db else None
        if not self.use_db:
            self.tasks = self._load_tasks()

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.bot.embed_color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=self.bot.footer)
        return embed

    def _load_tasks(self):
        if not os.path.exists(TASKS_FILE):
            return {}
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_tasks(self):
        os.makedirs("data", exist_ok=True)
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.tasks, f, indent=2)

    def _parse_due(self, text: str):
        if not text:
            return None
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        try:
            amount = int(text[:-1])
            unit = text[-1].lower()
            return int(time.time() + amount * units[unit])
        except Exception:
            return None

    async def _get_tasks(self, guild_id: str, assignee_id: str = None):
        if self.use_db:
            coll = self.bot.db["tasks"]
            query = {"guild_id": guild_id, "status": {"$ne": "complete"}}
            if assignee_id:
                query["assignee_id"] = assignee_id
            docs = await coll.find(query).to_list(length=100)
            return docs
        tasks = self.tasks.get(guild_id, {})
        result = [task for task in tasks.values() if task.get("status") != "complete"]
        if assignee_id:
            result = [task for task in result if task.get("assignee_id") == assignee_id]
        return result

    async def _get_task(self, guild_id: str, task_id: str):
        if self.use_db:
            coll = self.bot.db["tasks"]
            return await coll.find_one({"guild_id": guild_id, "task_id": task_id})
        return self.tasks.get(guild_id, {}).get(task_id)

    async def _save_task(self, task: dict):
        if self.use_db:
            coll = self.bot.db["tasks"]
            await coll.update_one(
                {"guild_id": task["guild_id"], "task_id": task["task_id"]},
                {"$set": task},
                upsert=True
            )
            return
        guild_tasks = self.tasks.setdefault(task["guild_id"], {})
        guild_tasks[task["task_id"]] = task
        self._save_tasks()

    async def _delete_task(self, guild_id: str, task_id: str):
        if self.use_db:
            coll = self.bot.db["tasks"]
            await coll.delete_one({"guild_id": guild_id, "task_id": task_id})
            return
        guild_tasks = self.tasks.get(guild_id, {})
        if task_id in guild_tasks:
            del guild_tasks[task_id]
            if not guild_tasks:
                self.tasks.pop(guild_id, None)
            self._save_tasks()

    # ==================== TASK MANAGEMENT ====================
    @commands.hybrid_command(name="task", description="Assign a task to a member", aliases=["assign", "assigntask"])
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(
        assignee="The member who will receive the task",
        title="A short title for the task",
        due="Optional due duration like 1h or 2d",
        details="Additional details for this task"
    )
    async def task(self, ctx: commands.Context, assignee: discord.Member, title: str, due: str = None, *, details: str = "No details provided"):
        guild_id = str(ctx.guild.id)
        due_at = self._parse_due(due) if due else None
        if due and due_at is None:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid Due", "Use a duration like `10m`, `1h`, or `2d`.", 0xFFAA00))

        task_id = uuid.uuid4().hex[:8]
        task = {
            "guild_id": guild_id,
            "task_id": task_id,
            "title": title,
            "details": details,
            "assignee_id": str(assignee.id),
            "assignee_name": str(assignee),
            "creator_id": str(ctx.author.id),
            "creator_name": str(ctx.author),
            "created_at": int(time.time()),
            "due_at": due_at,
            "status": "open"
        }
        await self._save_task(task)

        due_text = f"\n**Due:** <t:{due_at}:R>" if due_at else ""
        await ctx.send(embed=self.get_embed(
            "✅ Task Assigned",
            f"**Task:** {title}\n**Assigned to:** {assignee.mention}\n**ID:** `{task_id}`{due_text}"
        ))

    @commands.hybrid_command(name="tasks", description="List open tasks", aliases=["tasklist"])
    @app_commands.describe(member="Filter tasks by member")
    async def tasks(self, ctx: commands.Context, member: discord.Member = None):
        guild_id = str(ctx.guild.id)
        assignee_id = str(member.id) if member else None
        tasks = await self._get_tasks(guild_id, assignee_id)

        if not tasks:
            target = f"for {member.mention}" if member else "in this server"
            return await ctx.send(embed=self.get_embed("📋 No Tasks", f"No open tasks found {target}."))

        lines = []
        for task in tasks[:20]:
            due = f" • Due <t:{task['due_at']}:R>" if task.get("due_at") else ""
            lines.append(f"`{task['task_id']}` • **{task['title']}** — <@{task['assignee_id']}>{due}")

        description = "\n".join(lines)
        if len(tasks) > 20:
            description += f"\n…and {len(tasks) - 20} more tasks."

        embed = self.get_embed("📝 Open Tasks", description)
        embed.set_footer(text=f"Showing {min(len(tasks), 20)} of {len(tasks)} tasks")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="taskinfo", description="Show details for a task", aliases=["taskdetails"])
    @app_commands.describe(task_id="The ID of the task")
    async def taskinfo(self, ctx: commands.Context, task_id: str):
        guild_id = str(ctx.guild.id)
        task = await self._get_task(guild_id, task_id)
        if not task:
            return await ctx.send(embed=self.get_embed("❌ Not Found", f"No task found with ID `{task_id}`.", 0xFF0000))

        lines = [
            f"**Title:** {task['title']}",
            f"**Assigned to:** <@{task['assignee_id']}>",
            f"**Created by:** {task['creator_name']}",
            f"**Status:** {task.get('status', 'open').title()}"
        ]
        if task.get("due_at"):
            lines.append(f"**Due:** <t:{task['due_at']}:R>")
        if task.get("completed_at"):
            lines.append(f"**Completed:** <t:{task['completed_at']}:R>")
        lines.append(f"**Details:** {task['details']}")

        await ctx.send(embed=self.get_embed(f"📝 Task {task_id}", "\n".join(lines)))

    @commands.hybrid_command(name="taskcomplete", description="Mark a task complete", aliases=["done", "completetask"])
    @app_commands.describe(task_id="The ID of the task")
    async def taskcomplete(self, ctx: commands.Context, task_id: str):
        guild_id = str(ctx.guild.id)
        task = await self._get_task(guild_id, task_id)
        if not task:
            return await ctx.send(embed=self.get_embed("❌ Not Found", f"No task found with ID `{task_id}`.", 0xFF0000))

        if task["assignee_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.manage_guild:
            return await ctx.send(embed=self.get_embed("⛔ Permission Denied", "Only the assignee or a server manager can complete this task.", 0xFF0000))

        if task.get("status") == "complete":
            return await ctx.send(embed=self.get_embed("ℹ️ Already Complete", "This task is already marked complete."))

        task["status"] = "complete"
        task["completed_at"] = int(time.time())
        await self._save_task(task)
        await ctx.send(embed=self.get_embed("✅ Task Completed", f"Task `{task_id}` has been marked complete."))

    @commands.hybrid_command(name="taskremove", description="Delete a task", aliases=["removetask", "deletetask"])
    @app_commands.describe(task_id="The ID of the task")
    async def taskremove(self, ctx: commands.Context, task_id: str):
        guild_id = str(ctx.guild.id)
        task = await self._get_task(guild_id, task_id)
        if not task:
            return await ctx.send(embed=self.get_embed("❌ Not Found", f"No task found with ID `{task_id}`.", 0xFF0000))

        if task["assignee_id"] != str(ctx.author.id) and not ctx.author.guild_permissions.manage_guild:
            return await ctx.send(embed=self.get_embed("⛔ Permission Denied", "Only the assignee or a server manager can remove this task.", 0xFF0000))

        await self._delete_task(guild_id, task_id)
        await ctx.send(embed=self.get_embed("✅ Task Removed", f"Task `{task_id}` has been deleted."))

    # ==================== SERVER MANAGEMENT ====================
    @commands.hybrid_command(name="announce", description="Send an announcement to a channel")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @app_commands.describe(channel="Target announcement channel", title="Announcement title", message="Announcement body")
    async def announce(self, ctx: commands.Context, channel: discord.TextChannel, title: str, *, message: str):
        embed = self.get_embed(title, message)
        await channel.send(embed=embed)
        await ctx.send(embed=self.get_embed("✅ Announcement Sent", f"Announcement posted to {channel.mention}."))

    @commands.hybrid_command(name="setservername", description="Change the server name")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(name="The new server name")
    async def setservername(self, ctx: commands.Context, *, name: str):
        try:
            await ctx.guild.edit(name=name, reason=f"Updated by {ctx.author}")
            await ctx.send(embed=self.get_embed("✅ Server Renamed", f"Server name set to **{name}**."))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    @commands.hybrid_command(name="channelinfo", description="Get information about a channel")
    @app_commands.describe(channel="The channel to inspect")
    async def channelinfo(self, ctx: commands.Context, channel: discord.abc.GuildChannel = None):
        channel = channel or ctx.channel
        text = (
            f"ID: {channel.id}\n"
            f"Type: {channel.type}\n"
            f"Position: {channel.position}\n"
            f"NSFW: {getattr(channel, 'is_nsfw', lambda: False)()}\n"
            f"Category: {channel.category.name if channel.category else 'None'}\n"
        )
        if isinstance(channel, discord.TextChannel):
            text += f"Slowmode: {channel.slowmode_delay}s\n"
        await ctx.send(embed=self.get_embed(f"📌 Channel Info — {channel.name}", text))

    @commands.hybrid_command(name="dm", description="Send a DM to a member as the bot")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(member="The member to DM", message="The message to send")
    async def dm(self, ctx: commands.Context, member: discord.Member, *, message: str):
        embed = self.get_embed(f"📩 Message from {ctx.guild.name}", message)
        try:
            await member.send(embed=embed)
            await ctx.send(embed=self.get_embed("✅ DM Sent", f"Message delivered to {member.mention}."))
        except discord.Forbidden:
            await ctx.send(embed=self.get_embed("❌ Failed", f"{member.mention} has DMs disabled.", 0xFF0000))

    @commands.hybrid_command(name="createrole", description="Create a new role")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    @app_commands.describe(name="Name of the role", color="Hex color like #00ff9f", hoisted="Show role separately in the member list")
    async def createrole(self, ctx: commands.Context, name: str, color: str = None, hoisted: bool = False):
        role_color = discord.Color(self.bot.embed_color)
        if color:
            try:
                role_color = discord.Color(int(color.strip().lstrip("#"), 16))
            except ValueError:
                return await ctx.send(embed=self.get_embed("⚠️ Invalid Color", "Use a hex color like `#00ff9f`.", 0xFFAA00))
        try:
            role = await ctx.guild.create_role(name=name, color=role_color, hoist=hoisted, reason=f"Created by {ctx.author}")
            await ctx.send(embed=self.get_embed("✅ Role Created", f"Created {role.mention}."))
        except discord.Forbidden:
            await ctx.send(embed=self.get_embed("❌ Missing Permissions", "I need **Manage Roles** to do that.", 0xFF0000))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

async def setup(bot):
    await bot.add_cog(ServerManagement(bot))
