import asyncio
import io
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime


TICKET_TYPES = {
    "support": {
        "label": "Support",
        "emoji": "🆘",
        "description": "Open a support ticket for help or questions.",
    },
    "purchase": {
        "label": "Purchase",
        "emoji": "🛒",
        "description": "Open a ticket for buying or order-related questions.",
    },
    "bugs": {
        "label": "Bugs",
        "emoji": "🐞",
        "description": "Report bugs or technical issues here.",
    },
    "other": {
        "label": "Other",
        "emoji": "💬",
        "description": "Open a ticket for anything else.",
    },
}


class TicketPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    def _get_guild_settings(self, guild_id: int):
        return self.bot.config.get("tickets", {}).get(str(guild_id), {})

    def _ticket_exists(self, guild: discord.Guild, member: discord.Member):
        for channel in guild.text_channels:
            topic = channel.topic or ""
            if topic.startswith("ticket|") and f"|{member.id}|" in topic:
                return channel
        return None

    async def _build_transcript(self, channel: discord.TextChannel):
        buffer = io.StringIO()
        buffer.write(f"Transcript for #{channel.name}\n")
        buffer.write(f"Channel ID: {channel.id}\n")
        buffer.write(f"Guild: {channel.guild.name}\n")
        buffer.write(f"Created: {datetime.utcnow().isoformat()} UTC\n")
        buffer.write("-" * 80 + "\n\n")

        messages = []
        async for message in channel.history(limit=None, oldest_first=True):
            messages.append(message)

        for message in messages:
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = message.content or ""
            attachments = " ".join(a.url for a in message.attachments)
            embeds = f" [embeds: {len(message.embeds)}]" if message.embeds else ""
            if attachments:
                content = f"{content} {attachments}".strip()
            buffer.write(f"[{timestamp}] {message.author} ({message.author.id}): {content}{embeds}\n")

        buffer.seek(0)
        return discord.File(fp=io.BytesIO(buffer.read().encode("utf-8")), filename=f"transcript-{channel.name}.txt")

    async def _send_ticket_log(self, guild: discord.Guild, embed: discord.Embed, transcript: discord.File = None):
        settings = self._get_guild_settings(guild.id)
        log_channel_id = settings.get("log_channel_id")
        if not log_channel_id:
            return

        log_channel = guild.get_channel(log_channel_id)
        if log_channel is None:
            return

        try:
            if transcript:
                await log_channel.send(embed=embed, file=transcript)
            else:
                await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass

    async def _create_ticket(self, interaction: discord.Interaction, ticket_type: str):
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return

        settings = self._get_guild_settings(guild.id)
        category_id = settings.get("category_id")
        support_role_id = settings.get("support_role_id")

        if category_id:
            category = guild.get_channel(category_id)
        else:
            category = None

        if category is None:
            category = interaction.channel.category if interaction.channel else None

        if category is None:
            try:
                category = await guild.create_category("Tickets", reason="Ticket system setup")
                self.bot.config.setdefault("tickets", {}).setdefault(str(guild.id), {})["category_id"] = category.id
                self.bot.save_config()
            except discord.Forbidden:
                return await interaction.response.send_message(
                    "I need **Manage Channels** to create the ticket category.",
                    ephemeral=True,
                )

        existing = self._ticket_exists(guild, member)
        if existing:
            return await interaction.response.send_message(
                f"You already have an open ticket: {existing.mention}",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)

        bot_member = guild.me or guild.get_member(self.bot.user.id)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
        }

        if bot_member:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )

        if support_role_id:
            support_role = guild.get_role(int(support_role_id))
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True,
                )

        ticket_name = f"{ticket_type}-{member.name}".lower().replace(" ", "-")[:90]
        topic = f"ticket|{ticket_type}|{member.id}|opened:{datetime.utcnow().isoformat()}"

        try:
            channel = await guild.create_text_channel(
                name=ticket_name,
                category=category,
                topic=topic,
                overwrites=overwrites,
                reason=f"Ticket opened by {member}",
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "I couldn't create the ticket channel. Please make sure I have **Manage Channels**.",
                ephemeral=True,
            )

        embed = discord.Embed(
            title=f"{TICKET_TYPES[ticket_type]['emoji']} {TICKET_TYPES[ticket_type]['label']} Ticket",
            description=(
                f"Thanks for opening a **{TICKET_TYPES[ticket_type]['label']}** ticket, {member.mention}.\n\n"
                f"Please describe your issue or request clearly so the team can help faster."
            ),
            color=self.bot.embed_color,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=self.bot.footer)

        content = member.mention
        if support_role_id:
            support_role = guild.get_role(int(support_role_id))
            if support_role:
                content = f"{member.mention} {support_role.mention}"

        await channel.send(embed=embed, content=content, view=TicketCloseView(self.bot))
        await interaction.followup.send(f"Your ticket is ready: {channel.mention}", ephemeral=True)

    @discord.ui.button(
        label="Support",
        style=discord.ButtonStyle.primary,
        emoji="🆘",
        custom_id="ticket:create:support",
    )
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "support")

    @discord.ui.button(
        label="Purchase",
        style=discord.ButtonStyle.success,
        emoji="🛒",
        custom_id="ticket:create:purchase",
    )
    async def purchase_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "purchase")

    @discord.ui.button(
        label="Bugs",
        style=discord.ButtonStyle.danger,
        emoji="🐞",
        custom_id="ticket:create:bugs",
    )
    async def bugs_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "bugs")

    @discord.ui.button(
        label="Other",
        style=discord.ButtonStyle.secondary,
        emoji="💬",
        custom_id="ticket:create:other",
    )
    async def other_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._create_ticket(interaction, "other")


class TicketCloseView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    def _is_ticket_channel(self, channel: discord.TextChannel):
        return bool(channel.topic and channel.topic.startswith("ticket|"))

    def _ticket_owner_id(self, channel: discord.TextChannel):
        if not channel.topic:
            return None
        parts = channel.topic.split("|")
        if len(parts) < 3:
            return None
        try:
            return int(parts[2])
        except ValueError:
            return None

    def _ticket_type(self, channel: discord.TextChannel):
        if not channel.topic:
            return None
        parts = channel.topic.split("|")
        if len(parts) < 2:
            return None
        return parts[1]

    async def _close_ticket(self, channel: discord.TextChannel, closer: discord.abc.User, *, log_reason: str):
        await channel.send(embed=discord.Embed(title="🔒 Ticket Closing", description="This ticket will be deleted shortly.", color=self.bot.embed_color))

        transcript = None
        try:
            transcript = await TicketPanelView(self.bot)._build_transcript(channel)
        except Exception:
            transcript = None

        ticket_type = self._ticket_type(channel)
        owner_id = self._ticket_owner_id(channel)
        owner_mention = f"<@{owner_id}>" if owner_id else "Unknown"

        log_embed = discord.Embed(
            title="🎫 Ticket Closed",
            description=(
                f"**Channel:** {channel.mention}\n"
                f"**Ticket Type:** {ticket_type or 'unknown'}\n"
                f"**Opened By:** {owner_mention}\n"
                f"**Closed By:** {closer.mention if hasattr(closer, 'mention') else str(closer)}\n"
                f"**Reason:** {log_reason}"
            ),
            color=self.bot.embed_color,
            timestamp=datetime.utcnow(),
        )
        log_embed.set_footer(text=self.bot.footer)

        await TicketPanelView(self.bot)._send_ticket_log(channel.guild, log_embed, transcript)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket:close",
    )
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or not self._is_ticket_channel(channel):
            return await interaction.response.send_message("This button only works inside ticket channels.", ephemeral=True)

        owner_id = self._ticket_owner_id(channel)
        is_owner = interaction.user.id == owner_id
        can_manage = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_channels

        if not is_owner and not can_manage:
            return await interaction.response.send_message("Only the ticket opener or staff can close this ticket.", ephemeral=True)

        await interaction.response.send_message("Closing ticket in 3 seconds...", ephemeral=True)
        await asyncio.sleep(3)
        await self._close_ticket(channel, interaction.user, log_reason="Closed via button")
        await channel.delete(reason=f"Ticket closed by {interaction.user}")


class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.bot.embed_color,
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text=self.bot.footer)
        return embed

    @commands.hybrid_command(name="ticketpanel", description="Post a ticket panel for support, purchase, bugs, and other")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True, send_messages=True, embed_links=True)
    @app_commands.describe(
        channel="Channel to post the panel in (defaults to this channel)",
        category="Category where ticket channels will be created",
        support_role="Optional support role to ping in new tickets",
        log_channel="Optional channel where ticket transcripts and close logs are sent",
    )
    async def ticketpanel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel = None,
        category: discord.CategoryChannel = None,
        support_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
    ):
        panel_channel = channel or ctx.channel
        if not isinstance(panel_channel, discord.TextChannel):
            return await ctx.send(embed=self.get_embed("❌ Invalid Channel", "Please choose a text channel for the panel.", 0xFF0000))

        guild = ctx.guild
        guild_id = str(guild.id)

        if category is None:
            category = panel_channel.category

        if category is None:
            try:
                category = await guild.create_category("Tickets", reason="Ticket panel setup")
            except discord.Forbidden:
                return await ctx.send(embed=self.get_embed("❌ Missing Permissions", "I need **Manage Channels** to create the ticket category.", 0xFF0000))

        tickets_cfg = self.bot.config.setdefault("tickets", {})
        tickets_cfg.setdefault(guild_id, {})["category_id"] = category.id
        if support_role is not None:
            tickets_cfg[guild_id]["support_role_id"] = support_role.id
        if log_channel is not None:
            tickets_cfg[guild_id]["log_channel_id"] = log_channel.id
        self.bot.save_config()

        embed = self.get_embed(
            "🎫 Open a Ticket",
            (
                "Choose the category that best fits your request.\n\n"
                "- 🆘 **Support** — help, questions, account issues\n"
                "- 🛒 **Purchase** — buying or order-related requests\n"
                "- 🐞 **Bugs** — report issues or bugs\n"
                "- 💬 **Other** — anything else"
            )
        )
        embed.add_field(name="Category", value=category.mention, inline=True)
        embed.add_field(name="Support Role", value=support_role.mention if support_role else "None", inline=True)
        embed.add_field(name="Ticket Log", value=log_channel.mention if log_channel else "None", inline=True)

        if ctx.interaction:
            await ctx.interaction.response.defer(ephemeral=True, thinking=True)

        await panel_channel.send(embed=embed, view=TicketPanelView(self.bot))

        confirmation = self.get_embed("✅ Ticket Panel Posted", f"The ticket panel is now live in {panel_channel.mention}.")
        if ctx.interaction:
            await ctx.interaction.followup.send(embed=confirmation, ephemeral=True)
        else:
            await ctx.send(embed=confirmation)

    @commands.hybrid_command(name="ticketclose", description="Close the current ticket")
    @commands.bot_has_permissions(manage_channels=True)
    async def ticketclose(self, ctx: commands.Context):
        channel = ctx.channel
        if not isinstance(channel, discord.TextChannel) or not channel.topic or not channel.topic.startswith("ticket|"):
            return await ctx.send(embed=self.get_embed("ℹ️ Not a Ticket", "This command only works inside a ticket channel."))

        owner_id = int(channel.topic.split("|")[2])
        is_owner = ctx.author.id == owner_id
        can_manage = ctx.author.guild_permissions.manage_channels

        if not is_owner and not can_manage:
            return await ctx.send(embed=self.get_embed("⛔ Not Allowed", "Only the ticket opener or staff can close this ticket.", 0xFF0000))

        await ctx.send(embed=self.get_embed("🔒 Closing Ticket", "This ticket will be deleted in 3 seconds."), ephemeral=False)
        await asyncio.sleep(3)
        try:
            close_view = TicketCloseView(self.bot)
            await close_view._close_ticket(channel, ctx.author, log_reason="Closed via command")
        except Exception:
            pass
        await channel.delete(reason=f"Ticket closed by {ctx.author}")

    @commands.hybrid_command(name="ticketrename", description="Rename the current ticket channel")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe(name="New ticket channel name")
    async def ticketrename(self, ctx: commands.Context, *, name: str):
        channel = ctx.channel
        if not isinstance(channel, discord.TextChannel) or not channel.topic or not channel.topic.startswith("ticket|"):
            return await ctx.send(embed=self.get_embed("ℹ️ Not a Ticket", "This command only works inside a ticket channel."))

        safe_name = name.lower().strip().replace(" ", "-")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")[:90]
        if not safe_name:
            return await ctx.send(embed=self.get_embed("❌ Invalid Name", "Please provide a valid channel name." , 0xFF0000))

        await channel.edit(name=safe_name, reason=f"Ticket renamed by {ctx.author}")
        await ctx.send(embed=self.get_embed("✅ Renamed", f"Ticket renamed to `{safe_name}`."), ephemeral=False)


async def setup(bot):
    bot.add_view(TicketPanelView(bot))
    bot.add_view(TicketCloseView(bot))
    await bot.add_cog(Tickets(bot))