import discord
from discord.ext import commands
import os
import json
import asyncio
import logging
from urllib.parse import urlparse
from dotenv import load_dotenv
from keep_alive import start_background

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "cobrasystems")

# Load config
def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(data):
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

config = load_config()

# Install a safe logging formatter/handler to avoid formatting crashes from library logs
class _SafeFormatter(logging.Formatter):
    def format(self, record):
        try:
            return super().format(record)
        except Exception:
            # Best-effort fallback to avoid crashing logging in background threads
            try:
                message = record.getMessage()
            except Exception:
                message = str(record.msg)
            time = self.formatTime(record, self.datefmt) if hasattr(self, 'formatTime') else ''
            return f"{time} {record.levelname}: {message}"

root_logger = logging.getLogger()
# Ensure all handlers use the safe formatter to avoid formatting crashes; add a stream handler if none exist
safe_fmt = _SafeFormatter("%(asctime)s %(levelname)s: %(message)s")
if root_logger.handlers:
    for h in list(root_logger.handlers):
        try:
            h.setFormatter(safe_fmt)
        except Exception:
            pass
else:
    handler = logging.StreamHandler()
    handler.setFormatter(safe_fmt)
    root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True
intents.reactions = True
intents.moderation = True

bot = commands.Bot(
    command_prefix=commands.when_mentioned_or(config.get("prefix", "!")),
    intents=intents,
    owner_id=OWNER_ID,
    help_command=None,  # We'll make a custom one
    case_insensitive=True
)

# Initialize MongoDB if provided. The client connects lazily, so the actual
# connectivity check happens in setup_hook once the event loop is running.
if MONGO_URI:
    try:
        import motor.motor_asyncio
        mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        parsed_db_name = urlparse(MONGO_URI).path.strip("/")
        db_name = MONGO_DB_NAME or parsed_db_name or "cobrasystems"
        bot.mongo_client = mongo_client
        bot.db = mongo_client[db_name]
        bot.mongo_db_name = db_name
        print(f"🔌 MongoDB configured: {db_name}")
    except Exception as e:
        print(f"❌ Failed to initialize MongoDB: {e}")

bot.config = config
bot.save_config = lambda: save_config(bot.config)
bot.embed_color = config.get("embed_color", 0x00FF9F)
bot.footer = config.get("footer", "Cobra Systems™ Manager")

_original_context_send = commands.Context.send


async def send_response(ctx, *args, **kwargs):
    """Send a hidden (ephemeral) response for slash commands.

    Prefix commands keep their normal public replies; slash commands are
    hidden from everyone except the person who ran them.
    """
    interaction = getattr(ctx, "interaction", None)

    if interaction is None:
        kwargs.pop("ephemeral", None)
        return await _original_context_send(ctx, *args, **kwargs)

    kwargs.setdefault("ephemeral", True)
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(*args, **kwargs)
        return await interaction.response.send_message(*args, **kwargs)
    except (discord.NotFound, discord.HTTPException):
        fallback_kwargs = dict(kwargs)
        fallback_kwargs.pop("ephemeral", None)
        return await ctx.channel.send(*args, **fallback_kwargs)


async def send_public(ctx, *args, **kwargs):
    """Send a public channel message WITHOUT revealing who ran the command.

    The interaction is deferred ephemerally and the placeholder deleted, so
    the message appears as a standalone bot post with no "user used command"
    indicator attached to it.
    """
    kwargs.pop("ephemeral", None)
    interaction = getattr(ctx, "interaction", None)

    if interaction is None:
        return await _original_context_send(ctx, *args, **kwargs)

    if not interaction.response.is_done():
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.HTTPException, discord.NotFound):
            pass

    message = await ctx.channel.send(*args, **kwargs)

    try:
        await interaction.delete_original_response()
    except (discord.HTTPException, discord.NotFound):
        pass

    return message


async def _stealth_send(self, *args, **kwargs):
    """Patched ``Context.send`` used by every cog.

    * Prefix commands behave normally.
    * Slash commands are hidden (ephemeral) by default so nobody else can
      see the bot's response.
    * Passing ``ephemeral=False`` sends a *silent public* message instead:
      posted straight to the channel with no command usage shown.
    """
    interaction = getattr(self, "interaction", None)
    if interaction is None:
        kwargs.pop("ephemeral", None)
        return await _original_context_send(self, *args, **kwargs)

    ephemeral = kwargs.pop("ephemeral", True)
    if ephemeral:
        return await send_response(self, *args, **kwargs)
    return await send_public(self, *args, **kwargs)


commands.Context.send = _stealth_send

async def load_cogs():
    cogs = [
        "cogs.events",
        "cogs.moderation",
            "cogs.audit_logs",
        "cogs.roles",
        "cogs.utility",
        "cogs.admin",
        "cogs.automod",
        "cogs.economy",
        "cogs.leveling",
        "cogs.polls",
        "cogs.starboard",
        "cogs.giveaways",
        "cogs.tags",
        "cogs.backup",
        "cogs.stats",
        "cogs.server_management",
        "cogs.fun",
        "cogs.honeypot",
        "cogs.tickets",
        "cogs.yt_notifications",
    ]
    for cog in cogs:
        if cog in bot.extensions:
            print(f"↪️ Skipped already loaded {cog}")
            continue
        try:
            await bot.load_extension(cog)
            print(f"✅ Loaded {cog}")
        except Exception as e:
            print(f"❌ Failed to load {cog}: {e}")

@bot.event
async def setup_hook():
    # discord.py normally calls setup_hook once, but keeping this idempotent
    # prevents duplicate cogs/commands if startup is triggered more than once.
    if getattr(bot, "_setup_complete", False):
        print("↪️ setup_hook already completed; skipping duplicate startup")
        return
    bot._setup_complete = True

    if hasattr(bot, "mongo_client"):
        try:
            await bot.mongo_client.admin.command("ping")
            print(f"✅ Connected to MongoDB database: {bot.mongo_db_name}")
        except Exception as e:
            print(f"❌ MongoDB connection failed; using JSON fallback: {e}")
            bot.mongo_client.close()
            del bot.mongo_client
            del bot.db

    # If MongoDB is available, attempt to load global config from DB
    if hasattr(bot, "db"):
        try:
            coll = bot.db["config"]
            doc = await coll.find_one({"_id": "global"})
            if doc and isinstance(doc.get("data"), dict):
                bot.config = doc["data"]
                print("✅ Loaded config from MongoDB")
            else:
                # write current file config to DB as baseline
                await coll.update_one({"_id": "global"}, {"$set": {"data": bot.config}}, upsert=True)
                print("✅ Initialized config in MongoDB from file")
        except Exception as e:
            print(f"❌ Failed to load config from MongoDB: {e}")

    # Provide a save_config helper that writes to DB when available
    async def _save_config_db(data):
        try:
            await bot.db["config"].update_one({"_id": "global"}, {"$set": {"data": data}}, upsert=True)
        except Exception as e:
            print(f"❌ Failed to save config to DB: {e}")

    def save_config_generic():
        if hasattr(bot, "db"):
            asyncio.create_task(_save_config_db(bot.config))
        else:
            save_config(bot.config)

    bot.save_config = save_config_generic

    await load_cogs()
    # Register every loaded hybrid command. Guild sync is immediate and is
    # useful in Docker/development; global sync is kept for all other servers.
    try:
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"✅ Preloaded {len(synced)} slash command(s) to guild {guild_id}")
        else:
            synced = await bot.tree.sync()
            print(f"✅ Synced {len(synced)} global slash command(s)")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

@bot.event
async def on_ready():
    print(f"""
╔══════════════════════════════════════════════╗
║   Cobra Systems™ Manager is online!          ║
║   Logged in as: {bot.user}                   
║   ID: {bot.user.id}                          
║   Servers: {len(bot.guilds)}                 
╚══════════════════════════════════════════════╝
    """)
    # Set presence status without a visible activity. Use config key "status" or env BOT_STATUS.
    status_str = bot.config.get("status", os.getenv("BOT_STATUS", "dnd")).lower()
    status_map = {
        "online": discord.Status.online,
        "idle": discord.Status.idle,
        "dnd": discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    status = status_map.get(status_str, discord.Status.dnd)
    try:
        await bot.change_presence(status=status)
    except Exception:
        # Fallback: set to dnd if anything goes wrong
        try:
            await bot.change_presence(status=discord.Status.dnd)
        except Exception:
            pass

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="⛔ Missing Permissions",
            description="You don't have the required permissions to use this command.",
            color=0xFF0000
        )
        await send_response(ctx, embed=embed, ephemeral=True if getattr(ctx, "interaction", None) else False)
        return
    if isinstance(error, commands.BotMissingPermissions):
        embed = discord.Embed(
            title="⛔ Bot Missing Permissions",
            description="I don't have the required permissions to do that.",
            color=0xFF0000
        )
        await send_response(ctx, embed=embed)
        return
    if isinstance(error, commands.CheckFailure):
        embed = discord.Embed(
            title="⛔ Permission Denied",
            description="This command is restricted to the bot owner, server owner, or server administrators.",
            color=0xFF0000,
        )
        await send_response(ctx, embed=embed, ephemeral=True if getattr(ctx, "interaction", None) else False)
        return
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="⚠️ Missing Argument",
            description=f"Missing required argument: `{error.param.name}`",
            color=0xFFAA00
        )
        await send_response(ctx, embed=embed)
        return
    # Generic
    print(f"Error in {ctx.command}: {error}")
    embed = discord.Embed(
        title="❌ Error",
        description=str(error),
        color=0xFF0000
    )
    await send_response(ctx, embed=embed)

if __name__ == "__main__":
    if not TOKEN:
        print("❌ No DISCORD_TOKEN found in .env file!")
    else:
        # Start simple keep-alive webserver so hosting providers don't put the process to sleep
        try:
            port = int(os.getenv("PORT", "8080"))
            start_background(port=port)
            print(f"✅ Keep-alive server started on port {port}")
        except Exception:
            pass
        bot.run(TOKEN)