import requests
import re
import json
from datetime import datetime
import asyncio

# Configuration / Defaults
BOARD_NAME_MAP = {
    "hcDUWrFo": "WPL",
    "8ttvsMXg": "WCH",
}


# -----------------------------
# Trello Fetching
# -----------------------------
def fetch_cards(board_id, api_key=None, token=None):
    """Fetch all cards from a Trello board."""
    url = f"https://api.trello.com/1/boards/{board_id}/cards"
    # params = {"fields": "name,desc"}
    params = {"fields": "name,desc,id,shortUrl"}

    if api_key and token:
        params["key"] = api_key
        params["token"] = token

    response = requests.get(url, params=params)
    response.raise_for_status()

    return response.json()


def fetch_meta_bgimg_140(board_id, api_key=None, token=None):
    """
    Fetch the 140px background image URL for a Trello board.
    """
    url = f"https://api.trello.com/1/boards/{board_id}"

    params = {"key": api_key, "token": token, "fields": "name", "prefs": "backgroundImageScaled"}

    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()

    # backgroundImageScaled is a list of sizes
    scaled = data.get("prefs", {}).get("backgroundImageScaled", [])

    # Find the 140px image
    for img in scaled:
        if img.get("width") == 140:
            return img.get("url")

    return None


def get_roblox_user_id(username):
    url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": True}
    response = requests.post(url, json=payload)
    response.raise_for_status()

    data = response.json().get("data", [])
    if data:
        return data[0]["id"]
    return None


def get_group_rank_name(user_id, group_id):
    url = f"https://groups.roblox.com/v2/users/{user_id}/groups/roles"
    response = requests.get(url)
    response.raise_for_status()

    for group in response.json()["data"]:
        if group["group"]["id"] == group_id:
            return group["role"]["name"]
    return None


def find_cards_by_username(cards, roblox_username, required_rank=None, group_id=None):
    """Find cards for a specific Roblox user, Optionally filtering by rank and group."""
    username = roblox_username.lower()

    matches = [
        {
            "id": card.get("id"),
            "name": card.get("name"),
            "desc": card.get("desc"),
            "shortUrl": card.get("shortUrl"),
        }
        for card in cards
        if username in card["name"].lower()
    ]

    print(
        f"Found {len(matches)} card(s) matching username '{roblox_username}' before rank filtering."
    )
    print(matches)

    if not required_rank:
        return matches

    if not group_id:
        raise ValueError("group_id is required when filtering by rank")

    user_id = get_roblox_user_id(roblox_username)
    if not user_id:
        return []

    rank_name = get_group_rank_name(user_id, group_id)
    if not rank_name:
        return []

    if rank_name.lower() != required_rank.lower():
        return []

    return matches


def json_safe(obj):
    """Ensure objects are serializable."""
    if isinstance(obj, datetime):
        return obj.strftime("%d/%m/%Y")
    raise TypeError(f"Type {type(obj)} not serializable")


# -----------------------------
# Parsing Logic
# -----------------------------


def parse_us_numeric_date(date_str):
    """Parse dates in MM/DD/YY or MM/DD/YYYY format."""
    if not date_str:
        return None

    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


def parse_card(card):
    """Parse a Trello card description into structured data."""
    title = card["name"]
    description = card["desc"]

    sections = re.split(r"\n(?=\*\*)", description)
    data = {}

    for section in sections:
        header_match = re.match(r"\*\*(.*?)\*\*", section)
        if not header_match:
            continue

        header = header_match.group(1).strip()
        corporate_dept = "Operations: General (Not Corporate Team)"

        if header.endswith("of Corporate Team"):
            corporate_dept = header.replace("of Corporate Team", "").strip()
            header = "Corporate Team"

        content = section[header_match.end() :].strip()

        jobs = {}
        items = []
        raw = []

        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue

            job_match = re.match(r"(.+?): (.+?) \[(.+)\]", line)
            if job_match:
                role, date, members = job_match.groups()
                jobs[role.strip()] = {
                    "date": date.strip(),
                    "promoter": [m.strip() for m in members.split(",")],
                }
                continue

            simple_match = re.match(r"(.+?): (.+)", line)
            if simple_match:
                role, date = simple_match.groups()
                jobs[role.strip()] = {
                    "date": date.strip(),
                    "members": [],
                }
                continue

            if line.startswith("- "):
                items.append(line[2:].strip())
                continue

            raw.append(line)
        if jobs:
            if header == "Corporate Team" and corporate_dept:
                if "Corporate Team" not in data:
                    data["Corporate Team"] = {"Dept": corporate_dept}
                data["Corporate Team"].update(jobs)
            else:
                data[header] = jobs
        elif items:
            data[header] = items
        else:
            data[header] = []

    if "|" in title:
        name, date_str = [t.strip() for t in title.split("|", 1)]
        data["Username"] = name
        data["Final Date"] = date_str
        data["Final Date Parsed"] = parse_us_numeric_date(date_str)
    else:
        data["Username"] = title
        data["Final Date"] = None

    return data


# -----------------------------
# Main Function (Can be reused as a module)
# -----------------------------


def trello_to_json(roblox_username=None, group_id=None, required_rank=None, board_id="hcDUWrFo"):
    """Fetch cards, filter by username and rank, and write to JSON."""
    cards = fetch_cards(board_id)
    matching_cards = find_cards_by_username(
        cards, roblox_username, required_rank=required_rank, group_id=group_id
    )

    data = []
    for card in matching_cards:
        data.append([card, parse_card(card)])

    with open("trello.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, default=json_safe)

    return matching_cards


def format_date(date_str):
    """Convert DD/MM/YYYY → MM/DD/YYYY if possible."""
    if not date_str:
        return ""

    parts = date_str.split("/")
    if len(parts) == 3:
        return f"{parts[1]}/{parts[0]}/{parts[2]}"
    return date_str


def display_results(cards, roblox_username, board_id):
    """Pretty-print matching card results."""
    if not cards:
        print("No matching cards found.")
        return

    print(f"Card Found: {len(cards)} card(s) matching '{roblox_username}'\n")
    print("-=" * 20 + "-\n")

    for card in cards:
        print("Title:", card["name"])

        latest_update = card["name"].split(" | ")[-1].strip()
        print("Latest Update:", format_date(latest_update), "(DD/MM/YYYY)")
        print("=" * 40)

        parsed = parse_card(card)
        print(parsed)
        print()

        for section in ("Staff of the Week", "Awards"):
            if parsed.get(section):
                print(f"{section}:")
                for item in parsed[section]:
                    print(f"- {item}")
                print()

        if parsed.get("Corporate Progression"):
            print("Corporate Progression Timeline:")
            for role, details in parsed["Corporate Progression"].items():
                members = ", ".join(details["members"])
                print(f"- {role}: {details['date']} [{members}]")

        print("\n\nDescription:")
        print(card["desc"])

        print("\n" + "^" * 40)
        cr = parsed.get("current_rank")
        if cr:
            print(
                f"Promotion information for {roblox_username}: "
                f"{cr['rank']} ({cr['group']}, {cr['date']})"
            )
        else:
            print(f"Promotion information for {roblox_username}: N/A")
        print(f"Latest Update: {format_date(latest_update)} (DD/MM/YYYY)")
        print(f"Card ID: {card.get('id', 'N/A')}")

        entry = parsed.get("Entry Team", {})
        supervision = parsed.get("Supervision Team", {})
        management = parsed.get("Management Team", {})
        corporate = parsed.get("Corporate Team", {})

        all_rank_groups = [entry, supervision, management, corporate]

        for rank_group in all_rank_groups:
            for rank, details in rank_group.items():
                if rank == "Dept":
                    continue  # skip metadata

                date = details.get("date", "N/A")
                promoter = ", ".join(details.get("promoter", [])) or "N/A"

                print(f"Rank: {rank}, Date: {date}, Promoter: {promoter}")

            print("-" * 40)

        print(
            f"Board: {BOARD_NAME_MAP.get(board_id, 'Unknown Board')} (ID: {board_id})"
        )  #! COMPLETE BOARD_ID
        print("Link to Board:", f"https://trello.com/b/{board_id}")
        card_id = card.get("id")
        short_url = card.get("shortUrl")
        if card_id:
            print("Link to Card:", short_url)
        else:
            print("Link to Card: N/A")


# -----------------------------
# Main Testing Function
# -----------------------------
def main():
    """Main entry point for testing purposes."""
    roblox_username = input("Enter the Roblox username to search for: ").strip()
    group_id = input("Enter the Roblox group ID (or leave blank): ").strip()
    required_rank = input("Enter the required rank (or leave blank): ").strip()
    BOARD_ID = input(
        "Enter the Trello Board ID, enter WPL/WCH (or leave blank for default): "
    ).strip()

    if BOARD_ID == "WPL" or BOARD_ID == "WCH":
        if BOARD_ID == "WPL":
            BOARD_ID = "hcDUWrFo"  # WPL Board ID
        elif BOARD_ID == "WCH":
            BOARD_ID = "8ttvsMXg"  # WCH Board ID

    if roblox_username == "" and required_rank == "":
        print("No input provided. Using Defaults for demonstration.")
        roblox_username = "hollvys"
        # required_rank = "Head Corporate" GG Holly. Thanks for your service. :D 28/09/26 (intl. date) 1774659800

    from roblox import RobloxUser

    roblox_username = asyncio.run(
        RobloxUser.create(roblox_username)
    ).username  # Overwrite Roblox username if username has changed
    # and user was found correctly with old username.

    del RobloxUser

    if group_id == "":
        group_id = 10261023
    if group_id == "" and required_rank != "":
        raise ValueError("Group ID must be provided if a required rank is specified.")

    if group_id == "":
        print("No group ID provided, proceeding without rank filtering.")
        group_id = None
    if required_rank == "":
        print("No required rank provided, proceeding without rank filtering.")
        required_rank = None
    if BOARD_ID == "":
        BOARD_ID = "hcDUWrFo"  # Default Board ID

    # Call the main function to execute
    matching_cards = trello_to_json(
        roblox_username=roblox_username,
        group_id=group_id,
        required_rank=required_rank,
        board_id=BOARD_ID,
    )

    print(f"Found {len(matching_cards)} matching cards.")

    display_results(matching_cards, roblox_username, BOARD_ID)
    data = []
    # for card in matching_cards:
    #     data.append([card, parse_card(card)])
    #     with open("trello.json", "w", encoding="utf-8") as f:
    #         import json

    #         json.dump(data, f, indent=4)


# -----------------------------
# Standalone Execution (Test Run)
# -----------------------------
if __name__ == "__main__":
    main()
else:
    del display_results, format_date, main
