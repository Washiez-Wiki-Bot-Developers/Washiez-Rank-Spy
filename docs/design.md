# Washiez Wiki Rank Spy - Design Document

* **Author:** Washiez Wiki Bot Developers
* **Status:** Draft
* **Last Updated:** 2026-07-26

## 1. Context & Goals

### Problem

Washiez Roblox group (~2M+ members) rank changes hard to track manually. Wiki editors need automatic promotion/demotion detection across staff ranks.

### Goals
* Rank change detection for Washiez Roblox group.
* * Automatic
* * * Poll Roblox Group API for rank updates.
* * Manual
* * * Allow community members to use `/check_role_users` command to query rank changes within role.
* * * Allow community members to use `/check_user_roles` command to query the user's role for changes.
* Rank history querying
* * Trello:
* * * Parse Washiez Trello boards via Atlassian API (`/trello_check` command).
* * TMM12/Rankspy Discord bot integration:
* * * Search for Roblox username using Discord API's built-in search endpoint -> return rank history. <br/><!--LF FOLLOWS ON RIGHT-->
(Most Discord libraries are in development or do not support this endpoint, so a custom implementation is required or implement development code by py-cord developers.)
* Announce changes on Discord using a bot (`TheMagikMan` bot) on rank change.
* Output `data.json` to be compared later for rank change detection.
* Compliance: Handle opt-out data removal (store Roblox ID -> block output).

### Non-Goals

* Execute Roblox in-game promotions/demotions.
* Manage Discord server roles.
* Manage Washiez group roles. (We only track and report rank changes; WE AREN'T WASHIEZ STAFF.)

---

## 2. Technical Architecture

### System Overview

```
[Roblox Group API] --\
                    +--> [Rank Spy Engine] --> [Database] --> [Discord Bot]
[Trello Board API] -/                                      --> [data.json Exporter]
```

### Data Schema

```json
{
  "roblox_id": 12345678,
  "username": "WashiezStaff",
  "previous_rank": "Shift Leader",
  "current_rank": "General Manager",
  "timestamp": 1785000000,
  "opt_out": false
}
```

### Core Services

1. **Roblox Poller:** Fetch group role members via `groups.roblox.com/v1/groups/{group_id}/roles/{role_id}/users` -> diff with DB -> generate change event.
2. **Trello Listener:** Fetch cards from Washiez Promotional Logs board -> link promotion proof to Roblox user.
3. **Privacy Filter:** Intercept output -> if `roblox_id` in blacklist DB -> obscure/suppress display.
4. **Wiki Exporter:** Format active staff list -> upload to Wiki via Fandom API bot.

---

## 3. Alternatives Considered

| Option                | Pros                      | Cons                                 | Decision                     |
|-----------------------|---------------------------|--------------------------------------|------------------------------|
| Roblox Cloud Webhooks | Instant updates           | Rank webhooks unreliable/unsupported | Rejected                     |
| Scheduled API Polling | Reliable, straightforward | Risk of `429 Too Many Requests`      | **Selected** (w/ proxy pool) |

---

## 4. Risks & Mitigations

* **Risk:** Roblox API rate limiting (`HTTP 429`).
  * **Mitigation:** Implement rotating proxies + backoff algorithm.
* **Risk:** Trello board layout format change.
  * **Mitigation:** Strict schema validation -> fallback error logging on failure.