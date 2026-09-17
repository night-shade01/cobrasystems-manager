import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime

class Tags(commands.Cog):
    """User-defined tags/snippets stored in DB or config."""
    def __init__(self, bot):
        self.bot = bot

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(title=title, description=description, color=color or self.bot.embed_color, timestamp=datetime.utcnow())
        embed.set_footer(text=self.bot.footer)
        return embed

    @commands.hybrid_group(name="tag", description="Create and view server tags", fallback="show")
    @app_commands.describe(name="The tag to show")
    async def tag(self, ctx: commands.Context, name: str = None):
        """`/tag show <name>` — display a tag's content publicly."""
        if name is None:
            return await self.list_tags(ctx)
        await self._show_tag(ctx, name)

    async def _show_tag(self, ctx: commands.Context, name: str):
        gid = str(ctx.guild.id)
        if hasattr(self.bot, "db"):
            doc = await self.bot.db["tags"].find_one({"guild_id": gid, "name": name})
            if not doc:
                return await ctx.send(embed=self.get_embed("❌ Not Found", "Tag not found.", 0xFF0000))
            return await ctx.send(doc.get("content"), ephemeral=False)
        else:
            content = self.bot.config.get("tags", {}).get(gid, {}).get(name)
            if not content:
                return await ctx.send(embed=self.get_embed("❌ Not Found", "Tag not found.", 0xFF0000))
            await ctx.send(content, ephemeral=False)

    @tag.command(name="create", description="Create a tag")
    @commands.has_permissions(manage_guild=True)
    async def tagcreate(self, ctx: commands.Context, name: str, *, content: str):
        gid = str(ctx.guild.id)
        if hasattr(self.bot, "db"):
            await self.bot.db["tags"].update_one({"guild_id": gid, "name": name}, {"$set": {"content": content}}, upsert=True)
        else:
            self.bot.config.setdefault("tags", {}).setdefault(gid, {})[name] = content
            self.bot.save_config()
        await ctx.send(embed=self.get_embed("✅ Created", f"Tag `{name}` saved."))

    @tag.command(name="delete", description="Delete a tag")
    @commands.has_permissions(manage_guild=True)
    async def tagdelete(self, ctx: commands.Context, name: str):
        gid = str(ctx.guild.id)
        if hasattr(self.bot, "db"):
            res = await self.bot.db["tags"].delete_one({"guild_id": gid, "name": name})
            if not res.deleted_count:
                return await ctx.send(embed=self.get_embed("❌ Not Found", "Tag not found.", 0xFF0000))
        else:
            tags = self.bot.config.get("tags", {}).get(gid, {})
            if name not in tags:
                return await ctx.send(embed=self.get_embed("❌ Not Found", "Tag not found.", 0xFF0000))
            del tags[name]
            self.bot.save_config()
        await ctx.send(embed=self.get_embed("✅ Deleted", f"Tag `{name}` deleted."))

    @tag.command(name="list", description="List all tags in this server")
    async def list_tags(self, ctx: commands.Context):
        gid = str(ctx.guild.id)
        if hasattr(self.bot, "db"):
            docs = await self.bot.db["tags"].find({"guild_id": gid}).to_list(length=100)
            names = [d.get("name") for d in docs]
        else:
            names = list(self.bot.config.get("tags", {}).get(gid, {}).keys())
        if not names:
            return await ctx.send(embed=self.get_embed("🏷️ Tags", "No tags have been created yet."))
        formatted = ", ".join(f"`{n}`" for n in sorted(names)[:100])
        await ctx.send(embed=self.get_embed(f"🏷️ Tags [{len(names)}]", formatted))

async def setup(bot):
    await bot.add_cog(Tags(bot))
