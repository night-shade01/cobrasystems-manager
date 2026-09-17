import discord
from discord.ext import commands
from discord import app_commands
import textwrap
import traceback
import inspect
import importlib
import asyncio
import io
import contextlib
import os
import json

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # Owner-only controls live under a single slash group (counts as 1 of the 100 global command slots).
    bot_group = app_commands.Group(name="bot", description="Bot owner controls")

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.bot.embed_color,
        )
        embed.set_footer(text=self.bot.footer)
        return embed

    @commands.is_owner()
    @commands.hybrid_group(name="bot", description="Bot owner controls", fallback="shutdown")
    async def bot_group_cmd(self, ctx: commands.Context):
        """`/bot shutdown` — shut down the bot (owner only)."""
        await ctx.send(embed=self.get_embed("⏹️ Shutting down", "Bye!"))
        await self.bot.close()

    @commands.is_owner()
    @bot_group.command(name="shutdown", description="Shut down the bot (owner only)")
    async def shutdown(self, ctx: commands.Context):
        await ctx.send(embed=self.get_embed("⏹️ Shutting down", "Bye!"))
        await self.bot.close()

    @commands.is_owner()
    @bot_group.command(name="reload", description="Reload an extension (owner only)")
    async def reload(self, ctx: commands.Context, extension: str):
        try:
            await self.bot.unload_extension(extension)
            await self.bot.load_extension(extension)
            await ctx.send(embed=self.get_embed("✅ Reloaded", f"{extension} reloaded."))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    @commands.is_owner()
    @bot_group.command(name="load", description="Load an extension (owner only)")
    async def load(self, ctx: commands.Context, extension: str):
        try:
            await self.bot.load_extension(extension)
            await ctx.send(embed=self.get_embed("✅ Loaded", f"{extension} loaded."))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    @commands.is_owner()
    @bot_group.command(name="unload", description="Unload an extension (owner only)")
    async def unload(self, ctx: commands.Context, extension: str):
        try:
            await self.bot.unload_extension(extension)
            await ctx.send(embed=self.get_embed("✅ Unloaded", f"{extension} unloaded."))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    @commands.is_owner()
    @bot_group.command(name="sync", description="Sync application commands (owner only)")
    async def sync(self, ctx: commands.Context, spec: str = None):
        try:
            if spec == "~":
                synced = await self.bot.tree.sync(guild=ctx.guild)
            else:
                synced = await self.bot.tree.sync()
            await ctx.send(embed=self.get_embed("✅ Synced", f"Synced {len(synced)} commands."))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    @commands.is_owner()
    @bot_group.command(name="eval", description="Evaluate Python code (owner only)")
    async def _eval(self, ctx: commands.Context, *, body: str):
        env = {
            'bot': self.bot,
            'ctx': ctx,
            'guild': ctx.guild,
            'channel': ctx.channel,
            'author': ctx.author,
            '__import__': __import__
        }
        body = body.strip('` ')
        stdout = io.StringIO()
        to_compile = f'async def func():\n{textwrap.indent(body, "    ")}'
        try:
            exec(to_compile, env)
        except Exception as e:
            return await ctx.send(embed=self.get_embed("❌ Compile Error", f"``\n{e}\n```", 0xFF0000))
        func = env['func']
        try:
            with contextlib.redirect_stdout(stdout):
                ret = await func()
        except Exception as e:
            value = stdout.getvalue()
            tb = traceback.format_exc()
            return await ctx.send(embed=self.get_embed("❌ Runtime Error", f"``\n{value}{tb}\n```", 0xFF0000))
        value = stdout.getvalue()
        if ret is None and not value:
            await ctx.send(embed=self.get_embed("✅ Evaluated", "No output."))
        else:
            out = f"{value}{ret or ''}"
            if len(out) > 1900:
                out = out[:1900] + "..."
            await ctx.send(embed=self.get_embed("✅ Eval Result", f"``\n{out}\n```"))

    @commands.is_owner()
    @bot_group.command(name="migrate_config", description="Migrate local config.json to MongoDB (owner only)")
    async def migrate_config_to_db(self, ctx: commands.Context):
        if not hasattr(self.bot, "db"):
            return await ctx.send(embed=self.get_embed("❌ No DB", "MongoDB not configured."))
        try:
            # read file
            with open("config.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            await self.bot.db["config"].update_one({"_id": "global"}, {"$set": {"data": data}}, upsert=True)
            await ctx.send(embed=self.get_embed("✅ Migrated", "config.json has been migrated to MongoDB."))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    @commands.is_owner()
    @bot_group.command(name="export_config", description="Export config from DB to local config.json (owner only)")
    async def export_config(self, ctx: commands.Context):
        if not hasattr(self.bot, "db"):
            return await ctx.send(embed=self.get_embed("❌ No DB", "MongoDB not configured."))
        try:
            doc = await self.bot.db["config"].find_one({"_id": "global"})
            if not doc or not isinstance(doc.get("data"), dict):
                return await ctx.send(embed=self.get_embed("❌ Not Found", "No config document found in DB.", 0xFF0000))
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(doc["data"], f, indent=2)
            await ctx.send(embed=self.get_embed("✅ Exported", "Config exported to config.json"))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Failed", str(e), 0xFF0000))

    @commands.is_owner()
    @bot_group.command(name="migrate_json", description="Migrate existing JSON stores (warnings, reminders, reaction_roles, giveaways) into MongoDB")
    async def migrate_json_to_db(self, ctx: commands.Context):
        if not hasattr(self.bot, "db"):
            return await ctx.send(embed=self.get_embed("❌ No DB", "MongoDB not configured."))

        summary = {}

        # Warnings
        try:
            warnings_file = os.path.join("data", "warnings.json")
            count = 0
            if os.path.exists(warnings_file):
                with open(warnings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # data format: {guild_id: {user_id: [warns]}}
                for gid, users in data.items():
                    for uid, warns in users.items():
                        if not warns:
                            continue
                        await self.bot.db["warnings"].update_one({"guild_id": gid, "user_id": uid}, {"$set": {"warnings": warns}}, upsert=True)
                        count += len(warns)
            summary["warnings_migrated"] = count
        except Exception as e:
            summary["warnings_error"] = str(e)

        # Reminders
        try:
            reminders_file = os.path.join("data", "reminders.json")
            rcount = 0
            if os.path.exists(reminders_file):
                with open(reminders_file, "r", encoding="utf-8") as f:
                    rdata = json.load(f)
                # rdata: {user_id: [reminders]}
                for user_id, items in rdata.items():
                    for r in items:
                        # upsert by user_id + id
                        await self.bot.db["reminders"].update_one({"user_id": user_id, "id": r.get("id")}, {"$set": {**r, "user_id": user_id}}, upsert=True)
                        rcount += 1
            summary["reminders_migrated"] = rcount
        except Exception as e:
            summary["reminders_error"] = str(e)

        # Reaction roles from config
        try:
            rr = self.bot.config.get("reaction_roles", {})
            rr_count = 0
            for gid, msgs in rr.items():
                for mid, data in msgs.items():
                    doc = {"guild_id": gid, "message_id": mid, "emoji": data.get("emoji"), "role_id": data.get("role_id"), "channel_id": data.get("channel_id")}
                    await self.bot.db["reaction_roles"].update_one({"guild_id": gid, "message_id": mid}, {"$set": doc}, upsert=True)
                    rr_count += 1
            summary["reaction_roles_migrated"] = rr_count
            # remove from local config
            if rr_count:
                self.bot.config.pop("reaction_roles", None)
                try:
                    self.bot.save_config()
                except Exception:
                    pass
        except Exception as e:
            summary["reaction_roles_error"] = str(e)

        # Giveaways from config
        try:
            gvs = self.bot.config.get("giveaways", [])
            gcount = 0
            for g in gvs:
                await self.bot.db["giveaways"].insert_one(g)
                gcount += 1
            summary["giveaways_migrated"] = gcount
            if gcount:
                self.bot.config.pop("giveaways", None)
                try:
                    self.bot.save_config()
                except Exception:
                    pass
        except Exception as e:
            summary["giveaways_error"] = str(e)

        # Starboard
        try:
            sb = self.bot.config.get("starboard", {})
            sbcount = 0
            for gid, cid in sb.items():
                await self.bot.db["starboard"].update_one({"guild_id": gid}, {"$set": {"channel_id": cid}}, upsert=True)
                sbcount += 1
            summary["starboard_migrated"] = sbcount
            if sbcount:
                self.bot.config.pop("starboard", None)
                try:
                    self.bot.save_config()
                except Exception:
                    pass
        except Exception as e:
            summary["starboard_error"] = str(e)

        # Final summary
        text = "\n".join(f"{k}: {v}" for k, v in summary.items())
        await ctx.send(embed=self.get_embed("✅ Migration Complete", text))

async def setup(bot):
    await bot.add_cog(Admin(bot))
