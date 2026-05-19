import asyncio
import re
from pathlib import Path
import streamlit as st
from discord_pop_reader import (
    fetch_discord_inventory,
    fetch_raidhelper_attendees,
    fetch_raidhelper_debug,
)

try:
    from streamlit_sortables import sort_items
except ImportError:
    sort_items = None


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


def normalize_inventory_rows(rows):
    if hasattr(rows, "to_dict"):
        return rows.to_dict("records")

    return list(rows)


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

    inventory_rows = st.session_state.inventory_rows

    if not inventory_rows:
        blank_row = {"Member": ""}

        for item in ALL_POP_ITEMS:
            blank_row[item] = False

        inventory_rows = [blank_row]

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
        key="inventory_editor",
    )
    st.session_state.inventory_rows = normalize_inventory_rows(
        edited_inventory_rows
    )
    st.session_state.inventory = rows_to_inventory(edited_inventory_rows)

    if st.button("Apply Inventory Edits"):
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
    st.success("Alliance assignments reset.")

late_attendee = st.text_input(
    "Add Available Attendee",
    placeholder="Late member name",
)

if st.button("Add Attendee"):
    names = names_from_text(late_attendee)

    if names:
        add_available_attendees(names)
        st.success(f"Added {', '.join(names)}.")
    else:
        st.warning("Enter a member name first.")

st.subheader("Alliance Assignments")

st.markdown("**God Assignments**")

if sort_items is not None:
    existing_god_buckets = st.session_state.god_buckets
    assigned_gods = (
        existing_god_buckets.get("Alliance 1", [])
        + existing_god_buckets.get("Alliance 2", [])
    )
    available_gods = [
        god
        for god in GOD_POP_ITEMS
        if god not in assigned_gods
    ]
    god_buckets = [
        {
            "header": "Available Gods",
            "items": available_gods,
        },
        {
            "header": "Alliance 1",
            "items": existing_god_buckets.get("Alliance 1", []),
        },
        {
            "header": "Alliance 2",
            "items": existing_god_buckets.get("Alliance 2", []),
        },
    ]

    sorted_god_buckets = sort_items(
        god_buckets,
        multi_containers=True,
        direction="horizontal",
        key=f"god_drag_buckets_{st.session_state.god_drag_version}",
    )

    if isinstance(sorted_god_buckets, list):
        new_god_buckets = normalize_god_buckets({
            bucket.get("header", ""): bucket.get("items", [])
            for bucket in sorted_god_buckets
        })

        if new_god_buckets != st.session_state.god_buckets:
            st.session_state.god_buckets = new_god_buckets

    alliance_1_gods = st.session_state.god_buckets.get("Alliance 1", [])
    alliance_2_gods = st.session_state.god_buckets.get("Alliance 2", [])

else:
    st.warning(
        "Drag-and-drop requires streamlit-sortables. "
        "Using multi-select god assignment instead."
    )
    col1, col2 = st.columns(2)

    with col1:
        alliance_1_gods = st.multiselect(
            "Alliance 1 Gods",
            options=list(GOD_POP_ITEMS.keys()),
            key="a1_gods",
        )

    with col2:
        alliance_2_gods = st.multiselect(
            "Alliance 2 Gods",
            options=[
                god
                for god in GOD_POP_ITEMS
                if god not in alliance_1_gods
            ],
            key="a2_gods",
        )

st.markdown("**Member Assignments**")

if st.session_state.attending_names and sort_items is not None:
    existing_buckets = st.session_state.attendee_buckets
    assigned_names = (
        existing_buckets.get("Alliance 1", [])
        + existing_buckets.get("Alliance 2", [])
    )
    available_names = [
        name
        for name in st.session_state.attending_names
        if name.lower() not in {n.lower() for n in assigned_names}
    ]
    attendee_buckets = [
        {
            "header": "Available attendees",
            "items": available_names,
        },
        {
            "header": "Alliance 1",
            "items": existing_buckets.get("Alliance 1", []),
        },
        {
            "header": "Alliance 2",
            "items": existing_buckets.get("Alliance 2", []),
        },
    ]

    sorted_buckets = sort_items(
        attendee_buckets,
        multi_containers=True,
        direction="horizontal",
        key=f"attendee_drag_buckets_{st.session_state.attendee_drag_version}",
    )

    if isinstance(sorted_buckets, list):
        new_attendee_buckets = {
            bucket.get("header", ""): bucket.get("items", [])
            for bucket in sorted_buckets
        }

        if new_attendee_buckets != st.session_state.attendee_buckets:
            st.session_state.attendee_buckets = new_attendee_buckets

    alliance_1_members = sort_names(
        st.session_state.attendee_buckets.get("Alliance 1", [])
    )
    alliance_2_members = sort_names(
        st.session_state.attendee_buckets.get("Alliance 2", [])
    )

elif st.session_state.attending_names:
    st.warning(
        "Drag-and-drop requires streamlit-sortables. "
        "Using multi-select assignment instead."
    )

    alliance_1_members = st.multiselect(
        "Alliance 1 Members",
        options=sort_names(st.session_state.attending_names),
        key="a1_attendees_fallback",
    )
    alliance_2_members = st.multiselect(
        "Alliance 2 Members",
        options=[
            name
            for name in sort_names(st.session_state.attending_names)
            if name not in alliance_1_members
        ],
        key="a2_attendees_fallback",
    )
    alliance_1_members = sort_names(alliance_1_members)
    alliance_2_members = sort_names(alliance_2_members)

else:
    alliance_1_members = []
    alliance_2_members = []
    st.info("Load attendee names above to assign members.")

st.header("3. Member Trade Orders")

if st.button("Generate Trade Plan"):
    inventory = rows_to_inventory(st.session_state.inventory_rows)
    st.session_state.inventory = inventory

    if not inventory:
        st.error("Load Discord inventory first.")
    else:
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

        a1_outgoing_orders = build_member_trade_orders(
            "Alliance 2",
            a2_results,
        )

        a2_outgoing_orders = build_member_trade_orders(
            "Alliance 1",
            a1_results,
        )

        ocol1, ocol2 = st.columns(2)

        with ocol1:
            display_member_trade_orders(
                "Alliance 1 members trading to Alliance 2",
                a1_outgoing_orders,
            )

        with ocol2:
            display_member_trade_orders(
                "Alliance 2 members trading to Alliance 1",
                a2_outgoing_orders,
            )

        with st.expander("Trade Plan Details", expanded=False):
            rcol1, rcol2 = st.columns(2)

            with rcol1:
                display_results("Alliance 1", alliance_1_gods, a1_results)

            with rcol2:
                display_results("Alliance 2", alliance_2_gods, a2_results)
