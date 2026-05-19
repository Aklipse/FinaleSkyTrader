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


def get_discord_config(channel_secret="DISCORD_CHANNEL_ID", default_channel_id=None):
    token = get_secret("DISCORD_TOKEN")
    channel_id = get_secret(channel_secret)

    if not channel_id and channel_secret != "DISCORD_CHANNEL_ID":
        channel_id = get_secret("DISCORD_CHANNEL_ID")

    if not channel_id:
        channel_id = default_channel_id

    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN.")

    if not channel_id:
        raise RuntimeError(f"Missing {channel_secret}.")

    try:
        channel_id = int(channel_id)
    except ValueError as exc:
        raise RuntimeError("DISCORD_CHANNEL_ID must be a number.") from exc

    return token, channel_id


def message_matches_event(message, event_name):
    event_name = event_name.lower()

    if event_name in (message.content or "").lower():
        return True

    for embed in message.embeds:
        parts = [
            embed.title or "",
            embed.description or "",
            embed.author.name if embed.author else "",
            embed.footer.text if embed.footer else "",
        ]
        parts.extend(field.name or "" for field in embed.fields)

        if event_name in "\n".join(parts).lower():
            return True

    return False


def field_is_attending(field_name):
    field_name = field_name.lower()
    blocked_words = [
        "absent",
        "absence",
        "bench",
        "declined",
        "not attending",
        "unavailable",
        "waitlist",
    ]

    return not any(word in field_name for word in blocked_words)


def clean_raidhelper_name(line, mention_lookup):
    line = line.strip()

    if not line or line in {"-", "—", "n/a", "N/A"}:
        return ""

    for user_id, display_name in mention_lookup.items():
        line = line.replace(f"<@{user_id}>", display_name)
        line = line.replace(f"<@!{user_id}>", display_name)

    line = line.replace("`", "")
    line = line.replace("*", "")

    if "." in line:
        prefix, rest = line.split(".", 1)

        if prefix.strip().isdigit():
            line = rest

    line = line.split(" - ", 1)[0]
    line = line.split(" | ", 1)[0]
    line = line.split(" (", 1)[0]
    line = line.strip("•-–— \t")

    return " ".join(line.split())


def extract_raidhelper_attendees(message):
    mention_lookup = {
        str(user.id): user.display_name
        for user in message.mentions
        if not user.bot
    }
    attendees = []

    for embed in message.embeds:
        for field in embed.fields:
            if not field_is_attending(field.name or ""):
                continue

            for line in (field.value or "").splitlines():
                name = clean_raidhelper_name(line, mention_lookup)

                if name and not name.lower().startswith(("empty", "none")):
                    attendees.append(name)

    seen = set()
    clean = []

    for attendee in attendees:
        key = attendee.lower()

        if key not in seen:
            seen.add(key)
            clean.append(attendee)

    return clean


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


async def fetch_raidhelper_attendees(event_name="Friday Sky", limit=100):
    token, channel_id = get_discord_config(
        "DISCORD_SIGNUP_CHANNEL_ID",
        default_channel_id="1383458990121291837",
    )

    intents = discord.Intents.default()
    intents.guilds = True
    intents.messages = True
    intents.reactions = False
    intents.message_content = False
    intents.members = False

    client = discord.Client(intents=intents)
    attendees = []

    @client.event
    async def on_ready():
        nonlocal attendees

        print(f"Logged in as {client.user}")

        channel = client.get_channel(channel_id)

        if channel is None:
            try:
                channel = await client.fetch_channel(channel_id)
            except discord.DiscordException:
                print("Could not find Discord signup channel.")
                await client.close()
                return

        print(f"Reading signup channel: {channel.name}")

        async for message in channel.history(limit=limit):
            if not message_matches_event(message, event_name):
                continue

            attendees = extract_raidhelper_attendees(message)

            if attendees:
                break

        await client.close()

    await client.start(token)

    return attendees
