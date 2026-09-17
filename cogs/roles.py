import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import json

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.bot.embed_color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=self.bot.footer)
        return embed

    # ==================== AUTO ROLE ====================
    @commands.hybrid_command(name="autorole", description="Set or remove the auto role for new members")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    @app_commands.describe(role="The role to give on join (leave empty to disable)")
    async def autorole(self, ctx: commands.Context, role: discord.Role = None):
        guild_id = str(ctx.guild.id)
        if role is None:
            if guild_id in self.bot.config.get("auto_role", {}):
                del self.bot.config["auto_role"][guild_id]
                self.bot.save_config()
                await ctx.send(embed=self.get_embed("✅ Auto Role Disabled", "Auto role has been disabled."))
            else:
                await ctx.send(embed=self.get_embed("ℹ️ Info", "No auto role is currently set."))
            return

        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot assign a role higher than or equal to my highest role.", 0xFF0000))

        if "auto_role" not in self.bot.config:
            self.bot.config["auto_role"] = {}
        self.bot.config["auto_role"][guild_id] = role.id
        self.bot.save_config()

        await ctx.send(embed=self.get_embed(
            "✅ Auto Role Set",
            f"New members will automatically receive {role.mention}."
        ))

    # ==================== WELCOME CHANNEL ====================
    @commands.hybrid_command(name="welcome", description="Set the welcome channel")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(channel="The channel for welcome messages (leave empty to disable)")
    async def welcome(self, ctx: commands.Context, channel: discord.TextChannel = None):
        guild_id = str(ctx.guild.id)
        if channel is None:
            if guild_id in self.bot.config.get("welcome_channel", {}):
                del self.bot.config["welcome_channel"][guild_id]
                self.bot.save_config()
                await ctx.send(embed=self.get_embed("✅ Welcome Disabled", "Welcome messages have been disabled."))
            else:
                await ctx.send(embed=self.get_embed("ℹ️ Info", "No welcome channel is currently set."))
            return

        if "welcome_channel" not in self.bot.config:
            self.bot.config["welcome_channel"] = {}
        self.bot.config["welcome_channel"][guild_id] = channel.id
        self.bot.save_config()
        await ctx.send(embed=self.get_embed("✅ Welcome Channel Set", f"Welcome messages will be sent in {channel.mention}."))

    # ==================== LOG CHANNEL ====================
    @commands.hybrid_command(name="setlog", description="Set the moderation log channel")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(channel="The channel for logs (leave empty to disable)")
    async def setlog(self, ctx: commands.Context, channel: discord.TextChannel = None):
        guild_id = str(ctx.guild.id)
        if channel is None:
            if guild_id in self.bot.config.get("log_channel", {}):
                del self.bot.config["log_channel"][guild_id]
                self.bot.save_config()
                await ctx.send(embed=self.get_embed("✅ Logs Disabled", "Logging has been disabled."))
            else:
                await ctx.send(embed=self.get_embed("ℹ️ Info", "No log channel is currently set."))
            return

        if "log_channel" not in self.bot.config:
            self.bot.config["log_channel"] = {}
        self.bot.config["log_channel"][guild_id] = channel.id
        self.bot.save_config()
        await ctx.send(embed=self.get_embed("✅ Log Channel Set", f"Logs will be sent in {channel.mention}."))

    # ==================== REACTION ROLES ====================
    @commands.hybrid_command(name="reactionrole", description="Create a reaction role message", aliases=["rr"])
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True, add_reactions=True, manage_messages=True)
    @app_commands.describe(
        title="Title of the embed",
        description="Description / instructions",
        emoji="Emoji to react with",
        role="Role to give when reacted"
    )
    async def reactionrole(self, ctx: commands.Context, title: str, description: str, emoji: str, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot assign a role higher than or equal to my highest role.", 0xFF0000))

        embed = self.get_embed(title, description)
        embed.add_field(name="Role", value=role.mention, inline=True)
        embed.add_field(name="Emoji", value=emoji, inline=True)

        msg = await ctx.send(embed=embed, ephemeral=False)
        try:
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            await msg.delete()
            return await ctx.send(embed=self.get_embed("❌ Invalid Emoji", "Could not react with that emoji. Make sure it's a valid emoji I can use.", 0xFF0000))

        # Save to config
        guild_id = str(ctx.guild.id)
        if "reaction_roles" not in self.bot.config:
            self.bot.config["reaction_roles"] = {}
        if guild_id not in self.bot.config["reaction_roles"]:
            self.bot.config["reaction_roles"][guild_id] = {}

        # Store by message ID
        self.bot.config["reaction_roles"][guild_id][str(msg.id)] = {
            "emoji": str(emoji),
            "role_id": role.id,
            "channel_id": ctx.channel.id
        }
        self.bot.save_config()

        # Confirm privately if possible
        confirm = self.get_embed("✅ Reaction Role Created", f"Users can now react with {emoji} to get {role.mention}.\nMessage ID: `{msg.id}`")
        if ctx.interaction:
            await ctx.interaction.followup.send(embed=confirm, ephemeral=True)
        else:
            # Already sent the main message, just leave it
            pass

    @commands.hybrid_command(name="removereactionrole", description="Remove a reaction role by message ID", aliases=["rrr"])
    @commands.has_permissions(manage_roles=True)
    @app_commands.describe(message_id="The ID of the reaction role message")
    async def removereactionrole(self, ctx: commands.Context, message_id: str):
        guild_id = str(ctx.guild.id)
        rr = self.bot.config.get("reaction_roles", {}).get(guild_id, {})
        if message_id not in rr:
            return await ctx.send(embed=self.get_embed("❌ Not Found", "No reaction role found with that message ID.", 0xFF0000))

        del self.bot.config["reaction_roles"][guild_id][message_id]
        self.bot.save_config()
        await ctx.send(embed=self.get_embed("✅ Removed", f"Reaction role for message `{message_id}` has been removed."))

    # ==================== REACTION LISTENERS ====================
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        guild_id = str(guild.id)
        rr_data = self.bot.config.get("reaction_roles", {}).get(guild_id, {}).get(str(payload.message_id))
        if not rr_data:
            return

        # Match emoji
        emoji_str = str(payload.emoji)
        if emoji_str != rr_data["emoji"] and payload.emoji.name != rr_data["emoji"]:
            return

        role = guild.get_role(rr_data["role_id"])
        if not role:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        try:
            await member.add_roles(role, reason="Reaction Role")
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        guild_id = str(guild.id)
        rr_data = self.bot.config.get("reaction_roles", {}).get(guild_id, {}).get(str(payload.message_id))
        if not rr_data:
            return

        emoji_str = str(payload.emoji)
        if emoji_str != rr_data["emoji"] and payload.emoji.name != rr_data["emoji"]:
            return

        role = guild.get_role(rr_data["role_id"])
        if not role:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            return

        try:
            await member.remove_roles(role, reason="Reaction Role Removed")
        except discord.Forbidden:
            pass

    # ==================== ROLE GIVE / TAKE ====================
    @commands.hybrid_command(name="giverole", description="Give a role to a member")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    @app_commands.describe(member="The member", role="The role to give")
    async def giverole(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot assign that role.", 0xFF0000))
        if role in member.roles:
            return await ctx.send(embed=self.get_embed("ℹ️ Info", f"{member.mention} already has {role.mention}."))
        await member.add_roles(role, reason=f"Given by {ctx.author}")
        await ctx.send(embed=self.get_embed("✅ Role Given", f"Gave {role.mention} to {member.mention}."))

    @commands.hybrid_command(name="takerole", description="Remove a role from a member")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    @app_commands.describe(member="The member", role="The role to remove")
    async def takerole(self, ctx: commands.Context, member: discord.Member, role: discord.Role):
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=self.get_embed("⛔ Hierarchy Error", "I cannot remove that role.", 0xFF0000))
        if role not in member.roles:
            return await ctx.send(embed=self.get_embed("ℹ️ Info", f"{member.mention} doesn't have {role.mention}."))
        await member.remove_roles(role, reason=f"Removed by {ctx.author}")
        await ctx.send(embed=self.get_embed("✅ Role Removed", f"Removed {role.mention} from {member.mention}."))

async def setup(bot):
    await bot.add_cog(Roles(bot))