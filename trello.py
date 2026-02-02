import requests
import re
import json
from datetime import datetime

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
    params = {"fields": "name,desc"}

    if api_key and token:
        params["key"] = api_key
        params["token"] = token

    response = requests.get(url, params=params)
    response.raise_for_status()

    return response.json()


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
    """Find cards for a specific Roblox user, optionally filtering by rank and group."""
    username = roblox_username.lower()

    matches = [
        {"name": card["name"], "desc": card["desc"]}
        for card in cards
        if username in card["name"].lower()
    ]

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
        required_rank = "Head Corporate"
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
        board_id=BOARD_ID
    )

    print(f"Found {len(matching_cards)} matching cards.")


# -----------------------------
# Standalone Execution (Test Run)
# -----------------------------
if __name__ == "__main__":
    main()
