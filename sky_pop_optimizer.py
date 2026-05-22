import asyncio
import base64
import json
import re
from pathlib import Path
import zlib
import streamlit as st
import streamlit.components.v1 as components
from discord_pop_reader import (
    fetch_discord_inventory,
    fetch_raidhelper_attendees,
    fetch_raidhelper_debug,
)


GOD_POP_ITEMS = {
    "Seiryu": ["Gem of the East", "Springstone"],
    "Suzaku": ["Gem of the South", "Summerstone"],
    "Byakko": ["Autumnstone", "Gem of the West"],
    "Genbu": ["Winterstone", "Gem of the North"],
}

ITEM_TO_GOD = {
    item: god
    for god, items in GOD_POP_ITEMS.items()
    for item in items
}
ALL_POP_ITEMS = list(ITEM_TO_GOD.keys())
BASE_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
HEADER_BACKGROUND_IMAGE = BASE_DIR / "sky.png"
SHARE_BASE_URL = "https://finaleskytrade.streamlit.app/"

def dedupe_names(names):
    seen = set()
    clean = []

    for name in names:
        name = re.sub(r"\s+", " ", str(name)).strip()
        if not name:
            continue

        key = name.lower()
        if key not in seen:
            seen.add(key)
            clean.append(name)

    return clean


def names_from_text(text):
    candidates = re.split(r"[\n,]+", text)
    names = []

    for candidate in candidates:
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if not candidate:
            continue

        if 2 <= len(candidate) <= 32 and re.search(r"[A-Za-z]", candidate):
            names.append(candidate)

    return dedupe_names(names)


def sort_names(names):
    return sorted(names, key=lambda name: name.lower())


def merge_names(existing_names, new_names):
    return sort_names(dedupe_names(list(existing_names) + list(new_names)))


def reset_attendee_assignments(names):
    st.session_state.attending_names = sort_names(names)
    st.session_state.attendee_buckets = {
        "Available attendees": sort_names(names),
        "Alliance 1": [],
        "Alliance 2": [],
    }
    st.session_state.attendee_drag_version += 1


def add_available_attendees(names):
    names = sort_names(names)
    merged_names = merge_names(st.session_state.attending_names, names)
    previous_attending_names = list(st.session_state.attending_names)
    previous_buckets = {
        bucket_name: list(bucket_names)
        for bucket_name, bucket_names in st.session_state.attendee_buckets.items()
    }
    alliance_1 = sort_names(st.session_state.attendee_buckets.get("Alliance 1", []))
    alliance_2 = sort_names(st.session_state.attendee_buckets.get("Alliance 2", []))
    assigned_lookup = {name.lower() for name in alliance_1 + alliance_2}
    current_available = st.session_state.attendee_buckets.get(
        "Available attendees",
        [],
    )
    available = [
        name
        for name in merge_names(current_available, names)
        if name.lower() not in assigned_lookup
    ]

    st.session_state.attending_names = merged_names
    st.session_state.attendee_buckets = {
        "Available attendees": sort_names(available),
        "Alliance 1": alliance_1,
        "Alliance 2": alliance_2,
    }

    if (
        previous_attending_names != st.session_state.attending_names
        or previous_buckets != st.session_state.attendee_buckets
    ):
        st.session_state.attendee_drag_version += 1


def normalize_attendee_buckets(attendee_buckets, attending_names):
    attending_names = sort_names(attending_names)
    attending_by_key = {name.lower(): name for name in attending_names}
    used_keys = set()
    normalized = {}

    for bucket_name in ("Alliance 1", "Alliance 2"):
        normalized[bucket_name] = []

        for name in attendee_buckets.get(bucket_name, []):
            key = str(name).strip().lower()

            if key in attending_by_key and key not in used_keys:
                normalized[bucket_name].append(attending_by_key[key])
                used_keys.add(key)

        normalized[bucket_name] = sort_names(normalized[bucket_name])

    normalized["Available attendees"] = [
        name
        for name in attending_names
        if name.lower() not in used_keys
    ]

    return {
        "Available attendees": normalized["Available attendees"],
        "Alliance 1": normalized["Alliance 1"],
        "Alliance 2": normalized["Alliance 2"],
    }


def normalize_god_buckets(god_buckets):
    alliance_1 = [
        god
        for god in god_buckets.get("Alliance 1", [])
        if god in GOD_POP_ITEMS
    ]
    alliance_2 = [
        god
        for god in god_buckets.get("Alliance 2", [])
        if god in GOD_POP_ITEMS and god not in alliance_1
    ]
    assigned = set(alliance_1 + alliance_2)

    return {
        "Available Gods": [
            god
            for god in GOD_POP_ITEMS
            if god not in assigned
        ],
        "Alliance 1": alliance_1,
        "Alliance 2": alliance_2,
    }


def inventory_to_rows(inventory):
    rows = []

    for player, items in sorted(inventory.items()):
        row = {"Member": player}

        for item in ALL_POP_ITEMS:
            row[item] = item in items

        rows.append(row)

    return rows


def rows_to_inventory(rows):
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")

    inventory = {}

    for row in rows:
        player = str(row.get("Member", "")).strip()

        if not player:
            continue

        inventory[player] = [
            item
            for item in ALL_POP_ITEMS
            if bool(row.get(item, False))
        ]

    return inventory


def blank_inventory_row():
    row = {"Member": ""}

    for item in ALL_POP_ITEMS:
        row[item] = False

    return row


def normalize_inventory_rows(rows):
    if hasattr(rows, "to_dict"):
        rows = rows.to_dict("records")

    normalized = []

    for row in rows:
        clean_row = {"Member": str(row.get("Member", "")).strip()}

        for item in ALL_POP_ITEMS:
            clean_row[item] = bool(row.get(item, False))

        if clean_row["Member"] or any(clean_row[item] for item in ALL_POP_ITEMS):
            normalized.append(clean_row)

    return normalized


def inventory_rows_to_share_rows(rows):
    share_rows = []

    for row in normalize_inventory_rows(rows):
        share_rows.append([
            row["Member"],
            [
                index
                for index, item in enumerate(ALL_POP_ITEMS)
                if row.get(item, False)
            ],
        ])

    return share_rows


def share_rows_to_inventory_rows(share_rows):
    rows = []

    for share_row in share_rows:
        if not isinstance(share_row, list) or len(share_row) != 2:
            continue

        member = str(share_row[0]).strip()
        item_indexes = share_row[1] if isinstance(share_row[1], list) else []
        row = {"Member": member}

        for index, item in enumerate(ALL_POP_ITEMS):
            row[item] = index in item_indexes

        if member:
            rows.append(row)

    return normalize_inventory_rows(rows)


def encode_share_setup(inventory_rows, show_plan=False):
    payload = {
        "v": 1,
        "i": inventory_rows_to_share_rows(inventory_rows),
        "a": st.session_state.attending_names,
        "ab": st.session_state.attendee_buckets,
        "gb": st.session_state.god_buckets,
        "p": bool(show_plan),
    }
    payload_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(payload_json)

    return base64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")


def decode_share_setup(token):
    padded_token = token + ("=" * (-len(token) % 4))
    payload_json = zlib.decompress(
        base64.urlsafe_b64decode(padded_token)
    ).decode("utf-8")

    return json.loads(payload_json)


def get_share_token():
    token = st.query_params.get("setup")

    if isinstance(token, list):
        token = token[0] if token else ""

    return str(token or "").strip()


def build_share_url(token):
    return f"{SHARE_BASE_URL}?setup={token}"


def set_browser_share_url(token):
    st.session_state.loaded_share_token = token

    if get_share_token() != token:
        st.query_params["setup"] = token


def hydrate_shared_setup(token):
    payload = decode_share_setup(token)

    if payload.get("v") != 1:
        raise ValueError("Unsupported shared setup version.")

    inventory_rows = share_rows_to_inventory_rows(payload.get("i", []))
    attending_names = sort_names(payload.get("a", []))
    attendee_buckets = normalize_attendee_buckets(
        payload.get("ab", {}),
        attending_names,
    )
    god_buckets = normalize_god_buckets(payload.get("gb", {}))

    st.session_state.inventory_rows = inventory_rows
    st.session_state.inventory = rows_to_inventory(inventory_rows)
    st.session_state.inventory_editor_version += 1
    st.session_state.attending_names = attending_names
    st.session_state.attendee_buckets = attendee_buckets
    st.session_state.attendee_drag_version += 1
    st.session_state.god_buckets = god_buckets
    st.session_state.god_drag_version += 1
    st.session_state.trade_plan = None
    st.session_state.loaded_share_token = token
    st.session_state.shared_should_show_plan = bool(payload.get("p", False))


def display_header():
    header_background = Path(HEADER_BACKGROUND_IMAGE)

    if header_background.exists():
        st.image(str(header_background), use_container_width=True)
        return

    st.title("FFXI Sky Pop Trade Optimizer")
    st.markdown(
        "Reads Discord pop-item reactions and recommends who should trade what based on two alliance setups."
    )


def required_items_for_gods(gods):
    needed = []

    for god in gods:
        needed.extend(GOD_POP_ITEMS[god])

    return needed


def find_item_holders(item, inventory):
    return [
        player
        for player, items in inventory.items()
        if item in items
    ]


def get_inventory_items(player, inventory):
    for inventory_player, items in inventory.items():
        if inventory_player.lower() == player.lower():
            return items

    return []


def copy_inventory(inventory):
    return {
        player: list(items)
        for player, items in inventory.items()
    }


def add_inventory_item(player, item, inventory):
    for inventory_player, items in inventory.items():
        if inventory_player.lower() == player.lower():
            if item not in items:
                items.append(item)
            return

    inventory[player] = [item]


def remove_inventory_item(player, item, inventory):
    for inventory_player, items in inventory.items():
        if inventory_player.lower() == player.lower() and item in items:
            items.remove(item)
            return


def has_full_pop_set(member, god, inventory):
    items = get_inventory_items(member, inventory)
    return all(item in items for item in GOD_POP_ITEMS[god])


def pick_next_receiver(god, members, inventory, blocked_receivers):
    candidates = [
        member
        for member in members
        if not has_full_pop_set(member, god, inventory)
        and member.lower() not in blocked_receivers
    ]

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda member: sum(
            item in get_inventory_items(member, inventory)
            for item in GOD_POP_ITEMS[god]
        ),
    )


def find_cross_alliance_donor(item, other_members, other_gods, inventory):
    if ITEM_TO_GOD[item] in other_gods:
        return None

    other_member_lookup = {m.lower(): m for m in other_members}

    for holder in find_item_holders(item, inventory):
        if holder.lower() in other_member_lookup:
            return holder

    return None


def optimize_alliance(gods, members, other_gods, other_members, inventory):
    member_lookup = {m.lower(): m for m in members}

    results = {
        "covered_inside": [],
        "needs_cross_alliance_trade": [],
        "missing": [],
    }

    for god in gods:
        existing_holders = [
            member
            for member in members
            if has_full_pop_set(member, god, inventory)
        ]

        for holder in existing_holders:
            results["covered_inside"].append({
                "god": god,
                "items": GOD_POP_ITEMS[god],
                "holder": holder,
                "source": "already ready",
            })

        blocked_receivers = set()

        while True:
            receiver = pick_next_receiver(
                god,
                members,
                inventory,
                blocked_receivers,
            )

            if receiver is None:
                if not members:
                    results["missing"].append({
                        "god": god,
                        "items": GOD_POP_ITEMS[god],
                        "reason": "No members entered for this alliance",
                    })
                break

            receiver_items = get_inventory_items(receiver, inventory)
            missing_items = [
                item
                for item in GOD_POP_ITEMS[god]
                if item not in receiver_items
            ]

            planned_trades = []
            failed_item = None

            for item in missing_items:
                donor = find_cross_alliance_donor(
                    item,
                    other_members,
                    other_gods,
                    inventory,
                )

                if donor is None:
                    failed_item = item
                    planned_trades = None
                    break

                planned_trades.append({
                    "item": item,
                    "god": god,
                    "holder": donor,
                    "receiver": receiver,
                })

            if planned_trades is None:
                inside_holders = [
                    h for h in find_item_holders(failed_item, inventory)
                    if h.lower() in member_lookup
                ]

                reason = (
                    "Held inside this alliance, but not by the selected pop-set holder"
                    if inside_holders
                    else "No surplus holder found in the other alliance"
                )

                results["missing"].append({
                    "item": failed_item,
                    "god": god,
                    "receiver": receiver,
                    "reason": reason,
                })
                blocked_receivers.add(receiver.lower())
                continue

            for trade in planned_trades:
                remove_inventory_item(trade["holder"], trade["item"], inventory)
                add_inventory_item(trade["receiver"], trade["item"], inventory)
                results["needs_cross_alliance_trade"].append(trade)

            results["covered_inside"].append({
                "god": god,
                "items": GOD_POP_ITEMS[god],
                "holder": receiver,
                "source": "after trades",
            })

    return results


def build_member_trade_orders(alliance_name, results):
    orders = {}

    for row in results["needs_cross_alliance_trade"]:
        holder = row["holder"]

        if holder not in orders:
            orders[holder] = []

        orders[holder].append({
            "item": row["item"],
            "receiver": row["receiver"],
            "receiver_alliance": alliance_name,
            "god": row["god"],
        })

    return dict(sorted(orders.items(), key=lambda row: row[0].lower()))


def display_member_trade_orders(title, orders):
    st.subheader(title)

    if not orders:
        st.info("No outgoing trades needed.")
        return

    for trader in sorted(orders, key=lambda name: name.lower()):
        trades = sorted(
            orders[trader],
            key=lambda trade: (
                trade["receiver"].lower(),
                trade["god"].lower(),
                trade["item"].lower(),
            ),
        )
        st.markdown(f"**{trader} should trade:**")

        for trade in trades:
            st.write(
                f"- **{trade['item']}** to **{trade['receiver']}** "
                f"({trade['receiver_alliance']}) for **{trade['god']}**"
            )


def display_results_legacy(title, gods, results):
    st.subheader(title)
    st.markdown(f"**Gods:** {', '.join(gods)}")

    if results["covered_inside"]:
        st.success("Covered inside alliance")
        for row in results["covered_inside"]:
            st.write(
                f"✅ **{row['item']}** for **{row['god']}** "
                f"is already held by **{row['holder']}**"
            )

    if results["needs_cross_alliance_trade"]:
        st.warning("Needs trade from outside alliance")
        for row in results["needs_cross_alliance_trade"]:
            st.write(
                f"🔁 **{row['holder']}** should trade "
                f"**{row['item']}** to **{row['receiver']}** "
                f"for **{row['god']}**"
            )

    if results["missing"]:
        st.error("Missing items")
        for row in results["missing"]:
            st.write(
                f"❌ Missing **{row['item']}** for **{row['god']}**"
            )


def display_results(title, gods, results):
    st.subheader(title)
    st.markdown(f"**Gods:** {', '.join(gods)}")

    ready_counts = {
        god: sum(
            1
            for row in results["covered_inside"]
            if row["god"] == god
        )
        for god in gods
    }

    if ready_counts:
        st.markdown(
            "**Ready pop sets:** "
            + ", ".join(
                f"{god}: {count}"
                for god, count in ready_counts.items()
            )
        )

    if results["covered_inside"]:
        st.success("Ready pop sets")
        for row in results["covered_inside"]:
            items = ", ".join(row["items"])
            source = f" ({row['source']})" if "source" in row else ""
            st.write(
                f"Covered: **{row['god']}** ({items}) "
                f"is held by **{row['holder']}**{source}"
            )

    if results["needs_cross_alliance_trade"]:
        st.warning("Needs trade from the other alliance")
        for row in results["needs_cross_alliance_trade"]:
            st.write(
                f"Trade: **{row['holder']}** should trade "
                f"**{row['item']}** to **{row['receiver']}** "
                f"for **{row['god']}**"
            )

    if results["missing"]:
        st.error("Missing items")
        for row in results["missing"]:
            reason = f" ({row['reason']})" if "reason" in row else ""
            if "item" not in row:
                items = ", ".join(row["items"])
                st.write(f"Missing **{row['god']}** set ({items}){reason}")
                continue

            st.write(
                f"Missing **{row['item']}** for **{row['god']}**{reason}"
            )


def generate_trade_plan(
    inventory_rows,
    alliance_1_gods,
    alliance_1_members,
    alliance_2_gods,
    alliance_2_members,
):
    inventory = rows_to_inventory(inventory_rows)
    planned_inventory = copy_inventory(inventory)

    a1_results = optimize_alliance(
        alliance_1_gods,
        alliance_1_members,
        alliance_2_gods,
        alliance_2_members,
        planned_inventory,
    )

    a2_results = optimize_alliance(
        alliance_2_gods,
        alliance_2_members,
        alliance_1_gods,
        alliance_1_members,
        planned_inventory,
    )

    return {
        "alliance_1_gods": list(alliance_1_gods),
        "alliance_2_gods": list(alliance_2_gods),
        "alliance_1_members": list(alliance_1_members),
        "alliance_2_members": list(alliance_2_members),
        "a1_results": a1_results,
        "a2_results": a2_results,
        "a1_outgoing_orders": build_member_trade_orders(
            "Alliance 2",
            a2_results,
        ),
        "a2_outgoing_orders": build_member_trade_orders(
            "Alliance 1",
            a1_results,
        ),
    }


def display_trade_plan(trade_plan):
    ocol1, ocol2 = st.columns(2)

    with ocol1:
        display_member_trade_orders(
            "Alliance 1 members trading to Alliance 2",
            trade_plan["a1_outgoing_orders"],
        )

    with ocol2:
        display_member_trade_orders(
            "Alliance 2 members trading to Alliance 1",
            trade_plan["a2_outgoing_orders"],
        )

    with st.expander("Trade Plan Details", expanded=False):
        rcol1, rcol2 = st.columns(2)

        with rcol1:
            display_results(
                "Alliance 1",
                trade_plan["alliance_1_gods"],
                trade_plan["a1_results"],
            )

        with rcol2:
            display_results(
                "Alliance 2",
                trade_plan["alliance_2_gods"],
                trade_plan["a2_results"],
            )


def display_share_url(inventory_rows):
    token = encode_share_setup(inventory_rows, show_plan=True)
    share_url = build_share_url(token)

    st.subheader("Share This Setup")
    components.html(
        f"""
        <button
            id="copy-setup-link"
            style="
                background: #7c3aed;
                border: 0;
                border-radius: 6px;
                color: white;
                cursor: pointer;
                font: 600 14px system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                padding: 0.55rem 0.9rem;
            "
            type="button"
        >
            Copy Setup Link
        </button>
        <script>
            const button = document.getElementById("copy-setup-link");
            const setupLink = {json.dumps(share_url)};

            button.addEventListener("click", async () => {{
                try {{
                    await navigator.clipboard.writeText(setupLink);
                }} catch (error) {{
                    const input = document.createElement("input");
                    input.value = setupLink;
                    document.body.appendChild(input);
                    input.select();
                    document.execCommand("copy");
                    input.remove();
                }}

                button.textContent = "Copied";
                window.setTimeout(() => {{
                    button.textContent = "Copy Setup Link";
                }}, 1600);
            }});
        </script>
        """,
        height=48,
    )


st.set_page_config(
    page_title="Sky Pop Trade Optimizer",
    page_icon="🗿",
    layout="wide",
)


display_header()

if "inventory" not in st.session_state:
    st.session_state.inventory = {}

if "inventory_rows" not in st.session_state:
    st.session_state.inventory_rows = []

if "inventory_editor_version" not in st.session_state:
    st.session_state.inventory_editor_version = 0

if "attending_names" not in st.session_state:
    st.session_state.attending_names = []

if "attendee_buckets" not in st.session_state:
    st.session_state.attendee_buckets = {
        "Available attendees": [],
        "Alliance 1": [],
        "Alliance 2": [],
    }

if "attendee_drag_version" not in st.session_state:
    st.session_state.attendee_drag_version = 0

if "god_drag_version" not in st.session_state:
    st.session_state.god_drag_version = 0

if "god_buckets" not in st.session_state:
    st.session_state.god_buckets = {
        "Available Gods": list(GOD_POP_ITEMS.keys()),
        "Alliance 1": [],
        "Alliance 2": [],
    }

if "trade_plan" not in st.session_state:
    st.session_state.trade_plan = None

if "loaded_share_token" not in st.session_state:
    st.session_state.loaded_share_token = ""

if "shared_should_show_plan" not in st.session_state:
    st.session_state.shared_should_show_plan = False

share_token = get_share_token()

if share_token and share_token != st.session_state.loaded_share_token:
    try:
        hydrate_shared_setup(share_token)
        st.success("Loaded shared setup from the URL.")
    except Exception as e:
        st.session_state.loaded_share_token = share_token
        st.error("This shared setup link could not be loaded.")
        st.exception(e)

normalized_attendee_buckets = normalize_attendee_buckets(
    st.session_state.attendee_buckets,
    st.session_state.attending_names,
)

if normalized_attendee_buckets != st.session_state.attendee_buckets:
    st.session_state.attendee_buckets = normalized_attendee_buckets
    st.session_state.attendee_drag_version += 1

normalized_god_buckets = normalize_god_buckets(st.session_state.god_buckets)

if normalized_god_buckets != st.session_state.god_buckets:
    st.session_state.god_buckets = normalized_god_buckets
    st.session_state.god_drag_version += 1


st.header("1. Discord Inventory Parse")

if st.button("Pull Finale #pop-items", type="primary"):
    with st.spinner("Reading Discord reactions..."):
        try:
            st.session_state.inventory = asyncio.run(
                fetch_discord_inventory(limit=500)
            )
            st.session_state.inventory_rows = inventory_to_rows(
                st.session_state.inventory
            )
            st.session_state.inventory_editor_version += 1
            st.session_state.trade_plan = None
            st.session_state.shared_should_show_plan = False

            if st.session_state.inventory:
                st.success("Discord inventory loaded.")
            else:
                st.warning(
                    "Connected to Discord, but no pop-item reactions were found. "
                    "Check channel permissions, message history limit, and emoji names."
                )

        except Exception as e:
            st.error("Discord read failed.")
            st.exception(e)

if not st.session_state.inventory:
    st.info("Click Pull Finale #pop-items or add members manually below.")

with st.expander("Parsed Discord Inventory", expanded=True):
    if not st.session_state.inventory_rows and st.session_state.inventory:
        st.session_state.inventory_rows = inventory_to_rows(
            st.session_state.inventory
        )

    inventory_rows = (
        st.session_state.inventory_rows
        if st.session_state.inventory_rows
        else [blank_inventory_row()]
    )

    edited_inventory_rows = st.data_editor(
        inventory_rows,
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Member": st.column_config.TextColumn(
                "Member",
            ),
            **{
                item: st.column_config.CheckboxColumn(item)
                for item in ALL_POP_ITEMS
            },
        },
        key=f"inventory_editor_{st.session_state.inventory_editor_version}",
    )
    edited_inventory_snapshot = normalize_inventory_rows(edited_inventory_rows)

    if (
        st.session_state.trade_plan is not None
        and edited_inventory_snapshot != st.session_state.inventory_rows
    ):
        st.session_state.trade_plan = None
        st.session_state.shared_should_show_plan = False

    if st.button("Apply Inventory Edits"):
        st.session_state.inventory_rows = edited_inventory_snapshot
        st.session_state.inventory = rows_to_inventory(
            st.session_state.inventory_rows
        )
        st.session_state.inventory_editor_version += 1
        st.session_state.trade_plan = None
        st.session_state.shared_should_show_plan = False
        st.success("Inventory edits applied.")


st.header("2. Alliance Setups")

if st.button("Pull Friday Sky Signups", type="primary"):
    with st.spinner("Reading RaidHelper signups..."):
        try:
            names = asyncio.run(
                fetch_raidhelper_attendees(
                    event_name="Friday Sky",
                    limit=500,
                )
            )

            if names:
                add_available_attendees(names)
                st.session_state.trade_plan = None
                st.session_state.shared_should_show_plan = False
                st.success(f"Loaded {len(names)} Friday Sky attendees.")
            else:
                st.warning("No Friday Sky attendees found in RaidHelper.")
                debug_rows = asyncio.run(fetch_raidhelper_debug(limit=50))

                if debug_rows:
                    with st.expander("Recent RaidHelper embed debug"):
                        st.dataframe(debug_rows, use_container_width=True)

        except Exception as e:
            st.error("RaidHelper signup read failed.")
            st.exception(e)

if st.button("Reload Alliance Setup"):
    reset_attendee_assignments(st.session_state.attending_names)
    st.session_state.trade_plan = None
    st.session_state.shared_should_show_plan = False
    st.success("Alliance assignments reset.")

late_attendee = st.text_input(
    "Add Available Attendee",
    placeholder="Late member name",
)

if st.button("Add Attendee"):
    names = names_from_text(late_attendee)

    if names:
        add_available_attendees(names)
        st.session_state.trade_plan = None
        st.session_state.shared_should_show_plan = False
        st.success(f"Added {', '.join(names)}.")
    else:
        st.warning("Enter a member name first.")

st.subheader("Alliance Assignments")

st.markdown("**God Assignments**")

existing_god_buckets = st.session_state.god_buckets
existing_alliance_1_gods = [
    god
    for god in existing_god_buckets.get("Alliance 1", [])
    if god in GOD_POP_ITEMS
]
existing_alliance_2_gods = [
    god
    for god in existing_god_buckets.get("Alliance 2", [])
    if god in GOD_POP_ITEMS and god not in existing_alliance_1_gods
]
col1, col2 = st.columns(2)

with col1:
    alliance_1_gods = st.multiselect(
        "Alliance 1 Gods",
        options=list(GOD_POP_ITEMS.keys()),
        default=existing_alliance_1_gods,
        key=f"a1_gods_{st.session_state.god_drag_version}",
    )

with col2:
    alliance_2_gods = st.multiselect(
        "Alliance 2 Gods",
        options=[
            god
            for god in GOD_POP_ITEMS
            if god not in alliance_1_gods
        ],
        default=[
            god
            for god in existing_alliance_2_gods
            if god not in alliance_1_gods
        ],
        key=f"a2_gods_{st.session_state.god_drag_version}",
    )

alliance_1_gods = list(
    st.session_state[f"a1_gods_{st.session_state.god_drag_version}"]
)
alliance_2_gods = list(alliance_2_gods)
available_gods = [
    god
    for god in GOD_POP_ITEMS
    if god not in alliance_1_gods and god not in alliance_2_gods
]

if available_gods:
    st.markdown("**Available gods:** " + ", ".join(available_gods))

new_god_buckets = normalize_god_buckets({
    "Alliance 1": alliance_1_gods,
    "Alliance 2": alliance_2_gods,
})

if new_god_buckets != st.session_state.god_buckets:
    st.session_state.god_buckets = new_god_buckets
    st.session_state.trade_plan = None
    st.session_state.shared_should_show_plan = False

st.markdown("**Member Assignments**")

if st.session_state.attending_names:
    attendee_options = sort_names(st.session_state.attending_names)
    existing_attendee_buckets = st.session_state.attendee_buckets
    existing_alliance_1_lookup = {
        name.lower()
        for name in existing_attendee_buckets.get("Alliance 1", [])
    }
    existing_alliance_2_lookup = {
        name.lower()
        for name in existing_attendee_buckets.get("Alliance 2", [])
    }
    alliance_1_members = []
    alliance_2_members = []
    assignments_by_name = {}

    for name in attendee_options:
        if name.lower() in existing_alliance_1_lookup:
            assignment = "A1"
        elif name.lower() in existing_alliance_2_lookup:
            assignment = "A2"
        else:
            assignment = "Available"

        assignments_by_name[name] = assignment

    for row_start in range(0, len(attendee_options), 6):
        row_columns = st.columns(6)

        for column_index, column in enumerate(row_columns):
            attendee_index = row_start + column_index

            if attendee_index >= len(attendee_options):
                continue

            name = attendee_options[attendee_index]
            current_assignment = assignments_by_name.get(name, "A1")
            radio_index = 1 if current_assignment == "A2" else 0

            with column:
                st.markdown(
                    f"<span style='color: #16a34a; font-weight: 700;'>{name}</span>",
                    unsafe_allow_html=True,
                )
                assignment = st.radio(
                    f"{name} alliance assignment",
                    options=["A1", "A2"],
                    index=radio_index,
                    horizontal=True,
                    label_visibility="collapsed",
                    key=(
                        "attendee_assignment_"
                        f"{st.session_state.attendee_drag_version}_{attendee_index}"
                    ),
                )

            if assignment == "A1":
                alliance_1_members.append(name)
            elif assignment == "A2":
                alliance_2_members.append(name)

    alliance_1_members = sort_names(alliance_1_members)
    alliance_2_members = sort_names(alliance_2_members)
    available_attendees = [
        name
        for name in attendee_options
        if name not in alliance_1_members and name not in alliance_2_members
    ]

    if available_attendees:
        st.markdown(
            "**Available attendees:** "
            + ", ".join(available_attendees)
        )

    new_attendee_buckets = normalize_attendee_buckets(
        {
            "Alliance 1": alliance_1_members,
            "Alliance 2": alliance_2_members,
        },
        st.session_state.attending_names,
    )

    if new_attendee_buckets != st.session_state.attendee_buckets:
        st.session_state.attendee_buckets = new_attendee_buckets
        st.session_state.trade_plan = None
        st.session_state.shared_should_show_plan = False

else:
    alliance_1_members = []
    alliance_2_members = []
    st.info("Load attendee names above to assign members.")

st.header("3. Member Trade Orders")

if st.button("Generate Trade Plan"):
    current_inventory_rows = normalize_inventory_rows(edited_inventory_rows)
    st.session_state.inventory_rows = current_inventory_rows
    inventory = rows_to_inventory(current_inventory_rows)
    st.session_state.inventory = inventory

    if not inventory:
        st.error("Load Discord inventory first.")
    else:
        st.session_state.trade_plan = generate_trade_plan(
            current_inventory_rows,
            alliance_1_gods,
            alliance_1_members,
            alliance_2_gods,
            alliance_2_members,
        )
        st.session_state.shared_should_show_plan = True
        set_browser_share_url(
            encode_share_setup(current_inventory_rows, show_plan=True)
        )

if st.session_state.shared_should_show_plan and st.session_state.trade_plan is None:
    shared_inventory_rows = normalize_inventory_rows(st.session_state.inventory_rows)

    if shared_inventory_rows:
        st.session_state.trade_plan = generate_trade_plan(
            shared_inventory_rows,
            alliance_1_gods,
            alliance_1_members,
            alliance_2_gods,
            alliance_2_members,
        )

if st.session_state.trade_plan is not None:
    plan_is_current = (
        st.session_state.trade_plan.get("alliance_1_gods") == list(alliance_1_gods)
        and st.session_state.trade_plan.get("alliance_2_gods") == list(alliance_2_gods)
        and st.session_state.trade_plan.get("alliance_1_members") == list(alliance_1_members)
        and st.session_state.trade_plan.get("alliance_2_members") == list(alliance_2_members)
    )

    if not plan_is_current:
        st.session_state.trade_plan = None
        st.session_state.shared_should_show_plan = False

if st.session_state.trade_plan is not None:
    display_share_url(st.session_state.inventory_rows)
    display_trade_plan(st.session_state.trade_plan)
