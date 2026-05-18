import os
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv
import discord


# =========================
# LOAD ENV
# =========================

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)


def get_secret(name):
    value = os.getenv(name)

    if value:
        return value

    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        return None


def get_discord_config():
    token = get_secret("DISCORD_TOKEN")
    channel_id = get_secret("DISCORD_CHANNEL_ID")

    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN.")

    if not channel_id:
        raise RuntimeError("Missing DISCORD_CHANNEL_ID.")

    try:
        channel_id = int(channel_id)
    except ValueError as exc:
        raise RuntimeError("DISCORD_CHANNEL_ID must be a number.") from exc

    return token, channel_id


# =========================
# POP ITEM EMOJI MAP
# =========================

POP_EMOJIS = {
    "gemoftheeast": "Gem of the East",
    "springstone": "Springstone",

    "gemofthesouth": "Gem of the South",
    "summerstone": "Summerstone",

    "autumnstone": "Autumnstone",
    "gemofthewest": "Gem of the West",

    "winterstone": "Winterstone",
    "gemofthenorth": "Gem of the North",
}


# =========================
# FETCH DISCORD INVENTORY
# =========================

async def fetch_discord_inventory(limit=500):
    token, channel_id = get_discord_config()

    intents = discord.Intents.default()
    intents.guilds = True
    intents.messages = True
    intents.reactions = True

    # keep these OFF unless enabled in Discord portal
    intents.message_content = False
    intents.members = False

    client = discord.Client(intents=intents)

    inventory = defaultdict(list)

    @client.event
    async def on_ready():

        print(f"Logged in as {client.user}")

        channel = client.get_channel(channel_id)

        if channel is None:
            print("Could not find Discord channel.")
            await client.close()
            return

        print(f"Reading channel: {channel.name}")

        async for message in channel.history(limit=limit):

            for reaction in message.reactions:

                emoji = reaction.emoji

                emoji_name = (
                    emoji.name
                    if hasattr(emoji, "name")
                    else str(emoji)
                )

                emoji_key = emoji_name.lower()

                print("FOUND REACTION:", emoji_key)

                if emoji_key not in POP_EMOJIS:
                    continue

                item_name = POP_EMOJIS[emoji_key]

                async for user in reaction.users():

                    if user.bot:
                        continue

                    player_name = user.display_name

                    if item_name not in inventory[player_name]:
                        inventory[player_name].append(item_name)

                        print(
                            f"Added {item_name} to {player_name}"
                        )

        await client.close()

    await client.start(token)

    return dict(inventory)
