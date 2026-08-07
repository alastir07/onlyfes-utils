# Chat Log Receiver — Privacy/GDPR Discussion & Mediation Plan

**Context:** Brad (staff) raised concerns about the `chat-log-receiver` service — it centralizes clan/friends chat into a searchable Supabase archive, accessible to all staff, submitted by whichever staff members run the `chat-logger` RuneLite plugin. This document summarizes the discussion so far and proposes a plan to bring it to the team.

## Brad's original concern

- Ethically questionable, and beyond what's actually needed to moderate the clan.
- Storing a near-complete chat history for every member, accessible to any staff, that members haven't been told about or agreed to — different in kind from staff individually screenshotting/citing things they personally witnessed.
- Suspected this doesn't comply with GDPR (UK/EU).
- If we go ahead: members should be informed, there should be a retention limit, and a way to request deletion.

## Gut reactions we tested and where they landed

**"We aren't a company, so GDPR doesn't apply."** Very likely wrong. GDPR applies to any organization/group that determines the purpose and means of processing personal data — no commercial-activity carve-out. The relevant exemption (Art. 2(2)(c), "purely personal or household activity") is for individuals acting for themselves, not a staff team running shared tooling to oversee other people's conduct under clan policy. Not incorporated ≠ exempt.

**"It's a public forum, no expectation of privacy."** Partially right, but doesn't do the work we wanted it to. "No expectation of privacy" isn't itself a lawful basis for processing under GDPR — you still need one of the six Article 6 bases. It does matter for the *proportionality* judgment (a large broadcast channel is a weaker privacy claim than a DM), but it doesn't make collection automatically fine.

**A teammate's framing (independently, and a good one):** "If I wouldn't say it in a room with 100 people, I don't say it in clan chat." Privacy expectation scales down with audience size, but isn't zero even in a large channel — this maps well onto how GDPR's legitimate-interest balancing test actually reasons about context and expectation.

**The "well the plugin's local logging already does this" question.** Also a good point, and mostly correct: staff running the plugin *as clan policy* (not personal use) are already processing other members' personal data, in a form that's arguably *worse* on several fronts — no consistent retention, no access control, no way to honor a deletion/objection request across N untracked local copies, no accountability trail. Centralizing this doesn't create the exposure; it's what makes the exposure *governable*. But: if we centralize and someone still keeps ungoverned local copies per old habit, we haven't actually fixed anything for that person's data — the plugin policy should say the central receiver replaces local retention, not supplements it.

## Specific GDPR provisions currently at risk

| Provision | Issue |
|---|---|
| **Art. 5(1)(b)** Purpose limitation | No filtering — every message from every staff client is captured by default, not just moderation-relevant content. |
| **Art. 5(1)(c)** Data minimisation | Complete transcript of all activity is close to the opposite of "limited to what's necessary." |
| **Art. 5(1)(e)** Storage limitation | `chat_log_entries` has **no retention limit at all** — rows are kept forever (confirmed: no TTL, no purge job anywhere in the codebase). |
| **Art. 6** Lawful basis | Legitimate interests (6(1)(f)) is the only realistic basis; requires necessity + a balancing test that indefinite, all-staff-searchable retention is unlikely to pass cleanly, especially since the old "cite what you personally witnessed" model already served the moderation purpose. |
| **Art. 13** Transparency | No notice currently exists anywhere the clan would see it. Required when data is collected in a way subjects wouldn't reasonably expect. |
| **Art. 15 / 17** Access & erasure | No code path exists to export or delete a member's data on request. Only existing DELETE usage is the dedup sweep (content-hash based, not member-scoped). |
| **Art. 21** Right to object | Distinct from Art. 17 — lets a member stop *future* collection, not just erase the past. Required alongside erasure when relying on legitimate interests. No mechanism exists. |
| **Art. 25** Data protection by design/default | Current defaults (full retention, full staff access, no expiry) are the least privacy-protective configuration, not the most. |

## Mediation plan — proposed for tomorrow's discussion

**Framing to open with:** this isn't "should we surveil the clan" vs. "Brad is being paranoid" — it's that we already informally do a weaker, *less* governable version of this (staff-run local plugin logs, per existing policy), and the question is whether to make it centralized *and properly governed*, or leave it decentralized *and ungoverned*. Both Brad's concern and the "public chat" instinct are partially right; the resolution is in the specifics, not in picking a side.

**Decisions to get the team's input on:**
1. Go ahead with the centralized receiver at all — given the local-logging status quo, is fixing this properly (see below) preferable to the current ungoverned state, or should we scale back further (e.g., stop centralizing, tighten the local-logging policy instead)?
2. Retention window — 30/60/90 days is the typical "moderation lookback," not indefinite archive. Needs a number.
3. Whether member-level deletion should be **hard delete** or **anonymize** (keep shape of moderation history, strip identity/content).
4. Access scope — all staff by default, or staff-with-a-stated-reason (audit-logged pull rather than open query access)? Lower priority / more of a judgment call than a hard requirement.
5. Whether adopting the central receiver should **replace** local plugin log retention as clan policy (recommended — otherwise deletion/objection requests aren't actually honored end-to-end).

**Required build items before/alongside launch (roughly in priority order):**

1. **Notice** — pinned message / rules update telling the clan: what's logged, why, retention window, who can access it, how to request deletion or opt out. Zero code; must happen before or immediately alongside turning this on.
2. **Retention limit** — scheduled purge job, same shape as the existing daily dedup-sweep loop in `main.py`/`db.py`. Deletes rows older than the agreed window.
3. **Deletion on request (Art. 17)** — staff-triggered command/endpoint, `DELETE ... WHERE member_id = $1` (or anonymize), reusing the member-resolution logic already in `db.py`. Small addition given existing DELETE grant on the `chat_log_receiver` role.
4. **Opt-out / objection (Art. 21)** — a `chat_log_exemptions` table keyed by `member_id`, checked at insert time in `db.py:insert_entries` alongside the existing sender→member_id resolution; suppress storage (or redact content) for exempted members going forward. Distinct from #3 — deletion alone does not satisfy this right.
5. **Access minimization** — optional/lower-priority; policy decision more than a build item.

**What's already in decent shape and doesn't need rework:** RLS + dedicated restricted DB role (`chat_log_receiver`, `NOBYPASSRLS`) is a reasonable security posture (Art. 32) — better than the local-file status quo. The existing daily-loop/transaction scaffolding in `db.py`/`main.py` makes items 2–4 straightforward additions rather than new infrastructure.

**Bottom line:** none of this requires re-architecting what's built — it's additive, and most of the engineering (items 2–4) is roughly a few days of work leaning on scaffolding that already exists. The open questions are policy calls (retention window, hard-delete vs. anonymize, access scope, whether to sunset local logging), not engineering ones.
