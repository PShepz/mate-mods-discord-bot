
import os
import asyncio
import datetime as dt
from typing import Dict, Any

import discord
from discord.ext import tasks, commands

# --- Tiny HTTP server so Render Free stays warm via external pings ---
# (Render Free Web Services sleep after ~15 min of no HTTP traffic)
from aiohttp import web  # aiohttp ships with discord.py

async def start_http_server():
    async def health(_):
        return web.json_response({"ok": True, "time": dt.datetime.now(dt.timezone.utc).isoformat()})

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
# --- end keep-alive server ---


# -------- Discord setup --------
intents = discord.Intents.default()  # message_content not required for this use-case
# If you later need to read message TEXT, enable below AND toggle in Dev Portal (see note in README).
# intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ----- Config: set via environment variables -----
def env_int(name: str, default: str) -> int:
    return int(os.getenv(name, default))

FACEBOOK_CHANNEL_ID = env_int("FACEBOOK_CHANNEL_ID", "123456789012345678")  # #facebook-posts
SPAM_CHANNEL_ID     = env_int("SPAM_CHANNEL_ID",     "123456789012345679")  # #spam-posts

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

# Per-channel state
STATE: Dict[int, Dict[str, Any]] = {
    # channel_id: {"last_message_at": datetime, "notified": bool}
}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    # Seed last_message_at from most recent message to avoid immediate reminders
    for channel_id in CONFIG.keys():
        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            async for msg in channel.history(limit=1):
                STATE[channel_id] = {"last_message_at": msg.created_at, "notified": False}
                break
            else:
                STATE[channel_id] = {"last_message_at": dt.datetime.now(dt.timezone.utc), "notified": False}
            print(f"Seeded channel {channel_id} at {STATE[channel_id]['last_message_at']}")
        except Exception as e:
            print(f"Seed warning for channel {channel_id}: {e}")
            STATE[channel_id] = {"last_message_at": dt.datetime.now(dt.timezone.utc), "notified": False}

    if not check_inactivity.is_running():
        check_inactivity.start()

@bot.event
async def on_message(message: discord.Message):
    if message.channel.id in CONFIG and not message.author.bot:
        STATE[message.channel.id] = {"last_message_at": message.created_at, "notified": False}
    await bot.process_commands(message)

@tasks.loop(minutes=1)
async def check_inactivity():
    now = dt.datetime.now(dt.timezone.utc)
    for channel_id, cfg in CONFIG.items():
        st = STATE.get(channel_id)
        if not st:
            STATE[channel_id] = {"last_message_at": now, "notified": False}
            continue

        last = st["last_message_at"]
        notified = st["notified"]
        threshold = cfg["threshold"]

        if (now - last) >= threshold and not notified:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            await channel.send(cfg["message"])
            st["notified"] = True
        elif (now - last) < threshold and notified:
            st["notified"] = False

# Optional: quick status command
@bot.command()
async def status(ctx: commands.Context):
    now = dt.datetime.now(dt.timezone.utc)
    lines = []
    for channel_id, cfg in CONFIG.items():
        st = STATE.get(channel_id, {})
        last = st.get("last_message_at")
        notified = st.get("notified", False)
        if last:
            elapsed = now - last
            remaining = cfg["threshold"] - elapsed
            lines.append(
                f"<#{channel_id}> — last: {last:%Y-%m-%d %H:%M:%S} UTC, "
                f"elapsed: {str(elapsed).split('.')[0]}, "
                f"until next reminder: {str(max(remaining, dt.timedelta(0))).split('.')[0]}, "
                f"notified={notified}"
            )
        else:
            lines.append(f"<#{channel_id}> — last: unknown")
    await ctx.send("\n".join(lines))


# ---------- Entry point ----------
async def main():
    await start_http_server()  # keep-alive server for Render Free
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN (or TOKEN) in your environment.")
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
