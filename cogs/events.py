import discord
from discord.ext import commands
from datetime import datetime

class Events(commands.Cog):
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

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Leave immediately when a previously blocked server invites the bot back."""
        blocked_guilds = self.bot.config.get("blocked_guilds", [])
        if guild.id in blocked_guilds or str(guild.id) in blocked_guilds:
            try:
                await guild.leave()
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        guild_id = str(guild.id)

        # Auto Role
        auto_roles = self.bot.config.get("auto_role", {})
        if guild_id in auto_roles:
            role_id = auto_roles[guild_id]
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto Role")
                except discord.Forbidden:
                    pass

        # Welcome Message
        welcome_channels = self.bot.config.get("welcome_channel", {})
        if guild_id in welcome_channels:
            channel = guild.get_channel(welcome_channels[guild_id])
            if channel:
                embed = self.get_embed(
                    title=f"Welcome to {guild.name}!",
                    description=(
                        f"Hey {member.mention}! Welcome to **{guild.name}**.\n\n"
                        f"You are member **#{guild.member_count}**.\n"
                        f"Make sure to read the rules and have fun!"
                    )
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                if guild.icon:
                    embed.set_author(name=guild.name, icon_url=guild.icon.url)
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass

        # Member join logging is handled in the dedicated audit logging cog.

async def setup(bot):
    await bot.add_cog(Events(bot))