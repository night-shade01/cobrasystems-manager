import os
import aiohttp
import asyncio
import discord
from discord.ext import commands
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timezone


class YTNotifications(commands.Cog):
    """Poll YouTube channel feeds and post new uploads to configured discord channels."""

    def __init__(self, bot):
        self.bot = bot
        self.session: aiohttp.ClientSession = None
        self.task = None
        self.api_key = os.getenv("YT_API_KEY")

    async def cog_load(self):
        # Created inside the running event loop (unlike __init__, which may run before it)
        self.session = aiohttp.ClientSession()
        self.task = asyncio.create_task(self.loop_poll())

    def cog_unload(self):
        try:
            if self.task:
                self.task.cancel()
        except Exception:
            pass
        try:
            if self.session:
                asyncio.create_task(self.session.close())
        except Exception:
            pass

    async def loop_poll(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.check_feeds()
            except Exception:
                pass
            await asyncio.sleep(self.bot.config.get("yt_poll_interval", 60))

    async def check_feeds(self):
        subs = self.bot.config.get("youtube_subscriptions", [])
        # subs: list of dicts {"channel_id": "UCxxx", "guild_id": "123", "notify_channel": 456}
        for sub in list(subs):
            channel_id = sub.get("channel_id")
            # resolve if not a UC id
            if channel_id and not channel_id.startswith("UC"):
                channel_id = await self.resolve_channel_id(channel_id)
                if not channel_id:
                    continue
                sub["channel_id"] = channel_id
                self.bot.save_config()
            guild_id = int(sub.get("guild_id"))
            notify_channel_id = int(sub.get("notify_channel"))
            notify_role_id = sub.get("notify_role")
            # Prefer API if key is available
            vid = None
            title_text = None
            thumbnail = None
            channel_title = None
            published_at = None
            description = None
            if self.api_key:
                try:
                    latest = await self.get_latest_video_via_api(channel_id)
                    if latest:
                        vid = latest.get("videoId")
                        title_text = latest.get("title")
                        thumbnail = latest.get("thumbnail")
                        channel_title = latest.get("channelTitle")
                        published_at = latest.get("publishedAt")
                        description = latest.get("description")
                except Exception:
                    vid = None

            # Fallback to RSS feed if API not available or failed
            if not vid:
                feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
                try:
                    async with self.session.get(feed_url, timeout=20) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            root = ET.fromstring(text)
                            entry = root.find('{http://www.w3.org/2005/Atom}entry')
                            if entry is None:
                                continue
                            video_id = entry.find('{http://www.youtube.com/xml/schemas/2015}videoId')
                            title = entry.find('{http://www.w3.org/2005/Atom}title')
                            media_thumbnail = entry.find('{http://search.yahoo.com/mrss/}group/{http://search.yahoo.com/mrss/}thumbnail')
                            if video_id is None or title is None:
                                continue
                            vid = video_id.text
                            title_text = title.text
                            if media_thumbnail is not None and 'url' in media_thumbnail.attrib:
                                thumbnail = media_thumbnail.attrib['url']
                except Exception:
                    continue

            if not vid:
                continue

            last_seen = self.bot.config.setdefault("yt_last", {}).get(channel_id)
            if last_seen == vid:
                continue

            # new video
            self.bot.config.setdefault("yt_last", {})[channel_id] = vid
            self.bot.save_config()
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            channel = guild.get_channel(notify_channel_id)
            if not channel:
                continue
            video_url = f"https://www.youtube.com/watch?v={vid}"
            embed = discord.Embed(
                title=title_text or "New YouTube Upload",
                url=video_url,
                color=self.bot.embed_color,
            )
            embed.description = description[:4000] if description else None
            embed.add_field(name="Channel", value=channel_title or f"`{channel_id}`", inline=True)
            embed.add_field(name="Video ID", value=f"`{vid}`", inline=True)
            embed.add_field(name="Video Link", value=f"[Watch here]({video_url})", inline=True)
            if published_at:
                try:
                    dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                    embed.add_field(name="Published", value=f"<t:{int(dt.timestamp())}:F>", inline=True)
                    embed.add_field(name="Age", value=f"<t:{int(dt.timestamp())}:R>", inline=True)
                except Exception:
                    pass
            if thumbnail:
                embed.set_thumbnail(url=thumbnail)
            embed.set_author(name=channel_title or "YouTube Upload", icon_url="https://www.youtube.com/s/desktop/9f83f27e/img/favicon_144x144.png")
            embed.set_footer(text=f"New YouTube upload • Channel ID: {channel_id}")
            content = None
            allowed_mentions = discord.AllowedMentions(everyone=False, users=False, roles=bool(notify_role_id))
            if notify_role_id:
                guild = self.bot.get_guild(guild_id)
                role = guild.get_role(int(notify_role_id)) if guild else None
                if role:
                    content = role.mention
            try:
                await channel.send(content=content, embed=embed, allowed_mentions=allowed_mentions)
            except Exception:
                pass

    async def resolve_channel_id(self, identifier: str) -> str | None:
        """Resolve various YouTube identifiers (handles, URLs, usernames) to a UC channel id.
        Returns UC... or None."""
        ident = identifier.strip()
        # direct UC id
        if ident.startswith("UC"):
            return ident

        # If a URL contains /channel/UC..., extract it
        m = re.search(r"/channel/(UC[0-9A-Za-z_-]{20,})", ident)
        if m:
            return m.group(1)

        # If it's a full URL or handle starting with @, try using the Data API if available
        if self.api_key:
            # Normalize handle: remove leading @ for query
            q = ident.lstrip("@")
            params = {
                "part": "snippet",
                "type": "channel",
                "q": q,
                "maxResults": 1,
                "key": self.api_key,
            }
            url = "https://www.googleapis.com/youtube/v3/search"
            try:
                async with self.session.get(url, params=params, timeout=20) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    items = data.get("items") or []
                    if not items:
                        return None
                    # channel id may be in snippet.channelId or id.channelId
                    item = items[0]
                    cid = None
                    if item.get("snippet") and item["snippet"].get("channelId"):
                        cid = item["snippet"]["channelId"]
                    elif item.get("id") and item["id"].get("channelId"):
                        cid = item["id"]["channelId"]
                    return cid
            except Exception:
                return None

        # Fallback: try to scrape the page HTML
        try:
            test_url = ident if "youtube.com" in ident else f"https://www.youtube.com/{ident.lstrip('@')}"
            async with self.session.get(test_url, timeout=20) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
                m = re.search(r'"channelId"\s*:\s*"(UC[0-9A-Za-z_-]{20,})"', text)
                if not m:
                    m = re.search(r'"externalId"\s*:\s*"(UC[0-9A-Za-z_-]{20,})"', text)
                if not m:
                    m = re.search(r"/channel/(UC[0-9A-Za-z_-]{20,})", text)
                if m:
                    return m.group(1)
        except Exception:
            return None

        return None

    async def get_latest_video_via_api(self, channel_id: str) -> dict | None:
        """Return a dict with videoId, title, thumbnail for the latest upload using YouTube Data API."""
        if not self.api_key:
            return None
        # Get uploads playlist id
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {"part": "contentDetails", "id": channel_id, "key": self.api_key}
        try:
            async with self.session.get(url, params=params, timeout=20) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                items = data.get("items") or []
                if not items:
                    return None
                uploads = items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                if not uploads:
                    return None

            # fetch most recent playlist item
            url2 = "https://www.googleapis.com/youtube/v3/playlistItems"
            params2 = {"part": "snippet", "playlistId": uploads, "maxResults": 1, "key": self.api_key}
            async with self.session.get(url2, params=params2, timeout=20) as resp2:
                if resp2.status != 200:
                    return None
                data2 = await resp2.json()
                items2 = data2.get("items") or []
                if not items2:
                    return None
                snip = items2[0].get("snippet", {})
                resource = snip.get("resourceId", {})
                vid = resource.get("videoId")
                title = snip.get("title")
                desc = snip.get("description")
                channel_title = snip.get("channelTitle")
                published_at = snip.get("publishedAt")
                thumbs = snip.get("thumbnails", {})
                thumb = None
                for key in ("maxres", "high", "medium", "default"):
                    if thumbs.get(key) and thumbs[key].get("url"):
                        thumb = thumbs[key]["url"]
                        break
                return {
                    "videoId": vid,
                    "title": title,
                    "description": desc,
                    "channelTitle": channel_title,
                    "publishedAt": published_at,
                    "thumbnail": thumb,
                }
        except Exception:
            return None

    @commands.hybrid_command(name="ytsub", description="Subscribe this server to a YouTube channel")
    @commands.has_permissions(manage_guild=True)
    async def ytsub(self, ctx, channel_identifier: str, notify_channel: discord.TextChannel = None, notify_role: discord.Role = None):
        """Subscribe this server to a YouTube channel's uploads. channel_identifier may be a channel ID or full channel URL.
        Example: !ytsub UC_xxx #youtube @Updates"""
        cid_raw = channel_identifier.strip()

        resolved = None
        if cid_raw.startswith("UC"):
            resolved = cid_raw
        else:
            # Try API resolution first when available
            if self.api_key:
                resolved = await self.resolve_channel_id(cid_raw)
            # Fallback to scraping
            if not resolved:
                test_url = cid_raw if ("youtube.com" in cid_raw or "youtu.be" in cid_raw) else f"https://www.youtube.com/{cid_raw.lstrip('@')}"
                try:
                    async with self.session.get(test_url, timeout=20) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            m = re.search(r'"channelId"\s*:\s*"(UC[0-9A-Za-z_-]{20,})"', text)
                            if not m:
                                m = re.search(r'"externalId"\s*:\s*"(UC[0-9A-Za-z_-]{20,})"', text)
                            if not m:
                                m = re.search(r"/channel/(UC[0-9A-Za-z_-]{20,})", text)
                            if m:
                                resolved = m.group(1)
                except Exception:
                    resolved = None

        if not resolved or not resolved.startswith("UC"):
            await ctx.send("Please provide a channel ID (starts with UC) or a full channel URL/handle that can be resolved.")
            return

        notify_channel = notify_channel or ctx.channel
        subs = self.bot.config.setdefault("youtube_subscriptions", [])
        subs.append({
            "channel_id": resolved,
            "guild_id": str(ctx.guild.id),
            "notify_channel": notify_channel.id,
            "notify_role": notify_role.id if notify_role else None,
        })
        self.bot.save_config()
        role_text = f" and ping {notify_role.mention}" if notify_role else ""
        await ctx.send(f"Subscribed to uploads from `{resolved}` and will notify in {notify_channel.mention}{role_text}.")

    @commands.hybrid_command(name="ytunsub", description="Remove a YouTube subscription from this server")
    @commands.has_permissions(manage_guild=True)
    async def ytunsub(self, ctx, channel_id: str):
        subs = self.bot.config.setdefault("youtube_subscriptions", [])
        before = len(subs)
        subs = [s for s in subs if not (s.get("channel_id") == channel_id and s.get("guild_id") == str(ctx.guild.id))]
        self.bot.config["youtube_subscriptions"] = subs
        self.bot.save_config()
        await ctx.send(f"Unsubscribed `{channel_id}` for this server.")


async def setup(bot):
    await bot.add_cog(YTNotifications(bot))
