
import os
import asyncio
import datetime as dt
from typing import Dict, Any

import discord
from discord.ext import tasks, commands

# Timezone setup for London
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    LONDON_TZ = ZoneInfo("Europe/London")
except ImportError:
    import pytz
    LONDON_TZ = pytz.timezone("Europe/London")

# --- Tiny HTTP server to keep Render Free alive ---
from aiohttp import web

async def start_http_server():
    async def health(_):
        return web.json_response({"ok": True, "time": dt.datetime.now(LONDON_TZ).isoformat()})

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"HTTP health server listening on :{port}")
    return runner

# -------- Discord setup --------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ----- Config -----
def env_int(name: str, default: str) -> int:
    return int(os.getenv(name, default))

FACEBOOK_CHANNEL_ID = env_int("FACEBOOK_CHANNEL_ID", "123456789012345678")
SPAM_CHANNEL_ID     = env_int("SPAM_CHANNEL_ID",     "123456789012345679")

CONFIG = {
    FACEBOOK_CHANNEL_ID: {
        "threshold": dt.timedelta(hours=1),
        "message": os.getenv("FACEBOOK_MESSAGE", "post needed."),
    },
    SPAM_CHANNEL_ID: {
        "threshold": dt.timedelta(hours=2),
        "message": os.getenv("SPAM_MESSAGE", "post needed."),
    },
}

STATE: Dict[int, Dict[str, Any]] = {}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    for channel_id in CONFIG.keys():
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            async for msg in channel.history(limit=1):
                STATE[channel_id] = {"last_message_at": msg.created_at.astimezone(LONDON_TZ)}
                break
            else:
                STATE[channel_id] = {"last_message_at": dt.datetime.now(LONDON_TZ)}
            print(f"Seeded channel {channel_id} at {STATE[channel_id]['last_message_at']}")
        except Exception as e:
            print(f"Seed warning for channel {channel_id}: {e}")
            STATE[channel_id] = {"last_message_at": dt.datetime.now(LONDON_TZ)}

    if not check_inactivity.is_running():
        check_inactivity.start()

@bot.event
async def on_message(message: discord.Message):
    if message.channel.id in CONFIG and not message.author.bot:
        STATE[message.channel.id] = {"last_message_at": message.created_at.astimezone(LONDON_TZ)}
    await bot.process_commands(message)

@tasks.loop(minutes=1)
async def check_inactivity():
    now = dt.datetime.now(LONDON_TZ)
    for channel_id, cfg in CONFIG.items():
        st = STATE.get(channel_id)
        if not st:
            STATE[channel_id] = {"last_message_at": now}
            continue

        last = st["last_message_at"]
        threshold = cfg["threshold"]

        if (now - last) >= threshold and now.minute == 0:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            await channel.send(cfg["message"])

@bot.command()
async def status(ctx: commands.Context):
    now = dt.datetime.now(LONDON_TZ)
    lines = []
    for channel_id, cfg in CONFIG.items():
        st = STATE.get(channel_id, {})
        last = st.get("last_message_at")
        if last:
            elapsed = now - last
            remaining = cfg["threshold"] - elapsed
            lines.append(
                f"<#{channel_id}> — last: {last:%Y-%m-%d %H:%M:%S} London time, "
                f"elapsed: {str(elapsed).split('.')[0]}, "
                f"until next reminder: {str(max(remaining, dt.timedelta(0))).split('.')[0]}"
            )
        else:
            lines.append(f"<#{channel_id}> — last: unknown")
    await ctx.send("\n".join(lines))

# ---------- Entry point ----------
async def main():
    await start_http_server()
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN (or TOKEN) in your environment.")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
