# High-Level & Low-Level Requirements

**System:** `Washiez-Rank-Spy`

**Repository:** `Washiez-Wiki-Bot-Developers/Washiez-Rank-Spy`

**Compliance Level:** ED-12C Baseline (DAL E $\rightarrow$ Path to DAL A)

---

# High-Level Requirements (HLR)

```{hlr} Roblox Group Member Scan
:id: HLR_SPY_001
:status: approved
:tags: scanner, roblox

Software shall poll Roblox Group API to retrieve member roster and current rank assignments for target group.
```

```{hlr} Rank Change Delta Detection
:id: HLR_SPY_002
:status: approved
:tags: core, detection

Software shall compare newly retrieved group rank data against stored rank state to detect rank promotions, demotions, or member departures.
```

```{hlr} Data Privacy & Opt-Out Enforcement
:id: HLR_SPY_003
:status: approved
:tags: privacy, compliance

Software shall check target user IDs against designated opt-out list before emitting or storing public rank records.
```

```{hlr} Discord Webhook Notification Emission
:id: HLR_SPY_004
:status: approved
:tags: notification, discord

Software shall send formatted alert payloads to configured Discord webhook channels upon detecting valid rank changes.
```

```{hlr} Persistent Rank Storage
:id: HLR_SPY_005
:status: approved
:tags: storage, persistence

Software shall persist current state of group members and rank IDs to JSON storage structure safely without data corruption.
```
