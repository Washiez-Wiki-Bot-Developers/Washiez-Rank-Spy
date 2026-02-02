import json

HELL_RESTRICTIONS = {}
with open("hell_restricitions.json", "r") as f:
    HELL_RESTRICTIONS = json.load(f)

all_patches = []


class all_checks:
    def heaven_or_hell(self, user_id, rank_to, rank_from):
        """
        # Heaven or Hell

        This function checks if a user has been added to a specific group which is found to have issues with Roblox API.
        This is a temporary patch to avoid errors when interacting with the Roblox API for these users.
        This checks if a specific user is in the integer list of problematic users, which rank are blocked and returns False if they are found.

        True: Expected, proceed as normal.
        False: User is restricted, skip the action.

        :param user: Description
        :param rank_to: Description
        :param rank_from: Description
        
        Named after Heavenaa, user who had issues with Roblox API due to group problems.
        """

        if str(user_id) in HELL_RESTRICTIONS:
            restriction = HELL_RESTRICTIONS[str(user_id)]["restriction"]
            if restriction["rank_from"] == rank_from and restriction["rank_to"] == rank_to:
                return False
        return True


def check_user(user, rank_to, rank_from, action):
    """
    # Check user

    This function checks if a user is restricted from performing a specific action between two ranks.
    If the user is restricted, it logs a message and returns False.
    If all checks pass, it returns True.

    True: Expected, proceed as normal.
    False: User is restricted, skip the action.

    :param user: the User object (dictionary) containing user details. user['userId'] is used to get the user ID.
    :param rank_to: Rank to which the action is being performed.
    :param rank_from: Rank original which the action is was performed.
    :param action: Description
    """

    user_id = user.get("userId")

    for check_function in all_patches:
        if not check_function(user_id, rank_to, rank_from):
            print(
                f"User {user_id} is restricted from performing action '{action}' "
                f"between ranks '{rank_from}' and '{rank_to}'. Skipping."
            )
            return False

    return True


# Register the restriction check
all_patches.append(all_checks().heaven_or_hell)
