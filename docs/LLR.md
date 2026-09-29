# High-Level & Low-Level Requirements

**System:** `Washiez-Rank-Spy`

**Repository:** `Washiez-Wiki-Bot-Developers/Washiez-Rank-Spy`

**Compliance Level:** ED-12C Baseline (DAL E $\rightarrow$ Path to DAL A)

---

# Low-Level Requirements (LLR)

```{llr} Fetch Group Roster Page
:id: LLR_SPY_001
:status: approved
:links: HLR_SPY_001

Function `fetch_group_members(group_id: int, cursor: str | None)` shall send HTTP GET request to Roblox Group v1 API endpoint `https://groups.roblox.com/v1/groups/{group_id}/users`.

```

```{llr} API Rate Limit & Error Handling
:id: LLR_SPY_002
:status: approved
:links: HLR_SPY_001

Function `fetch_group_members()` shall catch HTTP status `429` (Rate Limited) or network errors, log event, and execute exponential backoff delay before retrying.

```

```{llr} Compare Rank Snapshots
:id: LLR_SPY_003
:status: approved
:links: HLR_SPY_002

Function `detect_rank_deltas(previous_state: dict[int, int], current_state: dict[int, int])` shall identify users whose rank ID changed between `previous_state` and `current_state`.

```

```{llr} User Opt-Out Guard
:id: LLR_SPY_004
:status: approved
:links: HLR_SPY_003

Function `is_user_opted_out(user_id: int, opt_out_list: set[int])` shall check if `user_id` exists within `opt_out_list`. If `True`, software shall strip user details from notification payloads.

```

```{llr} Format Webhook Payload
:id: LLR_SPY_005
:status: approved
:links: HLR_SPY_004

Function `build_webhook_embed(user_id: int, old_rank: str, new_rank: str)` shall construct valid Discord embed JSON object containing user avatar URL, old rank string, and new rank string.

```

```{llr} Atomic JSON File Writes
:id: LLR_SPY_006
:status: approved
:links: HLR_SPY_005

Function `save_rank_data(file_path: Path, data: dict[str, Any])` shall write rank snapshot to temporary file `file_path.tmp` before performing atomic file replacement to prevent data corruption during crashes.

```