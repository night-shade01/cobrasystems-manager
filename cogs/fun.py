import discord
from discord.ext import commands
from discord import app_commands
import random
import aiohttp
from datetime import datetime

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.jokes = [
            "I told my computer I needed a break, and it said 'No problem — I'll go to sleep.'",
            "Why do programmers prefer dark mode? Because light attracts bugs.",
            "There are only 10 types of people in the world: those who understand binary, and those who don't."
        ]
        self.eightball_answers = [
            "It is certain.", "Without a doubt.", "Yes, definitely.", "Most likely.",
            "Signs point to yes.", "Ask again later.", "Cannot predict now.",
            "Don't count on it.", "My reply is no.", "Very doubtful.",
            "Absolutely not.", "Yes — trust the snake. 🐍"
        ]

    def get_embed(self, title: str, description: str = None, color=None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.bot.embed_color,
            timestamp=datetime.utcnow()
        )
        embed.set_footer(text=self.bot.footer)
        return embed

    @commands.hybrid_command(name="coin", description="Flip a coin")
    async def coin(self, ctx: commands.Context):
        res = random.choice(["Heads", "Tails"])
        await ctx.send(embed=self.get_embed("🪙 Coin Flip", f"Result: **{res}**"))

    @commands.hybrid_command(name="roll", description="Roll dice (e.g. 2d6, d20)")
    @app_commands.describe(sides="Dice expression like 2d6 or d20")
    async def roll(self, ctx: commands.Context, sides: str = "1d6"):
        try:
            if 'd' not in sides:
                return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Use format like `2d6` or `d20`.", 0xFFAA00))
            parts = sides.lower().split('d')
            count = int(parts[0]) if parts[0] else 1
            die = int(parts[1])
            if count < 1 or count > 100 or die < 2 or die > 10000:
                return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Dice out of allowed range.", 0xFFAA00))
            rolls = [random.randint(1, die) for _ in range(count)]
            total = sum(rolls)
            await ctx.send(embed=self.get_embed("🎲 Roll", f"Rolls: {rolls}\nTotal: **{total}**"))
        except Exception as e:
            await ctx.send(embed=self.get_embed("❌ Error", str(e), 0xFF0000))

    @commands.hybrid_command(name="choose", description="Choose between multiple options")
    async def choose(self, ctx: commands.Context, *, options: str):
        opts = [o.strip() for o in options.split(",") if o.strip()]
        if len(opts) < 2:
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Provide at least two comma-separated options.", 0xFFAA00))
        pick = random.choice(opts)
        await ctx.send(embed=self.get_embed("🎯 Choice", f"I pick: **{pick}**"))

    @commands.hybrid_command(name="joke", description="Tell a silly joke")
    async def joke(self, ctx: commands.Context):
        await ctx.send(embed=self.get_embed("😂 Joke", random.choice(self.jokes)))

    @commands.hybrid_command(name="rps", description="Play rock-paper-scissors")
    async def rps(self, ctx: commands.Context, choice: str):
        choice = choice.lower()
        if choice not in ("rock", "paper", "scissors"):
            return await ctx.send(embed=self.get_embed("⚠️ Invalid", "Choose rock, paper, or scissors.", 0xFFAA00))
        bot_choice = random.choice(["rock", "paper", "scissors"])
        if choice == bot_choice:
            result = "Tie"
        elif (choice == "rock" and bot_choice == "scissors") or (choice == "paper" and bot_choice == "rock") or (choice == "scissors" and bot_choice == "paper"):
            result = "You Win"
        else:
            result = "You Lose"
        await ctx.send(embed=self.get_embed("✊ Rock Paper Scissors", f"You: **{choice}**\nBot: **{bot_choice}**\nResult: **{result}**"))

    @commands.hybrid_command(name="8ball", description="Ask the magic 8-ball a question")
    @app_commands.describe(question="The question to ask")
    async def eightball(self, ctx: commands.Context, *, question: str):
        answer = random.choice(self.eightball_answers)
        await ctx.send(embed=self.get_embed("🎱 Magic 8-Ball", f"**Q:** {question}\n**A:** {answer}"))

    @commands.hybrid_command(name="rate", description="Rate anything out of 10")
    @app_commands.describe(thing="What to rate")
    async def rate(self, ctx: commands.Context, *, thing: str):
        score = random.randint(0, 10)
        await ctx.send(embed=self.get_embed("📊 Rating", f"I rate **{thing}** a solid **{score}/10**."))

    @commands.hybrid_command(name="ship", description="Check the compatibility between two members")
    @app_commands.describe(first="First member", second="Second member (defaults to you)")
    async def ship(self, ctx: commands.Context, first: discord.Member, second: discord.Member = None):
        second = second or ctx.author
        if first.id == second.id:
            return await ctx.send(embed=self.get_embed("💔 Ship", "You can't ship someone with themselves.", 0xFFAA00))
        # Deterministic-ish score so repeat ships match
        score = (first.id + second.id) % 101
        bar_filled = round(score / 10)
        bar = "🟥" * bar_filled + "⬛" * (10 - bar_filled)
        if score >= 80:
            verdict = "A match made in heaven! 💞"
        elif score >= 50:
            verdict = "There's definitely something there. 😏"
        elif score >= 25:
            verdict = "Could work with some effort. 🤷"
        else:
            verdict = "It's not looking great... 💔"
        await ctx.send(embed=self.get_embed(
            "💘 Ship Meter",
            f"{first.mention} ❤️ {second.mention}\n\n{bar} **{score}%**\n{verdict}",
        ))

    @commands.hybrid_command(name="mock", description="sPoNgEbOb mock some text")
    @app_commands.describe(text="Text to mock")
    async def mock(self, ctx: commands.Context, *, text: str):
        mocked = "".join(c.upper() if random.random() < 0.5 else c.lower() for c in text)
        await ctx.send(embed=self.get_embed("🧽 Mock", mocked[:1900]))

    @commands.hybrid_command(name="emojify", description="Turn text into letter emojis")
    @app_commands.describe(text="Text to emojify (letters and numbers)")
    async def emojify(self, ctx: commands.Context, *, text: str):
        out = []
        for c in text.lower():
            if "a" <= c <= "z":
                out.append(f":regional_indicator_{c}:")
            elif c.isdigit():
                digits = {"0": "0️⃣", "1": "1️⃣", "2": "2️⃣", "3": "3️⃣", "4": "4️⃣", "5": "5️⃣", "6": "6️⃣", "7": "7️⃣", "8": "8️⃣", "9": "9️⃣"}
                out.append(digits[c])
            elif c == " ":
                out.append("   ")
            else:
                out.append(c)
        result = "".join(out)
        if len(result) > 1900:
            return await ctx.send(embed=self.get_embed("⚠️ Too Long", "That text is too long to emojify.", 0xFFAA00))
        await ctx.send(embed=self.get_embed("🔤 Emojified", result))

    @commands.hybrid_command(name="reverse", description="Reverse some text")
    @app_commands.describe(text="Text to reverse")
    async def reverse(self, ctx: commands.Context, *, text: str):
        await ctx.send(embed=self.get_embed("🔄 Reversed", text[::-1][:1900]))

    @commands.hybrid_command(name="clap", description="Add 👏 between 👏 every 👏 word")
    @app_commands.describe(text="Text to clap-ify")
    async def clap(self, ctx: commands.Context, *, text: str):
        await ctx.send(embed=self.get_embed("👏 Clap", " 👏 ".join(text.split())[:1900]))

    @commands.hybrid_command(name="catfact", description="Get a random cat fact")
    async def catfact(self, ctx: commands.Context):
        fact = None
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://catfact.ninja/fact") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        fact = data.get("fact")
        except Exception:
            fact = None
        if not fact:
            fact = "Cats sleep for around 70% of their lives. 😺"
        await ctx.send(embed=self.get_embed("🐱 Cat Fact", fact))

    @commands.hybrid_command(name="dogpic", description="Get a random dog picture")
    async def dogpic(self, ctx: commands.Context):
        url = None
        try:
            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://dog.ceo/api/breeds/image/random") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        url = data.get("message")
        except Exception:
            url = None
        if not url:
            return await ctx.send(embed=self.get_embed("❌ Error", "Couldn't fetch a dog picture right now. Try again later.", 0xFF0000))
        embed = self.get_embed("🐶 Random Dog")
        embed.set_image(url=url)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Fun(bot))
