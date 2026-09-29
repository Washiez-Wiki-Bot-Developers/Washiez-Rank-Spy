## Plan: Multi-role handling & dedupe

TL;DR
Detect multiple concurrent roles per user. Store role sets + notification metadata. Compute adds/removes per cycle. Notify once per user per chosen policy (7-week suppression on flip-flop). Persist new state. Update tests.

**Steps**
1. Data model: change `data["user_roles"]` values to list of role ids (unique, sorted). Add `data["user_meta"]` per-user metadata: `last_notified_ts`, `suppressed_until`, `last_notified_change`.
2. Migration: on load, normalize existing single-value entries to lists. Update `convert_to_simplified.py` if used.
3. Collect current roles: in the monitoring loop, instead of handling each role in isolation, first build `current_user_roles: dict[str, set[int]]` by iterating all roles and their members (can be done by accumulating within existing per-role loops or by a dedicated pass). *depends on fetch_users_in_role*.
4. Compare sets: for each user seen this cycle, compute `prev_set = set(store_user_roles)` and `curr_set = current_user_roles.get(user)`.
5. Determine deltas: `added = curr_set - prev_set`, `removed = prev_set - curr_set`.
6. Notification policy (confirmed): notify once on change, then suppress further notifications for that user for 7 weeks unless they change to a different rank. Implement rules:
   - If `added` or `removed` non-empty and `now >= suppressed_until`: pick net change to notify (see "notify selection"). Record `last_notified_ts = now` and set `suppressed_until = now + 7 weeks`.
   - If `now < suppressed_until`: skip notification for that user this cycle.
7. Notify selection (how to pick single notification): choose the highest-priority rank among `curr_set` vs `prev_set` using `RANK_ORDER` and produce a one-line message describing net change (e.g., "has been promoted to X" or "now holds X and Y — promoted/demoted summary"). Keep message creation centralized so batching works with `flush_role_change_queue`.
8. Deduplicate within cycle: keep `notified_users` set to avoid more than one message per user per run regardless of role loops.
9. Persist state: after processing all roles, update `data["user_roles"]` with normalized lists (or possibly store as list-of-ids) and `data["user_meta"]` metadata; call `save_data(data)`.
10. Backwards compatibility & rollout: add config flag `ENABLE_MULTI_ROLE_MODE` default True; on False keep old single-role behavior. Add migration script to convert existing store to list form.
11. Tests: add unit tests for set diff + suppression window, integration test for a user with two roles to assert single notification and suppressed repeated notifications.

**Relevant files**
- `app.py` — modify `monitor_role_changes`, `role_updates` handling, message composition, add `user_meta` writes.
- `convert_to_simplified.py` — normalize format read/write.
- `special_patches.py` — ensure `check_user` accepts sets or the selected single-role input.
- `tests/` — add `test_multi_role_notifications.py` and update any integration tests that assume single-role storage.

**Verification**
1. Unit tests: validate `compute_deltas(prev_set, curr_set)` and suppression logic (7-week window). Run `pytest tests/test_multi_role_notifications.py`.
2. Integration: run `monitor_role_changes` in `test_mode=True` with mocked `fetch_users_in_role` producing a user with multiple roles; assert only one notification generated and store updated to list form.
3. Run existing test suite to ensure no regressions.
4. Manual run: start bot with `--run-once` or `test_mode` and observe `safe_send` messages for a test account.

**Decisions / assumptions**
- Chosen policy: single notification on change + 7-week suppression unless user moves to a different rank (confirmed).
- Persist full role set per user (list of role ids) — easier to reason about multiple roles.
- Channel selection: message channel chosen by highest-priority role currently held; if multiple high roles, prefer the one with highest `RANK_ORDER` value.

**Further considerations**
1. Performance: building full `current_user_roles` for large groups may increase memory. Mitigate by streaming aggregation into a dict and pruning inactive users.
2. UI wording: choose concise message templates to summarize multiple-role changes.
3. Rollout: feature flag + migration path to avoid sudden behavior changes.

PENDING: implement changes after you approve the plan and confirm message wording style.