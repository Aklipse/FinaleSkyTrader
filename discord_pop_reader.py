import os
import re
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
    event_terms = [
        term
        for term in event_name.lower().split()
        if term
    ]
    searchable_parts = [message.content or ""]

    for embed in message.embeds:
        searchable_parts.extend([
            embed.title or "",
            embed.description or "",
            embed.author.name if embed.author else "",
            embed.footer.text if embed.footer else "",
        ])
        searchable_parts.extend(field.name or "" for field in embed.fields)
        searchable_parts.extend(field.value or "" for field in embed.fields)

    for component in message.components:
        for child in getattr(component, "children", []):
            searchable_parts.append(getattr(child, "label", "") or "")
            searchable_parts.append(getattr(child, "custom_id", "") or "")

    searchable = "\n".join(searchable_parts).lower()

    if event_name.lower() in searchable:
        return True

    return all(term in searchable for term in event_terms)


def text_matches_event(text, event_name):
    text = (text or "").lower()
    event_name = event_name.lower()
    event_terms = [
        term
        for term in event_name.split()
        if term
    ]

    if event_name in text:
        return True

    return all(term in text for term in event_terms)


def component_labels(message):
    labels = []

    for component in message.components:
        for child in getattr(component, "children", []):
            label = getattr(child, "label", "") or ""
            custom_id = getattr(child, "custom_id", "") or ""

            if label:
                labels.append(label)

            if custom_id:
                labels.append(custom_id)

    return labels


def field_is_attending(field_name, field_value=""):
    field_name = field_name.lower()
    field_value = field_value.lower()
    blocked_words = [
        "absent",
        "absence",
        "bench",
        "declined",
        "not attending",
        "unavailable",
        "waitlist",
    ]

    attending_words = [
        "accepted",
        "attending",
        "confirmed",
        "going",
        "signed",
        "signup",
        "yes",
    ]

    if any(word in field_name for word in blocked_words):
        return False

    if any(word in field_name for word in attending_words):
        return True

    return "<@" in field_value


def line_looks_like_name(line):
    lowered = line.lower()
    blocked = [
        "accepted",
        "attending",
        "bench",
        "declined",
        "empty",
        "maybe",
        "not attending",
        "signup",
        "tentative",
        "unavailable",
        "waitlist",
        "web view",
    ]

    if any(word in lowered for word in blocked):
        return False

    has_signup_marker = "✅" in line or "☑" in line or "<:" in line
    has_numbered_name = bool(
        re.search(r"^\W*\d{1,2}[\).]?\s+\S+", line)
    )

    return has_numbered_name or (
        has_signup_marker
        and bool(re.search(r"\d{1,2}[\).]?\s+\S+", line))
    )


def clean_raidhelper_name(line, mention_lookup):
    line = line.strip()

    if not line or line in {"-", "—", "n/a", "N/A"}:
        return ""

    for user_id, display_name in mention_lookup.items():
        line = line.replace(f"<@{user_id}>", display_name)
        line = line.replace(f"<@!{user_id}>", display_name)

    line = line.replace("`", "")
    line = line.replace("*", "")
    line = line.replace("_", "")
    line = line.replace(">", "")
    line = line.replace("✅", "")
    line = line.replace("☑", "")
    line = re.sub(r"<a?:[^:>]+:\d+>", "", line)
    line = re.sub(r"^\W+", "", line)
    line = re.sub(r"^\s*\d{1,2}[\).]?\s+", "", line)

    if "." in line:
        prefix, rest = line.split(".", 1)

        if prefix.strip().isdigit():
            line = rest

    if ")" in line:
        prefix, rest = line.split(")", 1)

        if prefix.strip().isdigit():
            line = rest

    line = line.split(" - ", 1)[0]
    line = line.split(" | ", 1)[0]
    line = line.split(" (", 1)[0]
    line = line.strip("•-–— \t")

    line = line.strip("- \t")

    return " ".join(line.split())


def clean_raidhelper_attendees(attendees):
    seen = set()
    clean = []
    blocked = {"friday", "friday sky", "holyhood", "yes"}

    for attendee in attendees:
        attendee = " ".join(str(attendee).split()).strip()
        key = attendee.lower()

        if not attendee or key in blocked:
            continue

        if len(attendee) > 32:
            continue

        if not any(char.isalpha() for char in attendee):
            continue

        if key not in seen:
            seen.add(key)
            clean.append(attendee)

    return clean


def extract_raidhelper_attendees(message):
    mention_lookup = {
        str(user.id): user.display_name
        for user in message.mentions
        if not user.bot
    }
    attendees = []
    content = message.content or ""

    attending_content = re.split(
        r"(?:tentative|absence|absent|declined|unavailable)",
        content,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]

    for match in re.finditer(
        r"\b\d{1,2}\s+([A-Za-z][A-Za-z0-9'_-]{1,31})",
        attending_content,
    ):
        attendees.append(match.group(1))

    for line in attending_content.splitlines():
        if not line_looks_like_name(line):
            continue

        name = clean_raidhelper_name(line, mention_lookup)

        if name and not name.lower().startswith(("empty", "none")):
            attendees.append(name)

    for embed in message.embeds:
        for field in embed.fields:
            if not field_is_attending(field.name or "", field.value or ""):
                continue

            for line in (field.value or "").splitlines():
                if not line_looks_like_name(line):
                    continue

                name = clean_raidhelper_name(line, mention_lookup)

                if name and not name.lower().startswith(("empty", "none")):
                    attendees.append(name)

    return clean_raidhelper_attendees(attendees)


async def extract_reaction_attendees(message):
    attendees = []

    for reaction in message.reactions:
        emoji_name = (
            reaction.emoji.name
            if hasattr(reaction.emoji, "name")
            else str(reaction.emoji)
        ).lower()

        if any(
            word in emoji_name
            for word in ["no", "decline", "absent", "bench", "wait"]
        ):
            continue

        async for user in reaction.users():
            if user.bot:
                continue

            attendees.append(user.display_name)

    seen = set()
    clean = []

    for attendee in attendees:
        key = attendee.lower()

        if key not in seen:
            seen.add(key)
            clean.append(attendee)

    return clean


async def signup_message_sources(channel):
    sources = [channel]
    seen_ids = {channel.id}

    for thread in getattr(channel, "threads", []):
        if thread.id not in seen_ids:
            seen_ids.add(thread.id)
            sources.append(thread)

    if hasattr(channel, "archived_threads"):
        try:
            async for thread in channel.archived_threads(limit=50):
                if thread.id not in seen_ids:
                    seen_ids.add(thread.id)
                    sources.append(thread)
        except discord.DiscordException:
            pass

    return sorted(
        sources,
        key=lambda source: getattr(source, "created_at", None),
        reverse=True,
    )


def source_matches_event(source, event_name):
    source_name = getattr(source, "name", "")

    return (
        text_matches_event(source_name, event_name)
        and not any(
            blocked in source_name.lower()
            for blocked in ["sea", "limbus", "henm"]
        )
    )


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


async def fetch_raidhelper_attendees(event_name="Friday Sky", limit=500):
    token, channel_id = get_discord_config(
        "DISCORD_SIGNUP_CHANNEL_ID",
        default_channel_id="1383458990121291837",
    )

    intents = discord.Intents.default()
    intents.guilds = True
    intents.messages = True
    intents.reactions = False
    intents.message_content = True
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

        sources = await signup_message_sources(channel)
        matching_sources = [
            source
            for source in sources
            if source_matches_event(source, event_name)
        ]
        sources = matching_sources or sources

        for source in sources:
            print(f"Scanning signup source: {source.name}")
            source_matches = source_matches_event(source, event_name)

            async for message in source.history(limit=limit):
                if not source_matches and not message_matches_event(
                    message,
                    event_name,
                ):
                    continue

                attendees = extract_raidhelper_attendees(message)

                if not attendees:
                    attendees = await extract_reaction_attendees(message)

                if attendees:
                    break

            if attendees:
                break

            if source_matches:
                break

        await client.close()

    await client.start(token)

    return attendees


async def fetch_raidhelper_debug(limit=50):
    token, channel_id = get_discord_config(
        "DISCORD_SIGNUP_CHANNEL_ID",
        default_channel_id="1383458990121291837",
    )

    intents = discord.Intents.default()
    intents.guilds = True
    intents.messages = True
    intents.reactions = False
    intents.message_content = True
    intents.members = False

    client = discord.Client(intents=intents)
    rows = []

    @client.event
    async def on_ready():
        nonlocal rows

        channel = client.get_channel(channel_id)

        if channel is None:
            channel = await client.fetch_channel(channel_id)

        for source in await signup_message_sources(channel):
            async for message in source.history(limit=limit):
                if not message.embeds:
                    rows.append({
                        "source": source.name,
                        "message_id": str(message.id),
                        "created_at": message.created_at.isoformat(),
                        "author": str(message.author),
                        "content": message.content or "",
                        "title": "",
                        "description": "",
                        "fields": "",
                        "field_values": "",
                        "components": ", ".join(component_labels(message)),
                    })
                    continue

                for embed in message.embeds:
                    rows.append({
                        "source": source.name,
                        "message_id": str(message.id),
                        "created_at": message.created_at.isoformat(),
                        "author": str(message.author),
                        "content": message.content or "",
                        "title": embed.title or "",
                        "description": (embed.description or "")[:500],
                        "fields": ", ".join(
                            field.name or ""
                            for field in embed.fields[:10]
                        ),
                        "field_values": "\n---\n".join(
                            (field.value or "")[:500]
                            for field in embed.fields[:5]
                        ),
                        "components": ", ".join(component_labels(message)),
                    })

        await client.close()

    await client.start(token)

    return rows
