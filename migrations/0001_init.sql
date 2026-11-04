-- canopy journal. Loop facts only. World facts are re-read from their source.
-- Applied by db.py inside a transaction; recorded in schema_migrations.
-- The schema as of v0.1 and the 128 migrations after it, squashed into this one (D068). A journal migrated through the
-- last of them, 0129, is recorded as having applied this one instead (db.py). Columns nothing reads any more stay, so a
-- fresh journal and one migrated through 0129 hold the same schema.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- One row per tick. tick_id tags every log line and decision.
CREATE TABLE ticks (
    id                        INTEGER PRIMARY KEY,
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    dry_run                   INTEGER NOT NULL DEFAULT 0,
    status                    TEXT NOT NULL DEFAULT 'running',
        -- running | ok | skipped | overseer_failed | reconcile_failed | abandoned
    summary                   TEXT,
    -- What the agent runtime reported about each tick's overseer run (DESIGN §6, §13): the session it kept, and what it
    -- cost in dollars and tokens, summed over its model calls, as `runs` records for a worker. NULL when the
    -- runtime reported none of it, as an `overseer_cmd` without OpenCode's JSON events does (D071), and on every tick
    -- from before canopy recorded it. A tick's cost is its overseer's alone: each run it dispatched records its own.
    session_id                TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    -- The newest message in the journal when each tick read it, before its harness items and the overseer's state block
    -- (DESIGN §6 step 3): every message up to it was there for that tick to see. NULL on every tick from before canopy
    -- recorded it. The web UI marks an operator message after the latest `ok` tick's as waiting for the next tick
    -- (§22).
    message_id                INTEGER,
    -- When each tick read the journal for its overseer's state, recorded with `message_id` (DESIGN §6 step 3): a run,
    -- chore run, or review run that started or ended after it, the tick could not have seen. Idle pacing reads it (§6).
    -- NULL on every tick from before canopy recorded it, and on a tick that stopped before reading.
    read_at                   TEXT,
    -- What `canopy loop` knew about each tick it ran (DESIGN §6, Idle pacing; ROADMAP M33): whether the tick was idle
    -- by `pacing.idle`, 1 or 0, and what ended the wait before it: `start` (the loop's first tick), `timer` (the wait
    -- ran its length), `gate` (a gate shortened the wait and it ran out), `message`, `run`, or `key`. Spend on idle
    -- ticks, and what woke the ticks that cost, is read from them. NULL on a tick the loop did not run, such as a
    -- hand-run `canopy tick`, and on every tick from before canopy recorded it.
    idle                      INTEGER,
    woken_by                  TEXT,
    tokens_peak_context       INTEGER,
    -- Whether a tick's state block told the overseer to run the tracker query (DESIGN §7, Spacing the query): 1 or 0.
    -- With `tracker.query_every_minutes` set, the next tick runs it again once that long has passed since the newest
    -- live `ok` tick that ran it. NULL on every tick from before canopy recorded it, each of which was told to run it.
    query_due                 INTEGER,
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    definitions_digest        TEXT,
    -- The version of canopy that ran each tick (DESIGN §6), as its installed package reports it: a release from its
    -- tag, or a development build with its commit. A tick's decisions name it through `tick_id`, so the journal says
    -- which release made each one. NULL on every tick from before canopy recorded it.
    canopy_version            TEXT,
    -- Whether the tick ran its overseer (DESIGN §39): 0 for one the harness's decisions left nothing to judge, which
    -- closed without it and cost nothing, and for one halted before it (§6 step 5); NULL on a tick from before that was
    -- recorded, every one of which that got that far ran it.
    overseer_ran              INTEGER,
    tokens_first_cache_read   INTEGER,
    -- The model canopy chose for a review's, a chore's, and a task's agent, and for a tick's overseer (DESIGN §13, Each
    -- agent's model), as a worker run records it in `runs.model`: what it asked the runtime for, written into the
    -- agent's definition, as `provider/model[@variant]`. NULL when it chose none and the runtime's default served it,
    -- on a tick whose overseer did not run, and on every run and tick from before canopy recorded it. What served it is
    -- `run_models`'.
    model                     TEXT,
    -- A running tick's overseer's latest tool call, as `runs` keeps its worker's (DESIGN §8): the tool's name,
    -- what the call did on one line (a shell call's command, else the runtime's title), and when canopy read it from
    -- the events the overseer printed. Shown to the operator while the tick runs. NULL before the overseer's first tool
    -- call, for a template that prints no events, and on every tick from before canopy recorded it.
    activity_tool             TEXT,
    activity                  TEXT,
    activity_at               TEXT
);

CREATE INDEX ticks_spent ON ticks(started_at, cost_usd);

-- One row per ticket key ever seen. The comment cursor makes ticks incremental. Attempt counts and the fix-ci cooldown
-- are derived from `runs` (D030). phase is the ticket's own last derived phase, for display only; never read as truth.
-- branch is the ticket's branch name, fixed by its first implement and the same in every unit.
CREATE TABLE tickets (
    key                   TEXT PRIMARY KEY,
    repo                  TEXT NOT NULL,   -- the workspace root
    first_seen_at         TEXT NOT NULL,
    last_seen_at          TEXT NOT NULL,
    phase                 TEXT,
    branch                TEXT,
    last_comment_id       TEXT,
    needs_human_since     TEXT,
    done                  INTEGER NOT NULL DEFAULT 0,
    -- A private ticket's message cursor: the newest journal message the loop has handled. Its own, apart from the
    -- comment cursor, which stays the tracker's.
    last_message_id       INTEGER,
    -- A ticket's mirror cursor: the newest tracker comment mirrored. Its own, apart from the comment cursor the phases
    -- use, and empty to start, so a ticket's first mirror covers its whole comment history.
    last_mirrored_id      TEXT,
    -- Forgetting a ticket's work (DESIGN §22): `canopy forget` clears what canopy knows of a ticket's branch and PRs so
    -- its next `implement` starts over, and marks where the loop's view of the ticket now begins. Earlier runs and
    -- messages stay in the journal: `show` prints them and attempt limits count them (D030), but the loop reads only
    -- what came after.

    -- When the operator last forgot the ticket's work; NULL if never.
    forgotten_at          TEXT,
    -- The ticket's newest run and newest message at that moment. The loop's reads skip runs and messages up to these.
    forgotten_run_id      INTEGER,
    forgotten_message_id  INTEGER,
    -- A ticket's title (DESIGN §6, §13): a short human name the overseer gives it with `canopy ticket set --title`,
    -- from the ticket's own title. For display, and for the session title of the ticket's runs; never read as truth.
    -- NULL until named.
    title                 TEXT,
    -- Whether this ticket is planned whatever `policy.plan` says: `plan` asks for one, `skip` waives it, NULL follows
    -- the policy. Set only by the operator's channels (DESIGN §22), never by the overseer or a worker.
    plan_setting          TEXT CHECK (plan_setting IN ('plan', 'skip')),
    -- When a ticket last changed (DESIGN §22): its row made, or its phase, title, done flag, plan setting, or a unit's
    -- phase or PR set to a value it did not already hold. The web UI weighs a ticket's and its PRs' activity by it
    -- rather than by `last_seen_at`, which every tick that names the ticket moves, so a tick that sets what was already
    -- there is no activity. Every row is made with it set; one from before canopy recorded it starts at its last
    -- sighting.
    changed_at            TEXT NOT NULL DEFAULT '',
    -- The comment cursor, as a journal number (DESIGN §35); a unit's review and ci cursors are on `ticket_units`.
    -- `last_comment_id` stays the comment cursor of a ticket no tracker source observes, which has no numbers to name
    -- (DESIGN §35, Open).
    comment_cursor        INTEGER
);

-- The tickets list: the tickets a tick saw last, the tickets with the newest messages, each one's newest message, and
-- the newest starts and stops. Without the third, SQLite read a ticket's newest message through the second, from the
-- newest message of any ticket.
CREATE INDEX tickets_seen ON tickets(last_seen_at);

-- The tickets list and the PRs list read the tickets that changed last, in place of the ones a tick saw last.
CREATE INDEX tickets_changed ON tickets(changed_at);

-- One row per worker execution. Source for capacity, crash detection, attempts. Its slots are in `run_slots`.
CREATE TABLE runs (
    id                        INTEGER PRIMARY KEY,
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    ticket_key                TEXT NOT NULL REFERENCES tickets(key),
    kind                      TEXT NOT NULL,                  -- implement | fix-ci | resume | split
    pid                       INTEGER,                        -- canopy _run
    branch                    TEXT NOT NULL,                  -- empty for a split, which works on none
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running',
        -- running | done | blocked | failed | unknown | unpushed | crashed | timeout
    result_json               TEXT,                           -- summary only; never raw logs
    log_path                  TEXT NOT NULL,
    -- The worker agent, which leads its own process group, so if `_run` is killed outright, reconcile can still stop
    -- the worker before returning its slots.
    worker_pid                INTEGER,
    -- What the agent runtime reported about each worker run (DESIGN §11, §13): the session it kept, and what the run
    -- cost in dollars and tokens, summed over its model calls. NULL when the runtime reported none of it, as a command
    -- template without OpenCode's JSON events does (D071), and on every run from before canopy recorded it.
    session_id                TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    -- Whether a run worked a private ticket: its prompt and agent definition were the private ones (DESIGN §22).
    private                   INTEGER NOT NULL DEFAULT 0,
    -- The most tokens one of an agent run's model calls was sent, from the cache or not (DESIGN §13): how large its
    -- context grew. The summed counts cannot say it, since each call reads again what the calls before it were sent.
    -- NULL when the runtime reported nothing, and on every run from before canopy recorded it.
    tokens_peak_context       INTEGER,
    -- What an agent run's first model call was sent, from the cache or not, and what it wrote to the cache (DESIGN
    -- §13): all of the run's fixed overhead is in that call, so less the prompt canopy sent it is the overhead, and a
    -- large write is a cold start. And the digest of the definitions snapshot the run loaded (`core/definitions.py`),
    -- so a change to a prompt, an override, or a definition splits the runs into before and after. NULL when the
    -- runtime reported nothing, the first call's too when it made no model call, and all three on every run from before
    -- canopy recorded it.
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    definitions_digest        TEXT,
    -- What a running run did last (DESIGN §8): its worker's latest tool call, as `_run` reads it from the worker's
    -- events while it runs, so a page shows more than `running` until the run ends. `activity_tool` is the tool's name,
    -- `activity` what the call did on one line (a shell call's command, else the runtime's title), and `activity_at`
    -- when `_run` read it. NULL until the worker's first tool call, and for a template that prints no events. Left as
    -- it was when the run ends: its result says what it did then.
    activity_tool             TEXT,
    activity                  TEXT,
    activity_at               TEXT,
    -- The approved plan an `implement` or `resume` was dispatched to follow (DESIGN §25, The worker's copy): the plan
    -- its prompt's `{{PLAN}}` names. `_run` writes the worker's copy of that plan alone, and refuses to start the
    -- worker when it is no longer the approved plan, or its file no longer has the approved hash. NULL for a run that
    -- follows none.
    plan_id                   INTEGER REFERENCES plans(id),
    -- The approved feedback plan a `resume` was dispatched to follow, the one its `{{PLAN}}` names and its run spent.
    feedback_plan_id          INTEGER REFERENCES feedback_plans(id),
    -- The persona each worker run and review ran in (DESIGN §31): its name, and the sha256 of its text as the prompt
    -- carried it, so the operator can compare one persona's work with another's, and a persona edited between two runs
    -- splits them. Both NULL for a run no persona reaches, such as a feedback plan, and for every run from before
    -- canopy recorded them.
    persona                   TEXT,
    persona_digest            TEXT CHECK ((persona IS NULL) = (persona_digest IS NULL)),
    -- The model canopy chose for a worker run's agent, from `runtime.models` (DESIGN §13, Each agent's model): what it
    -- asked the runtime for, written into the agent's definition, as `provider/model`. NULL when it chose none and the
    -- run went to the runtime's default, and on every run from before canopy chose one. What served it is
    -- `run_models`'.
    model                     TEXT,
    -- What an agent run's first model call read from the cache (DESIGN §13): the share of what it was sent that it read
    -- is whether the run's fixed prefix came from the cache, and a provider that reports no cache writes (OpenAI's)
    -- says so only through it. NULL when the runtime reported nothing, when the run made no model call, and on every
    -- run from before canopy recorded it.
    tokens_first_cache_read   INTEGER,
    -- What a running worker's, planner's, or reviewer's agent says of where its work stands, its card (DESIGN §41): the
    -- input of its latest `status` call, as canopy read it from the events the agent printed and validated it, as JSON;
    -- when canopy read it; and how many tool calls the agent had made by then. `tool_calls` counts every tool call the
    -- run's events have ended so far, so the calls since the card are what it says less `card_calls`. The card stays
    -- once the run ends. NULL, and 0 calls, on a run that never called `status`, and on every run from before canopy
    -- recorded it.
    card_json                 TEXT,
    card_at                   TEXT,
    card_calls                INTEGER,
    tool_calls                INTEGER NOT NULL DEFAULT 0,
    -- When each step a running agent's card names as `working` was first seen working (DESIGN §41): a JSON object from
    -- the step's title to the time canopy recorded the first card on which it was working, of the steps working on the
    -- latest card alone. A step working longer than the run's last fifth is shown stuck. NULL for a card with no steps
    -- working, and on every run from before canopy recorded it.
    card_working_since        TEXT,
    -- The question a running worker's, planner's, or reviewer's card asks the operator, and their answer (DESIGN §41):
    -- when canopy first recorded a card asking it, kept while the cards after it ask the same; the letter of the option
    -- the operator chose; and when they chose it. A card that asks another question starts it over, with no answer, and
    -- one that asks none clears all three. NULL on a run whose card asks nothing, and on every run from before canopy
    -- recorded it.
    card_asked_at             TEXT,
    card_answer               TEXT CHECK (card_answer IN ('A', 'B', 'C', 'D', 'E')),
    card_answered_at          TEXT,
    -- How often a running run's card went stale (DESIGN §41), so the journal says it after the run has ended.
    -- `card_lapses` counts each time it went from fresh to stale, as canopy found it at a tool call the run ended;
    -- `card_stale` says whether its card as it stands, or the run with none yet, has been counted so, until a new card
    -- makes it fresh again. A run that ended stale and not counted so lapses once more as it ended, which its row's
    -- `ended_at` says, so that lapse is read, not written. 0 on a run whose card never went stale, and on every run
    -- from before canopy recorded it.
    card_lapses               INTEGER NOT NULL DEFAULT 0,
    card_stale                INTEGER NOT NULL DEFAULT 0 CHECK (card_stale IN (0, 1)),
    -- The level of `policy.planner_may_approve` a plan run's prompt offered its planner (DESIGN §25): `off` where it
    -- was asked nothing, under the key's `off` or a plan the planner's word cannot approve, and `strict`, `normal`, or
    -- `lenient` where it was asked whether its plan needs review. So a report can split the plans approved by the level
    -- they were written under. Set as a `plan` or `feedback_plan` run starts; NULL on every other kind, and on every
    -- plan run from before canopy recorded it.
    plan_review               TEXT CHECK (plan_review IN ('off', 'strict', 'normal', 'lenient'))
);

CREATE INDEX runs_running ON runs(status) WHERE status = 'running';

CREATE INDEX runs_ticket  ON runs(ticket_key, started_at);

-- What the web UI reads on every journal commit, by index (DESIGN §22). On a journal with a year of history, a hundred
-- thousand ticks, tens of thousands of runs, and hundreds of thousands of decisions, each read was a scan of every row
-- ever recorded, and every open event stream made them all again on each commit.

-- The runs list: the runs that ended last.
CREATE INDEX runs_ended ON runs(ended_at);

-- The spend: what every agent run started since a time cost, read from the index alone.
CREATE INDEX runs_spent ON runs(started_at, cost_usd);

-- One row per overseer decision. Audit log and prompt evaluation corpus.
CREATE TABLE decisions (
    id          INTEGER PRIMARY KEY,
    tick_id     INTEGER NOT NULL REFERENCES ticks(id),
    ticket_key  TEXT,
    action      TEXT NOT NULL,   -- dispatch:<kind> | wait | skip | attention:<reason> | refused:<guard>
    rationale   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- An attention item may be about a repository or a ticket's unit; one about a repository has no ticket key.
    repo        TEXT,
    -- A decision about a chore carries its name and no ticket key: `dispatch:chore`, `wait`, `refused:<guard>`, and
    -- the harness's `attention:chore_failed`.
    chore       TEXT,
    -- A decision about a PR the loop reviews carries its URL: `dispatch:review`, `wait`, `refused:<guard>`, and
    -- `attention:<reason>`. An agent PR's decisions also carry its ticket key.
    pr          TEXT,
    -- Who made each decision (DESIGN §37, ROADMAP M38, TRUST_MODEL T5): the overseer, through one of its verbs, or the
    -- harness on its own, in code, which records decisions that need no judgment before the overseer runs. NULL on
    -- a decision recorded before the journal said, since a reason the harness raises today the overseer may have
    -- recorded then.
    decider     TEXT CHECK (decider IN ('overseer', 'harness')),
    -- The attention items the overseer keeps, `needs_author`, `multi_repo`, and `notice_rerun` (DESIGN §14, §37), are
    -- recorded once, naming what each is about, and held until that ends it, where the overseer recorded one every tick
    -- its cause held. `kept` is 1 on such a record; 0 on every other decision, and on an item the overseer recorded
    -- every tick before canopy kept them, which the list still reads that way. `item` is the journal number (§35) of
    -- what it names: the comment, review item, or review run a `needs_author` waits on, or the check run a
    -- `notice_rerun` holds; NULL for one about its ticket alone.
    kept        INTEGER NOT NULL DEFAULT 0 CHECK (kept IN (0, 1)),
    item        INTEGER,
    -- The kind of run a refused dispatch asked for (DESIGN §11), so the health report can say what a guard refused,
    -- ticket and kind, without reading it from the guard's reason. NULL on any other decision, and on every refusal
    -- from before canopy recorded it.
    kind        TEXT
    CHECK (kind IN ('implement', 'fix-ci', 'resume', 'split', 'plan', 'needs-plan', 'feedback-plan'))
);

CREATE INDEX decisions_tick ON decisions(tick_id);

-- Decisions by ticket, newest first (DESIGN §22): a ticket's page reads its latest decisions, and the tickets list and
-- `canopy status` read each ticket's newest one. Each was a scan of every decision ever recorded, a few hundred
-- thousand rows on a journal with months of ticks, once for each ticket the list shows.
CREATE INDEX decisions_ticket ON decisions(ticket_key, id);

CREATE INDEX decisions_pr ON decisions(pr, id) WHERE pr IS NOT NULL;

-- The list reads every kept record however old it is, so each is found by index.
CREATE INDEX decisions_kept ON decisions(id) WHERE kept = 1;

-- Attention items each notification sink was told about and that are still open, so a diff never re-notifies (D032).
CREATE TABLE notifications (
    sink         TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,   -- sha256 of ticket_key, reason, and repo when there is one
    ticket_key   TEXT,
    reason       TEXT NOT NULL,
    repo         TEXT,
    sent_at      TEXT NOT NULL,
    PRIMARY KEY (sink, fingerprint)
);

-- Units and joint runs (DESIGN §18). A ticket's work is divided into units, one per repository it changes, each with
-- its own branch, PR, phase, and review and ci cursors; the comment cursor and the ticket's own phase stay on
-- `tickets`. A run may lease a slot in several repositories, one `run_slots` row each.
CREATE TABLE ticket_units (
    ticket_key      TEXT NOT NULL REFERENCES tickets(key),
    repo            TEXT,
    branch          TEXT,
    pr_url          TEXT,
    phase           TEXT,
    -- Unread: the cursors are the journal numbers below (DESIGN §35).
    last_review_id  TEXT,
    last_ci_run_id  TEXT,
    review_cursor   INTEGER,
    ci_cursor       INTEGER,
    UNIQUE (ticket_key, repo)
);

CREATE INDEX ticket_units_pr ON ticket_units(pr_url);

-- The merged blocker an open PR is stacked on (DESIGN §10): the unit whose branch the PR targets, found by its branch.
-- Without it, each open PR the tickets list and the event stream weigh scanned every unit ever recorded, and SQLite
-- from 3.53 no longer finds a cheaper plan on its own.
CREATE INDEX ticket_units_branch ON ticket_units(branch);

CREATE TABLE run_slots (
    run_id        INTEGER NOT NULL REFERENCES runs(id),
    repo          TEXT,
    slot_path     TEXT NOT NULL,
    lease_id      TEXT NOT NULL,
    lease_holder  TEXT NOT NULL,
    base_branch   TEXT,
    -- What each slot's `.git` file held when `_run` started, before any git step (DESIGN §8, D108). Reconcile reads it
    -- to check a slot whose `_run` died before putting a changed link back. NULL for a slot whose `.git` is not a file,
    -- and on every slot from before canopy recorded it.
    git_link      BLOB,
    -- Which pool made each lease (DESIGN §18, ROADMAP M45 stage 3): a slot always goes back to the pool that leased it,
    -- whichever `pools.backend` names now, so switching with runs in flight is safe. Leases from before canopy
    -- recorded it are treehouse's.
    pool          TEXT NOT NULL DEFAULT 'treehouse' CHECK (pool IN ('treehouse', 'canopy')),
    UNIQUE (run_id, repo)
);

CREATE INDEX run_slots_lease ON run_slots(lease_id);

-- Split tickets (DESIGN §18). A split run creates one child ticket per repository in the tracker; `_run` records each
-- child it reported, after validating the result, with the repository it covers. A child is dispatched only in that
-- repository. The child is an ordinary ticket of the tracker's and may never appear in `tickets`, so it has no foreign
-- key; the parent does, since its dispatch recorded it.
CREATE TABLE split_children (
    child_key   TEXT PRIMARY KEY,
    parent_key  TEXT NOT NULL REFERENCES tickets(key),
    repo        TEXT NOT NULL,
    run_id      INTEGER NOT NULL REFERENCES runs(id)
);

CREATE INDEX split_children_parent ON split_children(parent_key);

-- Chores (DESIGN §19): recurring agent runs the operator defines and the overseer delegates. A chore run holds no slot
-- and works on no ticket, so it is not a `runs` row. Its result is a summary and findings, kept as the validated result
-- in `result_json`. `tick_id` is the tick whose overseer started the run, NULL for one the operator started by hand
-- (`canopy chore try`). `pid` is `canopy _chore`'s, or that of the `canopy chore try` running it in the foreground.
CREATE TABLE chore_runs (
    id                        INTEGER PRIMARY KEY,
    tick_id                   INTEGER REFERENCES ticks(id),
    chore                     TEXT NOT NULL,
    pid                       INTEGER,
    agent_pid                 INTEGER,           -- the chore's agent, which leads its own process group
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running',  -- running | ok | failed | unknown | timeout | crashed
    result_json               TEXT,
    log_path                  TEXT NOT NULL,
    -- What the agent runtime reported about each chore run (DESIGN §13, §19): the session it kept, and what the run
    -- cost in dollars and tokens, summed over its model calls, as `runs` records for a worker. NULL when the runtime
    -- reported none of it, as a chore `cmd` without OpenCode's JSON events does (D071), and on every chore run from
    -- before canopy recorded it. The columns after them are read and written as `runs`' and `ticks`' of the same names.
    session_id                TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    tokens_peak_context       INTEGER,
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    definitions_digest        TEXT,
    tokens_first_cache_read   INTEGER,
    model                     TEXT
);

CREATE INDEX chore_runs_chore ON chore_runs(chore, started_at);

CREATE INDEX chore_runs_running ON chore_runs(status) WHERE status = 'running';

CREATE INDEX chore_runs_spent ON chore_runs(started_at, cost_usd);

-- A chore's runs, newest first, for its page and its findings. Its runs by start served that by sorting them all.
CREATE INDEX chore_runs_newest ON chore_runs(chore, id);

-- Notification sinks (DESIGN §20). Point events go to an outbox, written in the transaction that records the fact, and
-- each sink has a cursor: the newest event it delivered. AUTOINCREMENT keeps ids rising after old events are pruned,
-- so an event never gets an id a cursor already passed.
CREATE TABLE notify_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    grp     TEXT NOT NULL,   -- loop | runs | chores
    kind    TEXT NOT NULL,
        -- run.started | run.ended | chore.ended | loop.failing | loop.recovered | loop.sink_failing
    at      TEXT NOT NULL,
    fields  TEXT NOT NULL    -- JSON object; text cut to its limits, one line
);

CREATE TABLE notify_sinks (
    name              TEXT PRIMARY KEY,
    cursor            INTEGER NOT NULL,   -- the newest notify_events id delivered, or passed over
    created_at        TEXT NOT NULL,
    last_delivery_at  TEXT,
    last_digest_at    TEXT,
    failures          INTEGER NOT NULL DEFAULT 0,  -- consecutive failed deliveries
    last_error        TEXT
);

-- Reviews (DESIGN §21): an adversarial read of one PR at one commit by a fresh reviewer run, in a slot checked out at
-- that commit. A review is keyed by its PR, not a ticket, so it is not a `runs` row. `ticket_key` links one of the
-- loop's own PRs to its ticket.
CREATE TABLE review_runs (
    id                        INTEGER PRIMARY KEY,
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    pr_url                    TEXT NOT NULL,
    sha                       TEXT NOT NULL,
    ticket_key                TEXT,
    -- The repository whose pool the slot came from; NULL in a workspace of one.
    repo                      TEXT,
    slot_path                 TEXT,
    lease_id                  TEXT,
    lease_holder              TEXT,
    pid                       INTEGER,           -- canopy _review
    agent_pid                 INTEGER,           -- the reviewer agent, which leads its own process group
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running',  -- running | done | failed | unknown | timeout | crashed
    result_json               TEXT,
    log_path                  TEXT NOT NULL,
    -- What the agent runtime reported about each review run (DESIGN §13, §21): the session it kept, and what the run
    -- cost in dollars and tokens, summed over its model calls, as `runs` records for a worker. NULL when the
    -- runtime reported none of it, as a `review_cmd` without OpenCode's JSON events does (D071), and on every review
    -- run from before canopy recorded it.
    session_id                TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    -- The branch a review run's slot was leased on, its pool's base (DESIGN §21): `_review` diffs the reviewed commit
    -- against where it leaves that branch, for the web UI's review page. NULL on every review run from before canopy
    -- recorded it, which has no diff.
    base_branch               TEXT,
    -- Why a review run was run (DESIGN §21): `own`, one of the loop's own PRs, named by the ticket whose unit opened
    -- it, or `query`, a PR `review.query` matched. `canopy review run` sets it, and refuses a ticket whose unit in the
    -- run's repository did not open the PR, so the overseer's ticket link is checked once, when the review starts. Only
    -- an `own` review's findings go to a worker. `request` is a review the operator asked for (ROADMAP M42). A run
    -- from before canopy recorded it is `own` where its ticket's unit in its repository had its PR then, and `query`
    -- otherwise.
    purpose                   TEXT NOT NULL DEFAULT 'query',
    tokens_peak_context       INTEGER,
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    definitions_digest        TEXT,
    pool                      TEXT NOT NULL DEFAULT 'treehouse' CHECK (pool IN ('treehouse', 'canopy')),
    persona                   TEXT,
    persona_digest            TEXT CHECK ((persona IS NULL) = (persona_digest IS NULL)),
    -- A revision is a review run at the same commit as the review whose draft it revises: `revises` names that draft
    -- and `revises_version` the version it read. Both NULL for a review, which every list of a PR's reviews keeps to.
    revises                   INTEGER REFERENCES review_drafts(id),
    revises_version           INTEGER CHECK ((revises IS NULL) = (revises_version IS NULL)),
    number                    INTEGER,
    tokens_first_cache_read   INTEGER,
    card_json                 TEXT,
    card_at                   TEXT,
    card_calls                INTEGER,
    tool_calls                INTEGER NOT NULL DEFAULT 0,
    card_working_since        TEXT,
    card_asked_at             TEXT,
    card_answer               TEXT CHECK (card_answer IN ('A', 'B', 'C', 'D', 'E')),
    card_answered_at          TEXT,
    model                     TEXT,
    card_lapses               INTEGER NOT NULL DEFAULT 0,
    card_stale                INTEGER NOT NULL DEFAULT 0 CHECK (card_stale IN (0, 1))
);

CREATE INDEX review_runs_pr ON review_runs(pr_url, started_at);

CREATE INDEX review_runs_running ON review_runs(status) WHERE status = 'running';

CREATE INDEX review_runs_spent ON review_runs(started_at, cost_usd);

-- The PRs list: the review runs that ended last, and the unit that has each PR. A PR's page: its latest decisions.
-- Most decisions name no PR, so only those that do are indexed.
CREATE INDEX review_runs_ended ON review_runs(ended_at);

-- A ticket's page: what the review runs naming it cost.
CREATE INDEX review_runs_ticket ON review_runs(ticket_key);

CREATE INDEX review_runs_revises ON review_runs(revises) WHERE revises IS NOT NULL;

-- Conversations (DESIGN §22): every ticket's messages, and the operator's start records for private tickets. Both are
-- keyed by subject, its kind and id, so a new kind of subject (a PR with M14) adds no table (D075).

-- One row per message. AUTOINCREMENT, so an id is never reused and a message cursor never passes a later message.
CREATE TABLE messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_kind  TEXT NOT NULL,                  -- ticket
    subject_id    TEXT NOT NULL,                  -- the ticket key
    at            TEXT NOT NULL,                  -- when canopy recorded it
    source        TEXT NOT NULL,                  -- worker | operator | tracker (M19)
    kind          TEXT NOT NULL,                  -- report | question (a worker's) | reply (the operator's)
    channel       TEXT NOT NULL,                  -- run | cli | web | slack | tracker
    run_id        INTEGER REFERENCES runs(id),    -- a worker's message: the run that reported it
    body          TEXT NOT NULL,                  -- bounded by its source: 2000 for a worker's, 4000 for the operator's
    answers       INTEGER REFERENCES messages(id),-- the message a reply answers, when the channel knows it
    submission    TEXT,                           -- an operator message's submission id: a retry records nothing new
    -- Tracker comments in the journal (DESIGN §22, M19): the overseer mirrors each ticket's comments into `messages`
    -- with `canopy mirror`, so the journal holds every ticket's conversation, public or private. A mirrored comment
    -- authorizes nothing.

    -- A mirrored comment's tracker id, its author's account id, and when the tracker says it was written. NULL for
    -- every other message.
    comment_id    TEXT,
    author        TEXT,
    commented_at  TEXT,
    -- Whether the body was cut to its bound (2000 characters for a mirrored comment).
    truncated     INTEGER NOT NULL DEFAULT 0,
    -- A one-off task's conversation (DESIGN §36): its runs' reports and questions, and the operator's replies, are
    -- messages about the task, `subject_kind` 'task' and its id. A run's own messages name it here, as `run_id` names a
    -- ticket's run; `run_id` references `runs`, which a task's run is not.
    task_run_id   INTEGER REFERENCES task_runs(id),
    UNIQUE (subject_kind, subject_id, submission)
);

CREATE INDEX messages_subject ON messages(subject_kind, subject_id, id);

-- A comment is mirrored once per subject, however often the overseer records it.
CREATE UNIQUE INDEX messages_comment ON messages(subject_kind, subject_id, comment_id) WHERE comment_id IS NOT NULL;

CREATE INDEX messages_at ON messages(subject_kind, at);

CREATE INDEX messages_subject_at ON messages(subject_kind, subject_id, at);

-- The operator's start record for a subject worked privately. It is the authorization: only the operator's commands
-- write it. `stop` marks it stopped and never deletes it, so a stopped ticket stays private.
CREATE TABLE starts (
    subject_kind  TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    status        TEXT NOT NULL,                  -- started | stopped
    started_at    TEXT NOT NULL,
    stopped_at    TEXT,
    channel       TEXT NOT NULL,                  -- the channel of the latest start or stop
    PRIMARY KEY (subject_kind, subject_id)
);

CREATE INDEX starts_at ON starts(subject_kind, coalesce(stopped_at, started_at));

-- Whether the operator paused the loop (DESIGN §6, The loop): a row means paused, since `paused_at`, through
-- `channel` (`loop`, the loop's own terminal; `cli`; or `web`). At most one row. `canopy loop` starts no tick while
-- it is there; a hand-run `canopy tick` still runs. Resuming deletes it.
CREATE TABLE pause (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    paused_at  TEXT NOT NULL,
    channel    TEXT NOT NULL
);

-- Runs the operator granted a unit beyond its policy attempt limit (`canopy grant`, DESIGN §8, §22). Rows are only
-- added: a unit's limit for a kind is the policy's plus the sum of its grants of that kind, and every run still counts
-- (D030). No agent canopy runs can add one.
CREATE TABLE attempt_grants (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    repo        TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('implement', 'fix-ci', 'resume', 'feedback-plan')),
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);

-- Chore findings the operator dismissed (`canopy dismiss chore:NAME ID`, DESIGN §19). A dismissal keeps a finding off
-- the attention list while the chore goes on reporting it: it covers the unbroken run of `ok` runs reporting the id
-- when it was made, so a finding that clears and comes back is listed again. `--undo` deletes the row, and dismissing
-- the id again replaces it. No agent canopy runs can add one.
CREATE TABLE finding_dismissals (
    chore         TEXT NOT NULL,
    finding_id    TEXT NOT NULL,
    dismissed_at  TEXT NOT NULL,
    channel       TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    PRIMARY KEY (chore, finding_id)
);

-- Review findings the operator dismissed (`canopy dismiss review:ID N`, DESIGN §21), by the finding's number in its
-- run, from 1. A dismissed finding stays on the review's page, marked, and is left out of what a `resume` hands a
-- worker and of the overseer's state block. A finding has no id that lasts from one commit's review to the next, so a
-- dismissal is of one run's finding only. `--undo` deletes the row. No agent canopy runs can add one.
CREATE TABLE review_dismissals (
    review_run_id  INTEGER NOT NULL REFERENCES review_runs(id),
    finding        INTEGER NOT NULL CHECK (finding > 0),
    dismissed_at   TEXT NOT NULL,
    channel        TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    -- Why the operator dismissed it: `wrong`, the finding does not hold; `intentional`, it holds but the change means
    -- it; `not_worth_it`, it holds and is not worth fixing; `out_of_scope`, it holds and is worth fixing, but belongs
    -- in another PR. It tells a reviewer's noise from findings that were right but not acted on. NULL on a dismissal
    -- from before canopy asked why.
    reason         TEXT CHECK (reason IN ('wrong', 'intentional', 'not_worth_it', 'out_of_scope')),
    PRIMARY KEY (review_run_id, finding)
);

-- Review runs the operator granted a PR beyond `policy.max_reviews_per_pr` (`canopy grant <PR> review`, DESIGN §21,
-- §22). Rows are only added: a PR's limit is the policy's plus the sum of its grants, and every review run still
-- counts (D030). Keyed by the PR's URL, as `review_runs.pr_url` is. No agent canopy runs can add one.
CREATE TABLE review_grants (
    id          INTEGER PRIMARY KEY,
    pr_url      TEXT NOT NULL,
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);

CREATE INDEX review_grants_pr ON review_grants(pr_url);

-- The operator's notices to workers (`canopy notice`, DESIGN §8, §22): a passing condition, such as a CI outage, that
-- every run that builds, tests, or reads CI hears while it lasts. A notice is in force from `set_at` until
-- `lapses_at`, or until `ended_at` if the operator cleared it (`canopy notice --clear`) or set another, which ends it.
-- At most one is in force; a lapsed one reads as none, so nothing deletes it. Rows stay, so the overseer can tell
-- which failed checks ran while one was in force (§7). `channel` and `ended_channel` are `cli` or `web`.
CREATE TABLE notices (
    id             INTEGER PRIMARY KEY,
    body           TEXT NOT NULL,
    set_at         TEXT NOT NULL,
    channel        TEXT NOT NULL,
    lapses_at      TEXT NOT NULL,
    ended_at       TEXT,
    ended_channel  TEXT
);

CREATE INDEX notices_set ON notices(set_at);

-- The operator's requests to review a PR the loop does not own (DESIGN §21, ROADMAP M42): `canopy start URL --review`,
-- or the web UI's pull requests page. A request authorizes one review of its PR at its head, as `review.query` would;
-- the overseer names the repository it is in when it runs the review. It ends when a review of it ends `done`, when the
-- overseer reads that the PR merged or closed first or is in none of the workspace's repositories, or when the operator
-- stops it. At most one open request per PR. Rows are kept once ended, so a PR's page shows who ended its request and
-- why. No agent canopy runs can add one.
CREATE TABLE review_requests (
    id          INTEGER PRIMARY KEY,
    pr_url      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    channel     TEXT NOT NULL,
    ended_at    TEXT,
    end_reason  TEXT CHECK (end_reason IN ('reviewed', 'merged', 'closed', 'unknown_repo', 'stopped')),
    -- The operator's notes on a review request (DESIGN §21): what they want the reviewer to know or look at, such as
    -- what the author asked for or the part of the change that worries them. The reviewer's prompt carries them. NULL
    -- when the request has none; asking again with notes replaces them on the open request.
    notes       TEXT,
    -- The model the operator chose for a review request's reviews (DESIGN §13, Each agent's model; §21): every review
    -- the request makes runs its reviewer on it, in place of the PR's ticket's override and `runtime.models.reviewer`,
    -- as `provider/model[@variant]`. NULL when the request chose none. Set only by the operator, with `canopy start URL
    -- --review --model` or the web UI; asking again with a model replaces it on the open request.
    model       TEXT,
    CHECK ((ended_at IS NULL) = (end_reason IS NULL))
);

CREATE UNIQUE INDEX review_requests_open ON review_requests(pr_url) WHERE ended_at IS NULL;

CREATE INDEX review_requests_pr ON review_requests(pr_url, id);

-- canopy's own worktree pools (DESIGN §18, ROADMAP M45): one row per slot of a repository's pool, idle or leased.
-- Written only by `core/pool.py`, under the pool's lock. A slot is leased while `lease_holder` is set; a lease a
-- failed seed left has a holder but no id, so no conditional return can clear it. `base` is the branch the slot was
-- last leased on by name, empty for the default branch; a return parks the slot there. `seeded` is a JSON array of the
-- paths seeding wrote in the slot, relative to it, which the next reset removes. A pool made by treehouse has no rows.
CREATE TABLE slots (
    repo          TEXT NOT NULL,
    name          TEXT NOT NULL,
    path          TEXT NOT NULL UNIQUE,
    lease_id      TEXT,
    lease_holder  TEXT,
    leased_at     TEXT,
    base          TEXT NOT NULL DEFAULT '',
    seeded        TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (repo, name),
    CHECK ((lease_holder IS NULL) = (leased_at IS NULL)),
    CHECK (lease_id IS NULL OR lease_holder IS NOT NULL)
);

-- What each agent run's tool calls put into its context (DESIGN §13): one row per run and tool, rolled up from the
-- run's `tool_use` events when it reports what it cost. `run_table` and `run_id` name the run: a tick's overseer, a
-- worker or split run, a chore run, a review run, a task's run, or an epic's plan run. `tool` is the tool's name as the
-- runtime gives it, an MCP server's prefixed with the server's; `calls` how many of its calls ended, `errors` how many
-- of those ended in an error, and `result_chars` the characters of what they returned, output or error, which each
-- later model call reads again. No row for a run whose template prints no events, nor for any run from before canopy
-- recorded them. Without a rowid, since every read is by its key, which would otherwise be stored again in an index of
-- its own.
CREATE TABLE run_tools (
    run_table              TEXT NOT NULL CHECK (
        run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs', 'epic_runs')
    ),
    run_id                 INTEGER NOT NULL,
    tool                   TEXT NOT NULL,
    calls                  INTEGER NOT NULL,
    errors                 INTEGER NOT NULL,
    result_chars           INTEGER NOT NULL,
    PRIMARY KEY (run_table, run_id, tool)
) WITHOUT ROWID;

-- Plans before implementing (DESIGN §25, ROADMAP M44): one row per plan a plan run wrote, and the ticket's own plan
-- setting. A plan's text is never here: it is the file `<state_dir>/plans/<ticket_key>/<run_id>.md`, which the row is
-- recorded after. `sha256` and `size` are the file's as the planner wrote it; the approved hash is the file's when the
-- operator approved it, their edits included, and `approved_channel` how they did. A new plan, a request for one, or a
-- skip supersedes the one before it, so a ticket has at most one plan waiting or approved. Rows are never deleted.
CREATE TABLE plans (
    id                     INTEGER PRIMARY KEY,
    ticket_key             TEXT NOT NULL REFERENCES tickets(key),
    run_id                 INTEGER NOT NULL UNIQUE REFERENCES runs(id),
    created_at             TEXT NOT NULL,
    status                 TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'superseded')),
    sha256                 TEXT NOT NULL,
    size                   INTEGER NOT NULL,
    approved_sha256        TEXT,
    approved_at            TEXT,
    approved_channel       TEXT,
    -- A plan the planner said needs no review (DESIGN §25, §32): under `policy.planner_may_approve`, the harness
    -- approves it as the planner wrote it, with `approved_channel` 'planner', and keeps the planner's one-line reason
    -- here, which every such approval has. NULL for every plan the operator approved, and for one not approved.
    approved_reason        TEXT CHECK ((approved_channel IS 'planner') = (approved_reason IS NOT NULL)),
    -- How much work a plan is for the worker that follows it, as its planner judged (DESIGN §25): `small`, `medium`, or
    -- `large`. NULL when the planner gave no estimate, as for every plan from before canopy asked, or one outside
    -- those.
    effort                 TEXT CHECK (effort IN ('small', 'medium', 'large')),
    -- The ticket's text as the tracker connector last observed it when its plan was approved (DESIGN §25): a SHA-256,
    -- hex, of its title and of its description, each recorded with the approval, the operator's or the planner's, and
    -- again with each approval after. While the ticket's observed text differs, the harness warns (`ticket_changed`),
    -- naming which changed, and refuses nothing. NULL for a plan never approved, one approved while the ticket was not
    -- observed, and every one approved before canopy recorded it: such an approval never warns of its ticket's text.
    approved_title_sha256  TEXT,
    approved_body_sha256   TEXT CHECK (
        (approved_title_sha256 IS NULL) = (approved_body_sha256 IS NULL)
        AND (approved_body_sha256 IS NULL OR approved_at IS NOT NULL)
    ),
    CHECK ((approved_sha256 IS NULL) = (approved_at IS NULL) AND (approved_at IS NULL) = (approved_channel IS NULL)),
    CHECK (status != 'approved' OR approved_at IS NOT NULL),
    CHECK (status != 'proposed' OR approved_at IS NULL)
);

CREATE UNIQUE INDEX plans_current ON plans(ticket_key) WHERE status != 'superseded';

CREATE INDEX plans_ticket ON plans(ticket_key, id);

-- Runs the operator granted a ticket beyond its policy attempt limit for a kind counted per ticket (`canopy grant KEY
-- plan`, DESIGN §22, §25). A plan covers every repository the ticket will touch, so its limit is the ticket's, not a
-- unit's, and `attempt_grants` holds only units'. Rows are only added; every run still counts (D030). No agent canopy
-- runs can add one.
CREATE TABLE ticket_grants (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    kind        TEXT NOT NULL CHECK (kind IN ('plan')),
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);

-- The operator's comments on a ticket's plan (DESIGN §25, Commenting on a plan): each a thread on a passage, with its
-- replies, open until the operator resolves it. A thread belongs to the ticket, not to one plan, so it carries from
-- plan to plan, anchored again on each by its passage's words: `quote`, and up to 32 characters either side, whitespace
-- collapsed. Never by a position. Written only by the web channel, behind its token (TRUST_MODEL T8). A comment is the
-- operator's words and the passage it quotes; the plan's text stays in its file.
CREATE TABLE plan_threads (
    id           INTEGER PRIMARY KEY,
    ticket_key   TEXT NOT NULL REFERENCES tickets(key),
    quote        TEXT NOT NULL,
    prefix       TEXT NOT NULL,
    suffix       TEXT NOT NULL,
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    resolved_at  TEXT,
    -- When the operator last sent a plan comment to a planner, as it stands, in a request for changes (DESIGN §25). A
    -- planner whose run started after it has read the comment, so an approval's notes leave it out rather than send the
    -- implement what the plan already answered. Cleared when the comment's words, its replies, or its resolution
    -- change, since it then says something no planner has read. NULL for a comment never sent, and for every one from
    -- before canopy recorded it.
    sent_at      TEXT
);

CREATE INDEX plan_threads_ticket ON plan_threads(ticket_key, id);

CREATE TABLE plan_replies (
    id          INTEGER PRIMARY KEY,
    thread_id   INTEGER NOT NULL REFERENCES plan_threads(id) ON DELETE CASCADE,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX plan_replies_thread ON plan_replies(thread_id, id);

-- Agent memory (DESIGN §28, ROADMAP M50): ticket notes a ticket's runs write for its later runs, proposals workers make
-- for the whole workspace, and the lessons the operator promotes from them. Empty while `memory.ticket_notes` and
-- `memory.proposals` are both off, as they are by default. `body` is NULL once the operator forgot or purged the row:
-- a tombstone that keeps who wrote it and when. Nothing is edited in place: a newer note under a key supersedes the
-- one before it, which stays.
CREATE TABLE memories (
    id              INTEGER PRIMARY KEY,
    scope           TEXT NOT NULL CHECK (scope IN ('ticket', 'proposal', 'lesson')),
    -- A note's ticket, a proposal's source ticket; NULL for a lesson, which is the workspace's.
    ticket_key      TEXT REFERENCES tickets(key),
    -- The repository a proposal or a lesson is about; NULL for every repository, and for a note.
    repo            TEXT,
    key             TEXT NOT NULL,
    body            TEXT,
    status          TEXT NOT NULL CHECK (status IN ('active', 'pending', 'superseded', 'invalid')),
    -- The harness's words for the latest change of status, such as `superseded by note 41`.
    why             TEXT,
    author          TEXT NOT NULL CHECK (author IN ('worker', 'operator')),
    run_id          INTEGER REFERENCES runs(id),
    tick_id         INTEGER REFERENCES ticks(id),
    -- The commit the run's branch was at when its worker ended, `repo@sha` per repository for a joint run.
    head            TEXT,
    supersedes      INTEGER REFERENCES memories(id),
    promoted_from   INTEGER REFERENCES memories(id),
    created_at      TEXT NOT NULL,
    approved_at     TEXT,
    last_used_at    TEXT,
    use_count       INTEGER NOT NULL DEFAULT 0,
    review_at       TEXT,
    invalidated_at  TEXT,
    -- A lesson's latest `memory_wrong` report, and the run that made it, until the operator renews it.
    wrong_at        TEXT,
    wrong_run_id    INTEGER REFERENCES runs(id),
    -- A lesson the operator pinned (DESIGN §28): never due for review, so its `review_at` is NULL while pinned, and
    -- served before every other lesson when the digest's cap leaves some out. NULL on every lesson not pinned, and on
    -- every note and proposal.
    pinned_at       TEXT,
    CHECK ((scope = 'lesson') = (author = 'operator')),
    CHECK ((scope = 'lesson') = (ticket_key IS NULL)),
    CHECK (scope != 'ticket' OR repo IS NULL),
    CHECK ((scope = 'lesson') = (run_id IS NULL)),
    CHECK (status != 'pending' OR scope = 'proposal'),
    CHECK (status != 'active' OR scope != 'proposal'),
    CHECK ((wrong_at IS NULL) = (wrong_run_id IS NULL))
);

CREATE UNIQUE INDEX memories_active ON memories(scope, ifnull(ticket_key, ''), key) WHERE status = 'active';

CREATE INDEX memories_ticket ON memories(ticket_key, status);

CREATE INDEX memories_run ON memories(run_id);

-- Memory by scope and status (DESIGN §28): the proposals waiting, the lessons in force, and the tickets with notes in
-- force, which every tick and the memory page read, found without a scan of every row retention keeps.
CREATE INDEX memories_scope ON memories(scope, status, ticket_key);

-- `canopy memory search` (DESIGN §28, ROADMAP M50 stage 3): a full-text index over each memory's key and body,
-- ranked with bm25(). It holds no text of its own: `memories` is its content, and these triggers keep the index in
-- step with every insert, update, and delete there, so a forgotten or purged body leaves the index with the row.
-- Needs SQLite built with FTS5, which `make install-check` checks.
CREATE VIRTUAL TABLE memories_fts USING fts5(
    key, body, content = 'memories', content_rowid = 'id', tokenize = 'porter unicode61'
);

CREATE TRIGGER memories_fts_insert AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts (rowid, key, body) VALUES (new.id, new.key, new.body);
END;

CREATE TRIGGER memories_fts_delete AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, key, body) VALUES ('delete', old.id, old.key, old.body);
END;

CREATE TRIGGER memories_fts_update AFTER UPDATE OF key, body ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, key, body) VALUES ('delete', old.id, old.key, old.body);
    INSERT INTO memories_fts (rowid, key, body) VALUES (new.id, new.key, new.body);
END;

-- What a run's prompt was rendered under, for each run of a kind a tier reaches dispatched while either tier was not
-- off: each tier's mode (`off` for one that does not reach the run's kind), and the entries `_run` refused from its
-- result, as a JSON list. A run with no row was rendered with both tiers off.
CREATE TABLE run_memory (
    run_id        INTEGER PRIMARY KEY REFERENCES runs(id),
    ticket_notes  TEXT NOT NULL CHECK (ticket_notes IN ('off', 'record', 'use')),
    proposals     TEXT NOT NULL CHECK (proposals IN ('off', 'record', 'use')),
    refused       TEXT NOT NULL DEFAULT '[]'
);

-- Each memory rendered into a run's prompt. Only these count in that run's `memory_used` and `memory_wrong`, and only
-- these notes' keys in its `drop_notes`.
CREATE TABLE memory_reads (
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    memory_id  INTEGER NOT NULL REFERENCES memories(id),
    -- What a run said of each memory rendered into its prompt (DESIGN §28): `used` for one in its `memory_used`,
    -- `wrong` for one in its `memory_wrong`, NULL for one it cited in neither. So a memory names the runs that relied
    -- on it, not only how many did. NULL on every read from before canopy recorded it, whose runs are counted in
    -- `memories.use_count` but not named.
    cited      TEXT CHECK (cited IN ('used', 'wrong')),
    PRIMARY KEY (run_id, memory_id)
);

CREATE INDEX memory_reads_memory ON memory_reads(memory_id);

-- A PR's own title (DESIGN §8, §22), which need not be its ticket's: the one the worker that opened or last updated it
-- reported in its result's `pr_titles`. For display; never read as truth. Keyed by the PR's URL, as
-- `review_runs.pr_url` is, so it outlives `canopy forget`, which drops the unit but not the PR or its reviews.
CREATE TABLE pr_titles (
    pr_url      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Why each `resume` runs (DESIGN §8): one row per reason its dispatch named with `--reason`. The cooldown reads them,
-- holding a `resume` whose only reason is `ci`, and the status views show them beside the run's kind. Other kinds,
-- and runs from before reasons existed, have none.
CREATE TABLE run_reasons (
    run_id  INTEGER NOT NULL REFERENCES runs(id),
    reason  TEXT NOT NULL CHECK (reason IN ('ci', 'review', 'reply', 'conflict', 'no_pr', 'retarget')),
    PRIMARY KEY (run_id, reason)
);

-- Review replies the operator sends (DESIGN §29, ROADMAP M53): what canopy's GitHub reader saw of a PR, the drafts a
-- run wrote in place of the comments it would have posted, each version of a draft's text, and the setting a run was
-- rendered under. Every row the reader writes is replaced on the next whole read of its PR, as ROADMAP M36's
-- observations are; a draft is never edited in place but for its status: its text is its versions.

-- A PR as the reader last read it whole.
CREATE TABLE observed_prs (
    url                  TEXT PRIMARY KEY,
    repository           TEXT NOT NULL,
    number               INTEGER NOT NULL,
    head_sha             TEXT,
    base_ref             TEXT,
    state                TEXT CHECK (state IN ('open', 'merged', 'closed')),
    draft                INTEGER NOT NULL,
    mergeable            TEXT,
    author               TEXT,
    observed_at          TEXT NOT NULL,
    -- A PR's labels, as a JSON list of names, and whether it can merge as its host says.
    labels               TEXT NOT NULL DEFAULT '[]',
    mergeable_state      TEXT CHECK (
        mergeable_state IN ('clean', 'behind', 'blocked', 'dirty', 'draft', 'has_hooks', 'unstable', 'unknown')
    ),
    -- A PR's title as canopy's reader last read it (DESIGN §30): the PR author's text, one line, cut and marked past
    -- 200 characters, for display only, never into a prompt. NULL on a PR read before canopy read titles, and from a
    -- connector that prints none.
    title                TEXT,
    -- A PR's times as canopy's reader last read them (DESIGN §30), each NULL where the reader printed none, as on a PR
    -- read before canopy read them: when it was opened; when it last became ready for review, its creation for one
    -- opened ready and NULL while it is a draft; when a review of it was first asked for at or after that; and when it
    -- merged and when it closed.
    created_at           TEXT,
    ready_at             TEXT,
    review_requested_at  TEXT,
    merged_at            TEXT,
    closed_at            TEXT
);

-- Each review and review comment of a PR, keyed by GitHub's id, with a comment's thread. Bodies are cut as a mirrored
-- comment's are (DESIGN §22).
CREATE TABLE observed_reviews (
    pr_url       TEXT NOT NULL,
    item         TEXT NOT NULL CHECK (item IN ('review', 'comment')),
    id           INTEGER NOT NULL,
    author       TEXT,
    bot          INTEGER NOT NULL,
    -- A review's state; NULL for a comment.
    state        TEXT CHECK (state IN ('pending', 'commented', 'approved', 'changes_requested', 'dismissed')),
    created_at   TEXT,
    body         TEXT NOT NULL,
    url          TEXT,
    -- A comment's review, and its thread: GitHub's node id, where it is, and whether it is outdated or resolved.
    review_id    INTEGER,
    thread_id    TEXT,
    path         TEXT,
    line         INTEGER,
    side         TEXT CHECK (side IN ('left', 'right')),
    outdated     INTEGER,
    resolved     INTEGER,
    observed_at  TEXT NOT NULL,
    number       INTEGER,
    PRIMARY KEY (pr_url, item, id),
    CHECK ((item = 'comment') = (thread_id IS NOT NULL)),
    CHECK (item = 'review' OR state IS NULL)
);

CREATE INDEX observed_reviews_thread ON observed_reviews(thread_id);

-- Each version of a draft's text: the run's own first, then each of the operator's edits.
CREATE TABLE draft_versions (
    draft_id    INTEGER NOT NULL REFERENCES drafts(id),
    version     INTEGER NOT NULL,
    body        TEXT NOT NULL,
    author      TEXT NOT NULL CHECK (author IN ('worker', 'operator')),
    channel     TEXT,
    created_at  TEXT NOT NULL,
    -- Reactions staged with drafts (DESIGN §29): a thread's draft may carry one of the reactions GitHub offers, on the
    -- review comment it names, beside its reply or alone. The reaction is part of each version, as the text is, so an
    -- edit of either is a new version and a send names both.

    -- A version with a reaction may have no text: it sends the reaction alone. One without a reaction needs its text.
    reaction    TEXT CHECK (
        COALESCE(reaction IN ('+1', '-1', 'laugh', 'confused', 'heart', 'hooray', 'rocket', 'eyes'), body != '')
    ),
    PRIMARY KEY (draft_id, version),
    CHECK ((author = 'worker') = (version = 1))
);

-- The `trust.review_replies` a run of a kind that comments was rendered under, whether its prompt asked for a ticket's
-- draft (only with a tracker source that posts, and never on a private ticket), and the drafts `_run` refused from its
-- result in the harness's words, as a JSON list. A run with no row was rendered before the setting existed.
CREATE TABLE run_replies (
    run_id         INTEGER PRIMARY KEY REFERENCES runs(id),
    mode           TEXT NOT NULL CHECK (mode IN ('approve', 'post')),
    ticket_drafts  INTEGER NOT NULL,
    refused        TEXT NOT NULL DEFAULT '[]'
);

-- Each time the operator forgot a ticket's work (DESIGN §22): when, how, the newest run and message then, and the
-- branch and PRs it dropped, which canopy never closes or deletes. The ticket's `forgotten_*` columns stay its latest
-- forget, the boundary every read of the loop's view uses; this is the history behind it, never edited.
CREATE TABLE forgets (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    at          TEXT NOT NULL,
    -- NULL, with `prs`, for a forget made before forgets were recorded: its channel and what it dropped are unknown.
    channel     TEXT CHECK (channel IN ('cli', 'web')),
    run_id      INTEGER REFERENCES runs(id),
    message_id  INTEGER REFERENCES messages(id),
    branch      TEXT,
    -- A JSON array of the URLs of the PRs its units had.
    prs         TEXT,
    CHECK ((channel IS NULL) = (prs IS NULL))
);

CREATE INDEX forgets_ticket ON forgets(ticket_key, id);

-- Triage before a plan (DESIGN §25, ROADMAP M55). `run_reads` holds the repositories a run that leases no slot reads,
-- by name, as dispatch named them: a `needs-plan` run reads each one's primary clone through a link in its desk, and
-- `run_slots` holds only leases. `plan_waivers` holds each plan a triage waived: the triage run, and the reason its
-- validated `done` `trivial` result gave, written by `_run` in the transaction that closes the run, never by an agent
-- and by no command. A waiver is in force while its ticket's own plan setting is unset and no forget came after its
-- run; rows are never deleted.
CREATE TABLE run_reads (
    run_id  INTEGER NOT NULL REFERENCES runs(id),
    repo    TEXT NOT NULL,
    PRIMARY KEY (run_id, repo)
);

CREATE TABLE plan_waivers (
    id          INTEGER PRIMARY KEY,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    run_id      INTEGER NOT NULL UNIQUE REFERENCES runs(id),
    reason      TEXT NOT NULL,
    at          TEXT NOT NULL
);

CREATE INDEX plan_waivers_ticket ON plan_waivers(ticket_key, id);

-- Follow-up tickets (DESIGN §18, ROADMAP M46). An `implement` or `resume` worker that files tickets outside its own
-- reports them in its result, and `_run` records each one its checks pass, in the transaction that closes the run: the
-- follow-up's key, its parent (the run's ticket), the run, the repository it is for or NULL, and when. A recorded
-- follow-up authorizes nothing: canopy asks the operator about it until a queue label or a start authorizes it, as any
-- ticket. Written only from a validated result, never by a command; rows are never deleted. The follow-up is a ticket
-- of the tracker's and may never appear in `tickets`, so it has no foreign key; the parent does, since its dispatch
-- recorded it.
CREATE TABLE follow_ups (
    key         TEXT PRIMARY KEY,
    parent_key  TEXT NOT NULL REFERENCES tickets(key),
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    repo        TEXT,
    at          TEXT NOT NULL
);

CREATE INDEX follow_ups_parent ON follow_ups(parent_key);

-- A comment a run would have posted, waiting on the operator. `number` is its place in the run's result, 1 to 30, as
-- a review's findings are numbered (DESIGN §21). `basis` is the time a comment on its thread must be newer than to
-- refuse a send as `thread_changed`: the run's start, then the newest comment a refusal showed.
CREATE TABLE drafts (
    id                 INTEGER PRIMARY KEY,
    run_id             INTEGER NOT NULL REFERENCES runs(id),
    number             INTEGER NOT NULL CHECK (number BETWEEN 1 AND 30),
    ticket_key         TEXT NOT NULL REFERENCES tickets(key),
    kind               TEXT NOT NULL CHECK (kind IN ('thread', 'pr', 'ticket')),
    -- A thread's or a PR's draft: the unit's repository and its PR; a thread's, the review comment it names.
    repo               TEXT,
    pr_url             TEXT,
    comment_id         INTEGER,
    -- A ticket's draft: the issue it goes to, as the worker named it.
    issue_url          TEXT,
    stance             TEXT CHECK (stance IN ('changed', 'declined', 'answered')),
    -- The thread the reader found the comment on, once a whole read checked the draft.
    thread_id          TEXT,
    status             TEXT NOT NULL CHECK (
        status IN (
            'unchecked', 'waiting', 'refused', 'superseded', 'dropped', 'sending', 'unconfirmed', 'staged', 'sent'
        )
    ),
    -- The harness's words for the latest change of status, such as `superseded by run 41's draft 2`.
    why                TEXT,
    basis              TEXT NOT NULL,
    superseded_by      INTEGER REFERENCES drafts(id),
    created_at         TEXT NOT NULL,
    checked_at         TEXT,
    -- A send's claim: when it began, the version it sends, and the pending review the post reported, if any, by its
    -- node id, which a later post deletes it by, and its id, which a later read settles an unconfirmed send by. A
    -- staged draft keeps its pending review's ids until a read settles it.
    send_started_at    TEXT,
    send_version       INTEGER,
    pending_review     TEXT,
    pending_review_id  INTEGER,
    -- What a sent draft became on GitHub, and through which channel the operator sent it. A staged reply's comment id
    -- is known from the start, so the loop knows it as the operator's whenever they submit it.
    sent_at            TEXT,
    sent_comment_id    INTEGER,
    sent_review_id     INTEGER,
    sent_url           TEXT,
    sent_channel       TEXT,
    -- The reaction a send added on GitHub, and when. A send adds its reactions before its review, so one whose review
    -- then failed keeps them here: they stay on GitHub, and sending again adds nothing more.
    reacted            TEXT CHECK (reacted IN ('+1', '-1', 'laugh', 'confused', 'heart', 'hooray', 'rocket', 'eyes')),
    reacted_at         TEXT,
    -- Drafts that start from a feedback plan (DESIGN §32, On the PR, and the drafts after): a `resume` that follows an
    -- approved feedback plan starts each thread's draft from the reply the plan proposed for its item. `plan_item` is
    -- the number of that item in its run's feedback plan (`runs.feedback_plan_id`), recorded by `_run` as it writes the
    -- draft, or by the read that checks it when only that read places the draft's comment on the item's thread. Whether
    -- the draft departs from the proposal is computed from the two texts, never said by the worker. NULL for a draft
    -- whose run followed no feedback plan, and for one answering no thread the plan covers.
    plan_item          INTEGER CHECK (plan_item > 0),
    UNIQUE (run_id, number),
    CHECK ((kind = 'ticket') = (pr_url IS NULL)),
    CHECK ((kind = 'ticket') = (issue_url IS NOT NULL)),
    CHECK ((kind = 'thread') = (comment_id IS NOT NULL)),
    CHECK ((kind = 'thread') = (stance IS NOT NULL)),
    CHECK ((status = 'sent') = (sent_at IS NOT NULL)),
    CHECK (status != 'staged' OR (kind != 'ticket' AND pending_review_id IS NOT NULL))
);

CREATE INDEX drafts_pr ON drafts(pr_url, status);

CREATE INDEX drafts_ticket ON drafts(ticket_key, status);

-- The connectors (DESIGN §30, ROADMAP M36): what each tick's run of a source read of the world, and each run. Every
-- observation is replaced whole on the next run that reads its subject whole (a ticket, a PR, a repository), so a
-- label, check, or branch gone from the source is gone from here; a subject not read whole keeps its rows and their
-- age. Nothing here is authority: an observation says what a connector saw and when.

-- A ticket as the tracker connector last read it whole. `labels` is a JSON list of `{"name", "added_at"}`, `added_at`
-- null where the tracker does not say; `blockers` a JSON list of the keys it names as blocking it.
CREATE TABLE observed_tickets (
    key          TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    state        TEXT NOT NULL CHECK (state IN ('open', 'closed')),
    labels       TEXT NOT NULL,
    updated_at   TEXT,
    blockers     TEXT NOT NULL,
    observed_at  TEXT NOT NULL
);

-- Each comment the tracker connector read, once per ticket and comment id, as it first read it: an edit after is not
-- followed, as a mirrored comment's is not. Kept apart from `messages`, so no prompt carries a comment the overseer
-- did not mirror (DESIGN §30). `body` is cut at the mirror's length, `truncated` saying so; `source` is `worker` when
-- the comment carries the workers' marks (D069).
CREATE TABLE observed_comments (
    ticket        TEXT NOT NULL,
    id            TEXT NOT NULL,
    author        TEXT NOT NULL,
    commented_at  TEXT NOT NULL,
    body          TEXT NOT NULL,
    truncated     INTEGER NOT NULL CHECK (truncated IN (0, 1)),
    source        TEXT NOT NULL CHECK (source IN ('tracker', 'worker')),
    observed_at   TEXT NOT NULL,
    -- The journal number (DESIGN §35) the comment took in `item_numbers` when a source first observed it, as each
    -- review item, completed check run, and ended review run has its own; NULL for a check with no completed run, and
    -- a review run not ended.
    number        INTEGER,
    PRIMARY KEY (ticket, id)
);

-- Each branch under `trust.branch_prefix` in a repository of the map, by the map's name for it.
CREATE TABLE observed_branches (
    repository   TEXT NOT NULL,
    name         TEXT NOT NULL,
    head_sha     TEXT NOT NULL,
    observed_at  TEXT NOT NULL,
    PRIMARY KEY (repository, name)
);

-- Each named context at a PR's head, a check run or a commit status, never the combined status.
CREATE TABLE observed_checks (
    pr_url       TEXT NOT NULL,
    name         TEXT NOT NULL,
    head_sha     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (
        status IN ('requested', 'queued', 'waiting', 'pending', 'in_progress', 'completed')
    ),
    conclusion   TEXT CHECK (
        conclusion IN (
            'success', 'failure', 'error', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required',
            'startup_failure', 'stale'
        )
    ),
    run_id       INTEGER,
    url          TEXT,
    observed_at  TEXT NOT NULL,
    number       INTEGER,
    PRIMARY KEY (pr_url, name)
);

-- Each run of a source: a tick's, or the loop's poll between ticks, whose `tick_id` is NULL. `request` is what it was
-- sent, as JSON; `recorded` and `refused` count its lines of each kind, as a JSON object; `missed` is the harness's
-- words for what it did not read, NULL for an `ok` run. The query's and the review query's results, as JSON lists of
-- keys and URLs in order, are kept when the run read them to the end.
CREATE TABLE connector_runs (
    id                   INTEGER PRIMARY KEY,
    tick_id              INTEGER REFERENCES ticks(id),
    source               TEXT NOT NULL,
    kind                 TEXT NOT NULL CHECK (kind IN ('tracker', 'vcs', 'artifacts', 'slack')),
    started_at           TEXT NOT NULL,
    ended_at             TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('ok', 'partial', 'failed')),
    request              TEXT NOT NULL,
    recorded             TEXT NOT NULL,
    refused              TEXT NOT NULL,
    missed               TEXT,
    stderr               TEXT NOT NULL,
    query_result         TEXT,
    review_query_result  TEXT,
    CHECK ((status = 'ok') = (missed IS NULL))
);

CREATE INDEX connector_runs_source ON connector_runs(source, id);

CREATE INDEX connector_runs_tick ON connector_runs(tick_id);

-- Plans before feedback runs (DESIGN §32, ROADMAP M54): one row per plan a feedback plan run wrote for what came back
-- to a ticket's PRs, and one per item it covers. As a ticket's plan's (`plans`), a plan's text is never here: it is the
-- file `<state_dir>/plans/<ticket_key>/<run_id>.md`, which the row is recorded after. The repositories it covers are
-- its run's slots. A new feedback plan supersedes the one before it, so a ticket has at most one waiting or approved.
-- An approval goes ahead once: the `resume` that starts on it is recorded as spending it, in the transaction that
-- inserts that run. Rows are never deleted.
CREATE TABLE feedback_plans (
    id                   INTEGER PRIMARY KEY,
    ticket_key           TEXT NOT NULL REFERENCES tickets(key),
    run_id               INTEGER NOT NULL UNIQUE REFERENCES runs(id),
    created_at           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'superseded')),
    sha256               TEXT NOT NULL,
    size                 INTEGER NOT NULL,
    approved_sha256      TEXT,
    approved_at          TEXT,
    approved_channel     TEXT,
    spent_run_id         INTEGER UNIQUE REFERENCES runs(id),
    approved_reason      TEXT CHECK ((approved_channel IS 'planner') = (approved_reason IS NOT NULL)),
    effort               TEXT CHECK (effort IN ('small', 'medium', 'large')),
    -- The SHA-256 of what changed that an approval of a stale plan was last refused for (`stale`): approving again,
    -- with nothing more changed, approves it.
    stale_shown          TEXT,
    -- The operator message the approval wrote on the ticket, naming the plan and its items by number, with the
    -- operator's own words when they gave some: the instruction its `resume` reads beside the plan. NULL for a plan not
    -- approved, and for one its planner approved, which writes no message.
    approved_message_id  INTEGER REFERENCES messages(id),
    CHECK ((approved_sha256 IS NULL) = (approved_at IS NULL) AND (approved_at IS NULL) = (approved_channel IS NULL)),
    CHECK (status != 'approved' OR approved_at IS NOT NULL),
    CHECK (status != 'proposed' OR approved_at IS NULL),
    CHECK (spent_run_id IS NULL OR approved_at IS NOT NULL)
);

CREATE UNIQUE INDEX feedback_plans_current ON feedback_plans(ticket_key) WHERE status != 'superseded';

CREATE INDEX feedback_plans_ticket ON feedback_plans(ticket_key, id);

-- Each item a feedback plan covers, in the order its result line named them: a review or a review comment of one of
-- its PRs, by the id the `vcs` source observed (DESIGN §29), what the plan proposes for it, and for a change or a
-- decline the reply it would draft. Model text, bounded as a draft's; never an instruction. A failed check at a PR's
-- head, the PR's conflict with its base, and a merged PR it was stacked on (§10) are items too (DESIGN §32, What a plan
-- covers), planned, approved, and left out by number as the rest are. None has an id the `vcs` source observed, so
-- canopy gives each one, always below zero, where no observed id is (`feedback_items.check_id`, `conflict_id`, and
-- `blocker_id`); none has an author, so none has a reply.
CREATE TABLE feedback_plan_items (
    plan_id   INTEGER NOT NULL REFERENCES feedback_plans(id),
    number    INTEGER NOT NULL CHECK (number > 0),
    pr_url    TEXT NOT NULL,
    item      TEXT NOT NULL CHECK (item IN ('review', 'comment', 'check', 'conflict', 'blocker')),
    item_id   INTEGER NOT NULL,
    proposal  TEXT NOT NULL CHECK (proposal IN ('change', 'decline', 'ask', 'leave')),
    reply     TEXT,
    -- Approval by item (DESIGN §32, Approving): the operator may approve a feedback plan with some of its items left
    -- out, which its `resume` must not act on and the next plan is offered again. `left_out` is 1 for such an item of
    -- an approved plan, 0 otherwise; approving again sets it afresh, and approving whole clears it.
    left_out  INTEGER NOT NULL DEFAULT 0 CHECK (left_out IN (0, 1)),
    PRIMARY KEY (plan_id, number),
    UNIQUE (plan_id, pr_url, item, item_id),
    CHECK ((item IN ('check', 'conflict', 'blocker')) = (item_id < 0)),
    CHECK (item IN ('review', 'comment') OR reply IS NULL)
);

-- Which models served each agent run (DESIGN §13, Each agent's model), read from the runtime's own record of the run's
-- session after the run ended: a tick's overseer, a worker or plan run, a chore run, a review run, a task's run, or an
-- epic's plan run, named by `run_table` and `run_id` as in `run_tools`. Past runs are read too, a few each tick, so no
-- row says a run has none.

-- Each run whose session canopy asked the runtime about, and how its last read ended: `found`, its models in
-- `run_models`; `missing`, the runtime keeps no such session; or `failed`, with canopy's words for why in `error`.
-- `attempts` counts the reads. A `found` or `missing` run is not read again.
CREATE TABLE run_model_reads (
    run_table        TEXT NOT NULL CHECK (
        run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs', 'epic_runs')
    ),
    run_id           INTEGER NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('found', 'missing', 'failed')),
    error            TEXT,
    attempts         INTEGER NOT NULL,
    read_at          TEXT NOT NULL,
    -- The version of the agent runtime that ran each agent run, as its session's record names it (DESIGN §13): a change
    -- to how the runtime lays out a run's prompt, which no digest of canopy's definitions shows, splits the runs into
    -- before and after. NULL where the record names none, and on every run read before canopy recorded it.
    runtime_version  TEXT,
    PRIMARY KEY (run_table, run_id),
    CHECK ((status = 'failed') = (error IS NOT NULL))
) WITHOUT ROWID;

-- Each model a `found` run's session names as having written its replies: how many it wrote, and what they cost in
-- US dollars, as the runtime priced them. None for a session that made no model call.
CREATE TABLE run_models (
    run_table        TEXT NOT NULL CHECK (
        run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs', 'epic_runs')
    ),
    run_id           INTEGER NOT NULL,
    model            TEXT NOT NULL,
    replies          INTEGER NOT NULL,
    cost_usd         REAL NOT NULL,
    PRIMARY KEY (run_table, run_id, model)
) WITHOUT ROWID;

-- What the operator has seen (DESIGN §22): a subject whose result is new to them until they open it, in the web UI or
-- the CLI. A row is one subject, named as its reference names it (`review:4` is kind `review`, subject `4`), so a new
-- kind of subject takes a value of `kind` and no table of its own. A mark is the operator's alone, as a dismissal is:
-- it authorizes nothing, no agent reads it, and seeing a subject again records nothing new.
--
-- A row with no channel is a review run that had ended when canopy began to keep these marks, taken as seen so the
-- reviews from before were not all new at once: no channel saw them.
CREATE TABLE seen (
    kind             TEXT NOT NULL CHECK (kind IN ('review')),
    subject          TEXT NOT NULL,
    at               TEXT NOT NULL,
    channel          TEXT CHECK (channel IN ('cli', 'web')),
    PRIMARY KEY (kind, subject)
);

-- The web UI's write requests (TRUST_MODEL T8, DESIGN §22): each request of a method but GET and HEAD that the server
-- let through, a sign-in or a write whose session, token, and Origin it accepted, however the verb then answered it,
-- so the operator can see what a holder of the listener secret did. `path` is the request's own, without its query, at
-- most 512 characters; `code` the HTTP status it was answered with; `client` the peer's address; `session` a
-- fingerprint of the session, NULL on the mock server, which signs nobody in. Never the request's body, headers,
-- query, cookie, or token. Written only by the server once it has answered, so `id` order may differ from `at` order;
-- rows are never deleted.
CREATE TABLE web_writes (
    id       INTEGER PRIMARY KEY,
    at       TEXT NOT NULL,
    method   TEXT NOT NULL,
    path     TEXT NOT NULL,
    code     INTEGER NOT NULL,
    client   TEXT,
    session  TEXT
);

-- The derivation, in shadow (DESIGN §30, ROADMAP M36): what each tick derived in code of §7's table, from the
-- observations and the journal, beside the overseer's decisions, which it never touches. A row is one subject a tick
-- derived: a ticket's own phases, `repo` NULL, or a unit's. `phases` is a JSON list of every row of §7 that held,
-- since §7 has no order between them yet; empty when none did, and when the subject depends on an observation stale or
-- missing, which `stale` then names. `overseer_phase` is the phase the journal held for the subject when the tick
-- closed: the overseer's, kept here since the journal keeps only a ticket's latest. Agreement is computed from these
-- and the tick's decisions, never stored, so a fix to the comparison reads every tick already recorded.
CREATE TABLE derivations (
    id              INTEGER PRIMARY KEY,
    tick_id         INTEGER NOT NULL REFERENCES ticks(id),
    ticket_key      TEXT NOT NULL,
    repo            TEXT,
    -- A ticket's own row: whether it is a candidate (DESIGN §17), and whether the tracker said it is closed. NULL on a
    -- unit's row, and on a stale one.
    candidate       INTEGER CHECK (candidate IN (0, 1)),
    closed          INTEGER CHECK (closed IN (0, 1)),
    phases          TEXT NOT NULL,
    stale           TEXT,
    overseer_phase  TEXT CHECK (
        overseer_phase IN (
            'ready', 'blocked', 'running', 'pushed_no_pr', 'conflicted', 'ci_running', 'ci_red', 'review_pending',
            'review_findings', 'changes_requested', 'untrusted_review', 'green_unreviewed', 'approved', 'merged',
            'needs_human', 'human_replied', 'split', 'plan_proposed'
        )
    ),
    CHECK (repo IS NULL OR (candidate IS NULL AND closed IS NULL)),
    CHECK (stale IS NULL OR (phases = '[]' AND candidate IS NULL AND closed IS NULL))
);

CREATE INDEX derivations_tick ON derivations(tick_id);

-- A version of a review's draft: the review's body, and its comments as a JSON list of {"path", "line", "text"} on
-- lines of the diff the review kept, a comment made from a finding naming it as "finding". The reviewer's is the first;
-- each of the operator's edits, drops, additions, and dismissals is a new one, `change` saying which in the harness's
-- words. `refused` is a JSON list of what canopy left out as it made the version, and why, in the harness's words.
CREATE TABLE review_draft_versions (
    draft_id    INTEGER NOT NULL REFERENCES review_drafts(id),
    version     INTEGER NOT NULL CHECK (version > 0),
    body        TEXT NOT NULL,
    comments    TEXT NOT NULL,
    author      TEXT NOT NULL CHECK (author IN ('reviewer', 'reviser', 'operator')),
    channel     TEXT CHECK (channel IN ('cli', 'web')),
    change      TEXT NOT NULL,
    refused     TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (draft_id, version),
    CHECK ((author = 'operator') = (channel IS NOT NULL))
);

-- What the runtime offered each agent run (DESIGN §13), asked as the run started, by its own command: a tick's
-- overseer, a worker or plan run, a chore run, or a review run, named by `run_table` and `run_id` as in `run_tools`.
-- A run from before canopy asked, or whose command it never ran, has no row.

-- Each run canopy asked about: the agent its command runs, and canopy's words for why the runtime could not say, NULL
-- when it said. `agent` is NULL when the command names none.
CREATE TABLE run_offers (
    run_table   TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id      INTEGER NOT NULL,
    agent       TEXT,
    error       TEXT,
    asked_at    TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id),
    CHECK (agent IS NOT NULL OR error IS NOT NULL)
) WITHOUT ROWID;

-- Each MCP server a run that said was offered: `all` of its tools or only `some`. A server its config turns off, or
-- whose every tool the agent's rules deny, is not among them.
CREATE TABLE run_offered_servers (
    run_table   TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id      INTEGER NOT NULL,
    server      TEXT NOT NULL,
    reach       TEXT NOT NULL CHECK (reach IN ('all', 'some')),
    PRIMARY KEY (run_table, run_id, server)
) WITHOUT ROWID;

-- Each skill a run that said was offered, by name.
CREATE TABLE run_offered_skills (
    run_table   TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id      INTEGER NOT NULL,
    skill       TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, skill)
) WITHOUT ROWID;

-- More of what the runtime offered each agent run (DESIGN §13), beside `run_offers`: the runtime's own tools, and the
-- rules that leave a run only `some` of a server's tools. A run recorded before them has none of either.

-- Each of the runtime's built-in tools a run that said was offered, by name. Its MCP servers' tools are not among them.
CREATE TABLE run_offered_tools (
    run_table   TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id      INTEGER NOT NULL,
    tool        TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, tool)
) WITHOUT ROWID;

-- Each rule that makes a server's reach `some`, in the order they apply, the last that matches a tool winning:
-- `offer` or `deny`, then the tool names it matches as the runtime's patterns write them.
CREATE TABLE run_offered_server_rules (
    run_table   TEXT NOT NULL CHECK (run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs')),
    run_id      INTEGER NOT NULL,
    server      TEXT NOT NULL,
    position    INTEGER NOT NULL,
    rule        TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, server, position)
) WITHOUT ROWID;

-- The operator's choices for one of a ticket's agents, each in force until cleared (DESIGN §31): one row a ticket,
-- agent, and kind of choice. `persona` names the persona the agent's runs for the ticket write in, in place of its
-- default in `[personas]`; `model` is reserved for the model the operator chooses per ticket (DESIGN §13, ROADMAP
-- M58), which nothing sets yet. Set only by the operator, from `canopy persona` or the ticket's page, and never by an
-- agent. A ticket canopy has not seen may have one, so the key references no table; `canopy forget` keeps it. A clear
-- deletes the row.
CREATE TABLE ticket_overrides (
    ticket_key  TEXT NOT NULL,
    agent       TEXT NOT NULL CHECK (agent IN ('worker', 'planner', 'reviewer')),
    kind        TEXT NOT NULL CHECK (kind IN ('persona', 'model')),
    -- What the operator chose: a persona's name, or a `provider/model` id.
    value       TEXT NOT NULL,
    channel     TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    set_at      TEXT NOT NULL,
    PRIMARY KEY (ticket_key, agent, kind)
);

-- The personas the operator chose for a review request (DESIGN §31): the voice its review is written in, in place of
-- `[personas] reviewer`. A request with no row here gets that default. Set only by the operator, with
-- `canopy start URL --review --persona` or `canopy persona URL`, and never by an agent; asking again with a persona
-- replaces the request's set.
CREATE TABLE review_request_personas (
    request_id  INTEGER NOT NULL REFERENCES review_requests(id),
    persona     TEXT NOT NULL,
    PRIMARY KEY (request_id, persona)
);

-- The persona the operator chose for the next run alone of one of a ticket's agents (DESIGN §31), in place of the
-- ticket's override and `[personas]`: one row a ticket and agent. Set only by the operator, with
-- `canopy persona KEY NAME --next`, `canopy start KEY --persona`, or `canopy plan KEY --persona`, and never by an
-- agent. The dispatch that records the agent's next run for the ticket deletes it in the same transaction, so it
-- reaches that run alone; the run records the persona it ran in. A ticket canopy has not seen may have one.
CREATE TABLE next_run_personas (
    ticket_key  TEXT NOT NULL,
    agent       TEXT NOT NULL CHECK (agent IN ('worker', 'planner')),
    persona     TEXT NOT NULL,
    channel     TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    set_at      TEXT NOT NULL,
    PRIMARY KEY (ticket_key, agent)
);

-- The text of each persona a run or a review was given, once per digest (DESIGN §31): what `runs.persona_digest` and
-- `review_runs.persona_digest` name, kept so the operator reads the instructions a run read after its persona's file
-- is edited or gone. Written with the run that first carries the digest, and never changed: a text is its digest's.
CREATE TABLE persona_texts (
    digest       TEXT PRIMARY KEY,
    text         TEXT NOT NULL,
    recorded_at  TEXT NOT NULL
);

-- One-off tasks (DESIGN §36): work the operator hands canopy in their own words, about no ticket. Only the operator's
-- channels write a row, refused inside a tick or any run: the submission is the authorization, and its text their
-- instruction. A task is stopped, never deleted, so its runs stay to read. `repo` is the repository it runs in, by its
-- name in the map; `project` the tracker project its tickets may go in, NULL for none.
CREATE TABLE tasks (
    id            INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    repo          TEXT NOT NULL,
    project       TEXT,
    channel       TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    submitted_at  TEXT NOT NULL,
    stopped_at    TEXT
);

-- A task's runs, each started by a tick before its overseer, in a slot of the task's repository's pool leased as
-- `canopy:task:<id>`. A task has no ticket, so its runs are not `runs` rows. `branch` is `<branch_prefix>task/<id>`,
-- a shape no ticket's branch takes; `head` the commit it was at on origin when the run ended, NULL when nothing was
-- pushed. `git_link` is what the slot's `.git` file held when the run started, as `run_slots.git_link`.
CREATE TABLE task_runs (
    id                        INTEGER PRIMARY KEY,
    task_id                   INTEGER NOT NULL REFERENCES tasks(id),
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    branch                    TEXT NOT NULL,
    repo                      TEXT NOT NULL,
    slot_path                 TEXT NOT NULL,
    lease_id                  TEXT NOT NULL,
    lease_holder              TEXT NOT NULL,
    base_branch               TEXT NOT NULL,
    pool                      TEXT NOT NULL CHECK (pool IN ('treehouse', 'canopy')),
    git_link                  BLOB,
    pid                       INTEGER,
    agent_pid                 INTEGER,
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'done', 'blocked', 'failed', 'unknown', 'unpushed', 'crashed', 'timeout', 'stopped')
    ),
    result_json               TEXT,
    head                      TEXT,
    log_path                  TEXT NOT NULL,
    session_id                TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    tokens_peak_context       INTEGER,
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    definitions_digest        TEXT,
    -- The newest message about its task when the run started: its prompt carries the conversation up to it, and a reply
    -- of the operator's past it queues the task's next run. NULL when the task had none.
    message_id                INTEGER REFERENCES messages(id),
    -- What a one-off task leaves (DESIGN §36, ROADMAP M61): a run's report is a file in the state directory, as a plan
    -- is, and the journal holds its hash as `_task` kept it, never its text. NULL when the run left none.
    report_sha256             TEXT,
    tokens_first_cache_read   INTEGER,
    model                     TEXT,
    -- A one-off task's run keeps its agent's progress, its card, as a worker's, planner's, and reviewer's runs do
    -- (DESIGN §41): the columns of the same names on `runs` and `review_runs`, read and written the same way. A
    -- task's run asks no question on its card, so its question's three stay NULL. NULL, and 0 calls, on a run that
    -- never called `status`, and on every run from before canopy recorded it.
    card_json                 TEXT,
    card_at                   TEXT,
    card_calls                INTEGER,
    tool_calls                INTEGER NOT NULL DEFAULT 0,
    card_working_since        TEXT,
    card_asked_at             TEXT,
    card_answer               TEXT CHECK (card_answer IN ('A', 'B', 'C', 'D', 'E')),
    card_answered_at          TEXT,
    card_lapses               INTEGER NOT NULL DEFAULT 0,
    card_stale                INTEGER NOT NULL DEFAULT 0 CHECK (card_stale IN (0, 1))
);

CREATE INDEX task_runs_task ON task_runs(task_id, started_at);

CREATE INDEX task_runs_running ON task_runs(status) WHERE status = 'running';

-- What `canopy spend` and `health` read a window of, as `runs_spent`.
CREATE INDEX task_runs_spent ON task_runs(started_at, cost_usd);

-- Each pass of garbage collection (DESIGN §26): when it ran, the retention it ran with, and what it removed. A file of
-- a row that ended before a pass's cutoff for its kind, and is gone, went by retention, which is how the web UI says
-- so. A cutoff is NULL when its kind is kept forever. `removed` counts, by the kind `canopy gc --dry-run` names, the
-- files removed and their bytes, as a JSON object of `{"files", "bytes"}`; `failures` the files it could not remove.
-- `tick_id` is NULL for a pass run by hand.
CREATE TABLE gc_passes (
    id               INTEGER PRIMARY KEY,
    tick_id          INTEGER REFERENCES ticks(id),
    started_at       TEXT NOT NULL,
    ended_at         TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    run_files_days   INTEGER NOT NULL,
    tick_files_days  INTEGER NOT NULL,
    run_cutoff       TEXT,
    tick_cutoff      TEXT,
    removed          TEXT NOT NULL,
    failures         INTEGER NOT NULL,
    error            TEXT,
    CHECK ((status = 'ok') = (error IS NULL))
);

-- Revising a review's draft with an agent (DESIGN §34, ROADMAP M43). The operator's note on a draft asks for a
-- revision while it is newer than the draft's newest version: `after_version` is the newest version when the note was
-- written, so a note is newer exactly while no version has been made since. A note is the operator's alone, written
-- through their channels (`canopy reply review:ID`), never by an agent; it is the reviser's only instruction.
CREATE TABLE review_draft_notes (
    id             INTEGER PRIMARY KEY,
    draft_id       INTEGER NOT NULL REFERENCES review_drafts(id),
    after_version  INTEGER NOT NULL CHECK (after_version > 0),
    body           TEXT NOT NULL,
    channel        TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    created_at     TEXT NOT NULL
);

CREATE INDEX review_draft_notes_draft ON review_draft_notes(draft_id, after_version);

-- Revisions the operator granted a draft beyond `policy.max_revisions_per_draft` (`canopy grant review:ID revision`).
-- Rows are only added: a draft's limit is the policy's plus the sum of its grants, and every revision still counts
-- (D030). No agent canopy runs can add one.
CREATE TABLE review_draft_grants (
    id          INTEGER PRIMARY KEY,
    draft_id    INTEGER NOT NULL REFERENCES review_drafts(id),
    runs        INTEGER NOT NULL CHECK (runs > 0),
    granted_at  TEXT NOT NULL
);

CREATE INDEX review_draft_grants_draft ON review_draft_grants(draft_id);

-- The tickets a task's runs reported filing in the project its submission names, each checked on its text alone
-- (D003). A row authorizes nothing: it names no ticket canopy works, and only the operator's label or start does.
CREATE TABLE task_tickets (
    id           INTEGER PRIMARY KEY,
    task_id      INTEGER NOT NULL REFERENCES tasks(id),
    task_run_id  INTEGER NOT NULL REFERENCES task_runs(id),
    key          TEXT NOT NULL,
    at           TEXT NOT NULL,
    UNIQUE (task_id, key)
);

CREATE INDEX task_tickets_run ON task_tickets(task_run_id);

-- What each feedback plan saw (DESIGN §32, Planning again): from the read its run made of its PRs before the planner
-- started, each PR's head, each check's conclusion at that head, and each item and reply it was given, by id with a
-- SHA-256 of its body, never its text. The observations (`observed_prs`, `observed_reviews`, `observed_checks`) are
-- replaced whole on every read of a PR, so this is what says what changed on a PR since its plan was written. Kept with
-- their plan; rows are never deleted.

-- Each PR a plan read, and its head then.
CREATE TABLE feedback_plan_prs (
    plan_id         INTEGER NOT NULL REFERENCES feedback_plans(id),
    pr_url          TEXT NOT NULL,
    head_sha        TEXT,
    -- Whether each PR a plan read conflicted with its base then: 1 or 0 as its host said, and NULL while it had not
    -- said, or for a plan from before canopy recorded it, which was offered no conflict, so that a conflict on its PR
    -- since makes it stale.
    conflicted      INTEGER CHECK (conflicted IN (0, 1)),
    -- The merged PR each PR a plan read was stacked on then, by URL: NULL when it was on none, or for a plan from
    -- before canopy recorded it, which was offered no merged blocker, so that a blocker merging under its PR since
    -- makes it stale.
    merged_blocker  TEXT,
    PRIMARY KEY (plan_id, pr_url)
);

-- Each named check at that head, with its conclusion then, NULL while it had none.
CREATE TABLE feedback_plan_checks (
    plan_id     INTEGER NOT NULL REFERENCES feedback_plans(id),
    pr_url      TEXT NOT NULL,
    name        TEXT NOT NULL,
    conclusion  TEXT CHECK (
        conclusion IN (
            'success', 'failure', 'error', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required',
            'startup_failure', 'stale'
        )
    ),
    PRIMARY KEY (plan_id, pr_url, name)
);

-- Each review and review comment a plan was given: an item, or a reply given beside the item it answers, `answers`
-- naming that item's id.
CREATE TABLE feedback_plan_seen (
    plan_id      INTEGER NOT NULL REFERENCES feedback_plans(id),
    pr_url       TEXT NOT NULL,
    item         TEXT NOT NULL CHECK (item IN ('review', 'comment')),
    item_id      INTEGER NOT NULL,
    thread_id    TEXT,
    author       TEXT,
    body_sha256  TEXT NOT NULL,
    answers      INTEGER,
    PRIMARY KEY (plan_id, pr_url, item, item_id),
    CHECK ((item = 'comment') = (thread_id IS NOT NULL)),
    CHECK (answers IS NULL OR item = 'comment')
);

-- Each head and check of a waiting plan's PR, with the value it has now and when the harness first saw it take that
-- value since it last held another. `name` is a check's name, '' for the head; `value` the head's sha or the
-- conclusion, '' for none. The quiet period runs from the newest a moved one took, as from the newest item, so a stream
-- of pushes or a flapping check keeps it running.
CREATE TABLE feedback_plan_moves (
    plan_id  INTEGER NOT NULL REFERENCES feedback_plans(id),
    pr_url   TEXT NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('head', 'check')),
    name     TEXT NOT NULL,
    value    TEXT NOT NULL,
    seen_at  TEXT NOT NULL,
    PRIMARY KEY (plan_id, pr_url, kind, name)
);

-- A review's draft (DESIGN §34, ROADMAP M43): a `done` review of a PR the loop does not own, as the comment review the
-- operator may publish on it in their own name. One draft a review run, made as the review ends `done`; a review that
-- names a ticket, or of a PR a ticket's unit holds, has none. Its versions are each exactly what would post. A draft
-- publishes, or stages, one version at most once: `publishing` while a post holds it, `unconfirmed` when the post
-- ended without saying whether it submitted, `staged` while a pending review holding it waits on the operator on
-- GitHub, and `published` once a review holding it is submitted. A whole read of the PR settles the two between. A
-- draft the operator `discarded` is seen, and not to be posted: it takes no edit, note, or publish, and answers its
-- PR's `review_waiting` item as a published one does, `why` naming the channel.
CREATE TABLE review_drafts (
    id                   INTEGER PRIMARY KEY,
    review_run_id        INTEGER NOT NULL UNIQUE REFERENCES review_runs(id),
    pr_url               TEXT NOT NULL,
    -- The commit the review read, which the review is posted on.
    sha                  TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (
        status IN ('waiting', 'publishing', 'unconfirmed', 'staged', 'published', 'discarded')
    ),
    -- The harness's words for the latest change of status, such as a post GitHub refused.
    why                  TEXT,
    created_at           TEXT NOT NULL,
    -- A publish's claim: the version it posts, when it began, and through which channel.
    publish_version      INTEGER,
    publish_started_at   TEXT,
    publish_channel      TEXT CHECK (publish_channel IN ('cli', 'web')),
    -- The pending review a post reported, by its node id, which a later post deletes it by, and its id, which a read
    -- settles an unconfirmed or staged draft by.
    pending_review       TEXT,
    pending_review_id    INTEGER,
    -- What the published review became on GitHub: its id and URL, and each comment's, as a JSON list in the version's
    -- order of {"id", "url"}.
    published_at         TEXT,
    published_review_id  INTEGER,
    published_url        TEXT,
    published_comments   TEXT,
    CHECK ((status = 'published') = (published_at IS NOT NULL)),
    CHECK (status IN ('waiting', 'discarded') OR publish_version IS NOT NULL),
    CHECK (status != 'staged' OR pending_review_id IS NOT NULL)
);

CREATE INDEX review_drafts_pr ON review_drafts(pr_url, status);

-- How far each `artifacts` source has read its feed: `through` is the cursor its next run reads from, which only goes
-- up; `read_at` is when a run last read the feed to its `end` line with nothing refused, NULL until one has.
CREATE TABLE observed_feeds (
    source   TEXT PRIMARY KEY,
    through  INTEGER NOT NULL CHECK (through >= 0),
    read_at  TEXT
);

-- Each thread on an artifact, as the newest change read of it left it. `origin` is the artifact's origin pairs, as a
-- JSON object; `ticket` its `canopy.ticket` where that is a ticket's key. `exact`, `prefix`, and `suffix` are its
-- anchor, all NULL for a thread on the whole artifact, and `anchor_status` whether the passage was in the artifact's
-- latest version when the store printed the change, NULL with no anchor or when the store does not say.
CREATE TABLE observed_artifact_threads (
    id                TEXT PRIMARY KEY,
    artifact_id       TEXT NOT NULL,
    origin            TEXT NOT NULL,
    ticket            TEXT,
    exact             TEXT,
    prefix            TEXT,
    suffix            TEXT,
    anchored_version  INTEGER NOT NULL,
    state             TEXT NOT NULL CHECK (state IN ('open', 'resolved')),
    anchor_status     TEXT CHECK (anchor_status IN ('found', 'passage_gone')),
    seq               INTEGER NOT NULL,
    observed_at       TEXT NOT NULL
);

CREATE INDEX observed_artifact_threads_ticket ON observed_artifact_threads(ticket);

-- Each comment on an artifact, as the newest change read of it left it: an edit or a deletion replaces it, and a
-- deleted comment keeps its row with its body empty. `author` is the store's id for who wrote it; `body` is cut at the
-- mirror's length, `truncated` saying so; `marked` is whether it carries every one of the workers' marks (D069).
CREATE TABLE observed_artifact_comments (
    id            TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL REFERENCES observed_artifact_threads(id),
    author        TEXT NOT NULL,
    author_name   TEXT NOT NULL,
    author_kind   TEXT NOT NULL CHECK (author_kind IN ('person', 'agent')),
    on_behalf_of  TEXT,
    via           TEXT NOT NULL CHECK (via IN ('web', 'mcp')),
    body          TEXT NOT NULL,
    truncated     INTEGER NOT NULL CHECK (truncated IN (0, 1)),
    marked        INTEGER NOT NULL CHECK (marked IN (0, 1)),
    created_at    TEXT NOT NULL,
    edited_at     TEXT,
    deleted_at    TEXT,
    seq           INTEGER NOT NULL,
    observed_at   TEXT NOT NULL
);

CREATE INDEX observed_artifact_comments_thread ON observed_artifact_comments(thread_id);

-- Files the operator attaches to a ticket or a task (DESIGN §22): text someone sent them, such as a design doc, for
-- the subject's runs to read as data. Only the operator's channels write a row, refused inside a tick or any run. The
-- text is kept beside the journal, `<state_dir>/attachments/<subject_kind>.<subject_id>/<id>.txt`, and `sha256` and
-- `size` are of it as written. `name` is what runs see it as, unique among the subject's attachments not removed. A
-- removed attachment keeps its row, with when and through which channel, and its file is deleted.
CREATE TABLE attachments (
    id               INTEGER PRIMARY KEY,
    subject_kind     TEXT NOT NULL CHECK (subject_kind IN ('ticket', 'task')),
    subject_id       TEXT NOT NULL,
    name             TEXT NOT NULL,
    size             INTEGER NOT NULL CHECK (size > 0),
    sha256           TEXT NOT NULL,
    channel          TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    added_at         TEXT NOT NULL,
    removed_at       TEXT,
    removed_channel  TEXT CHECK (removed_channel IN ('cli', 'web')),
    CHECK ((removed_at IS NULL) = (removed_channel IS NULL))
);

CREATE UNIQUE INDEX attachments_name ON attachments(subject_kind, subject_id, name) WHERE removed_at IS NULL;

-- What a resumed worker answered of each review finding it was handed (DESIGN §21, Answers and rebuttals): `fixed`,
-- or `declined` with its reason, in its own words, by the finding's number in its review run. The next review of the
-- PR reads them as data. A worker answers only findings of its own ticket's reviews; the harness checks that.
CREATE TABLE review_answers (
    run_id         INTEGER NOT NULL REFERENCES runs(id),
    review_run_id  INTEGER NOT NULL REFERENCES review_runs(id),
    finding        INTEGER NOT NULL CHECK (finding > 0),
    answer         TEXT NOT NULL CHECK (answer IN ('fixed', 'declined')),
    reason         TEXT,
    CHECK (answer != 'declined' OR reason IS NOT NULL),
    PRIMARY KEY (run_id, review_run_id, finding)
);

-- The model that wrote each reply of a run more than one model served (DESIGN §13, Each agent's model), read from the
-- runtime's record of the run's session with `run_models`, so its transcript names the model of each call. A reply is
-- the runtime's `message`, which each event of the call that wrote it names in the run's log; `model` is named as
-- `run_models.model` names it. None for a run one model served, which `run_models` names.
CREATE TABLE run_reply_models (
    run_table  TEXT NOT NULL CHECK (
        run_table IN ('ticks', 'runs', 'chore_runs', 'review_runs', 'task_runs', 'epic_runs')
    ),
    run_id     INTEGER NOT NULL,
    message    TEXT NOT NULL,
    model      TEXT NOT NULL,
    PRIMARY KEY (run_table, run_id, message)
) WITHOUT ROWID;

-- Each PR's head commit as canopy last saw it, and since when (`review.settle_minutes`, DESIGN §21, Settling). A review
-- of that commit waits until it has been the head for the settle time. A push, or a force push back to an earlier
-- commit, replaces the row and starts the wait over, so a commit pushed over soon after is never reviewed. Written by
-- `canopy review run` in a live tick only. Keyed by the PR's URL, as `review_runs.pr_url` is.
CREATE TABLE review_heads (
    pr_url     TEXT PRIMARY KEY,
    sha        TEXT NOT NULL,
    seen_at    TEXT NOT NULL
);

-- Each completed check run a `vcs` source has observed, by its run id, kept across later reads of its PR (DESIGN
-- §35). A read replaces `observed_checks` with the newest run of each context, so a re-run at the same head would
-- leave no trace of the run it repeats; this keeps it, so a `resume` for CI alone is refused `handled` when every
-- failure repeats, at the same head and context, one behind the unit's `ci` cursor. A commit status has no run and is
-- not kept.
CREATE TABLE observed_check_runs (
    pr_url       TEXT NOT NULL,
    run_id       INTEGER NOT NULL,
    name         TEXT NOT NULL,
    head_sha     TEXT NOT NULL,
    conclusion   TEXT NOT NULL CHECK (
        conclusion IN (
            'success', 'failure', 'error', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required',
            'startup_failure', 'stale'
        )
    ),
    observed_at  TEXT NOT NULL,
    number       INTEGER,
    PRIMARY KEY (pr_url, run_id)
);

-- A review finding the harness holds for the operator: it starts no `resume` and reaches no worker until the operator
-- sends it, which releases it, or dismisses it. `rebuttal` is a later review's answer to a finding the worker declined,
-- named by that earlier review run and finding. `late` is a later review's finding on a line unchanged since the PR's
-- first reviewed commit, which names no earlier finding (DESIGN §21, Answers and rebuttals).
CREATE TABLE review_holds (
    review_run_id     INTEGER NOT NULL REFERENCES review_runs(id),
    finding           INTEGER NOT NULL CHECK (finding > 0),
    kind              TEXT NOT NULL CHECK (kind IN ('rebuttal', 'late')),
    rebuts_run_id     INTEGER REFERENCES review_runs(id),
    rebuts_finding    INTEGER CHECK (rebuts_finding > 0),
    held_at           TEXT NOT NULL,
    released_at       TEXT,
    released_channel  TEXT CHECK (released_channel IN ('cli', 'web')),
    CHECK (kind != 'rebuttal' OR (rebuts_run_id IS NOT NULL AND rebuts_finding IS NOT NULL)),
    CHECK (kind != 'late' OR (rebuts_run_id IS NULL AND rebuts_finding IS NULL)),
    CHECK ((released_at IS NULL) = (released_channel IS NULL)),
    PRIMARY KEY (review_run_id, finding)
);

-- Every session the agent runtime keeps (DESIGN §13, Every session's spend), canopy's runs' and the operator's own
-- alike, read from the runtime's own record while `canopy loop` waits between ticks, so that the journal tells spend in
-- canopy from spend outside it. A session is read again each time the runtime updates it, its row replaced.

-- Each session as the runtime last recorded it: the session it ran for as a subagent, where it ran, when it started and
-- was last updated, what its replies cost in US dollars as the runtime priced them, and their tokens by kind.
-- `updated_ms` is the runtime's own stamp of the update, in milliseconds, which the reading's cursor names.
CREATE TABLE runtime_sessions (
    session_id          TEXT PRIMARY KEY,
    parent_id           TEXT,
    directory           TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    updated_ms          INTEGER NOT NULL,
    cost_usd            REAL NOT NULL,
    tokens_input        INTEGER NOT NULL,
    tokens_output       INTEGER NOT NULL,
    tokens_reasoning    INTEGER NOT NULL,
    tokens_cache_read   INTEGER NOT NULL,
    tokens_cache_write  INTEGER NOT NULL,
    read_at             TEXT NOT NULL
) WITHOUT ROWID;

CREATE INDEX runtime_sessions_started ON runtime_sessions (started_at);

CREATE INDEX runtime_sessions_parent ON runtime_sessions (parent_id);

-- Each model a session's replies name: how many it wrote, and what they cost. None for a session that made no call.
CREATE TABLE runtime_session_models (
    session_id          TEXT NOT NULL REFERENCES runtime_sessions (session_id) ON DELETE CASCADE,
    model               TEXT NOT NULL,
    replies             INTEGER NOT NULL,
    cost_usd            REAL NOT NULL,
    PRIMARY KEY (session_id, model)
) WITHOUT ROWID;

-- How reading the runtime's record stands, in one row: where the next read starts, after the last session read, and
-- how the last read ended, `found`, `missing` (the runtime has kept no session yet), or `failed`, with canopy's words
-- for why. `skipped` counts the sessions every read so far passed over as ones canopy cannot read.
CREATE TABLE runtime_session_reads (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    cursor_updated_ms   INTEGER,
    cursor_session_id   TEXT,
    status              TEXT NOT NULL CHECK (status IN ('found', 'missing', 'failed')),
    error               TEXT,
    skipped             INTEGER NOT NULL,
    read_at             TEXT NOT NULL,
    CHECK ((status = 'failed') = (error IS NOT NULL)),
    CHECK ((cursor_updated_ms IS NULL) = (cursor_session_id IS NULL))
);

-- Journal numbers (DESIGN §35, ROADMAP M37), which the cursors are. Each comment, review, review comment, and completed
-- check run takes the next number when a source first observes it, and keeps it across later reads of its subject,
-- which replace the observation's row but not its number; a canopy review run takes one when it ends. "Newer than a
-- cursor" then means first observed after it, one order for every kind, so the `review` cursor needs no time form.

-- Each item ever numbered, by what it is, its subject (a ticket's key for a comment, a PR's URL for the rest), and the
-- source's id for it (canopy's own for a review run). AUTOINCREMENT keeps numbers rising, so none is ever given twice.
CREATE TABLE item_numbers (
    number       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL CHECK (kind IN ('comment', 'review', 'review_comment', 'check_run', 'review_run')),
    subject      TEXT NOT NULL,
    id           TEXT NOT NULL,
    numbered_at  TEXT NOT NULL,
    UNIQUE (subject, kind, id)
);

-- The runs the overseer asks for, recorded, not spawned (DESIGN §40, ROADMAP M40): a dispatch, a review, a revision of
-- a review's draft, or a chore's run, its guards checked at the ask. The tick spawns each once the overseer's run has
-- ended, under its guards again; until then it counts as running in every guard's count. One the tick did not spawn is
-- closed `unstarted` as the tick closes, or by the next tick when this one died, and counts toward no limit.
CREATE TABLE recorded_runs (
    id           INTEGER PRIMARY KEY,
    tick_id      INTEGER NOT NULL REFERENCES ticks(id),
    kind         TEXT NOT NULL CHECK (kind IN ('dispatch', 'review', 'revision', 'chore')),
    -- The verb's request as the overseer made it, JSON, which the spawn makes again.
    request      TEXT NOT NULL,
    -- What it holds while it waits: its ticket (a dispatch's, or a review's of one of the loop's own PRs), a review's
    -- or a revision's PR and persona, and a chore's name.
    ticket_key   TEXT,
    pr_url       TEXT,
    persona      TEXT,
    chore        TEXT,
    status       TEXT NOT NULL DEFAULT 'recorded' CHECK (status IN ('recorded', 'started', 'refused', 'unstarted')),
    -- The run it started as, in its kind's table: `runs`, `review_runs`, or `chore_runs`.
    run_id       INTEGER,
    recorded_at  TEXT NOT NULL,
    closed_at    TEXT
);

-- The pushes canopy made to rerun a PR's checks a worker judged flaky (DESIGN §23): its branch rebased onto its base
-- and pushed with a lease, under `trust.max_flaky_kicks`. Each kick's head is the next one's `from_head`, so the
-- chain back from a branch's head counts the kicks spent on it since a push of work, which starts a new chain.
CREATE TABLE flaky_kicks (
    run_id     INTEGER NOT NULL REFERENCES runs(id),
    repo       TEXT NOT NULL,
    branch     TEXT NOT NULL,
    -- The commit origin's branch held before the kick, and the rebased commit the kick pushed in its place.
    from_head  TEXT NOT NULL,
    to_head    TEXT NOT NULL,
    kicked_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, repo)
);

CREATE INDEX flaky_kicks_by_branch ON flaky_kicks (repo, branch);

-- What a worker run answered of each item of its repositories' checklists (DESIGN §42): `pass`, `fixed`, `held` with
-- its reason, or `n/a`, the worker's word, untrusted; and `unanswered`, the harness's, for an item the run was given
-- and its result said nothing of. A row for every item of every list the run was given, and none for one it was not:
-- an answer to an item or a repository the run's lists do not hold is dropped. Counted per repository and item, so an
-- item earns its place or is dropped. A one-off task's run answers its repository's checklist too (DESIGN §36): each
-- row names the run in `run_id` or the task run in `task_run_id`, never both, so `canopy checklist` counts them
-- together. A row's rowid is its item's place in its list.
CREATE TABLE checklist_answers (
    run_id       INTEGER REFERENCES runs(id),
    repo         TEXT NOT NULL,
    item         TEXT NOT NULL,
    answer       TEXT NOT NULL CHECK (answer IN ('pass', 'fixed', 'held', 'n/a', 'unanswered')),
    reason       TEXT,
    task_run_id  INTEGER REFERENCES task_runs(id),
    CHECK ((answer = 'held') = (reason IS NOT NULL)),
    CHECK ((run_id IS NULL) != (task_run_id IS NULL)),
    UNIQUE (run_id, repo, item),
    UNIQUE (task_run_id, repo, item)
);

-- A tick's runs of the overseer (DESIGN §40, ROADMAP M40): the subject each was given, how it ended, its session, the
-- model canopy asked for, and what it cost, as `ticks` keeps them for its one run. A tick makes one run today, given
-- the whole state block, its subject NULL; `ticks` still keeps that run's session, cost, and model, and the models that
-- served it are `run_models`' under the tick.
--
-- `status`: `running` until the run ends; `ok`, its done line printed and every duty done; `failed`, it did not start,
-- timed out, exited non-zero, or printed no done line, or its tick raised while it ran, `failure` saying why; `undone`,
-- it ended well and left a duty undone, `failure` naming them; `abandoned`, its tick's process died while it ran.
-- `failure` is NULL for any other status.
CREATE TABLE overseer_runs (
    id                        INTEGER PRIMARY KEY,
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    subject                   TEXT,
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'ok', 'failed', 'undone', 'abandoned')),
    failure                   TEXT,
    session_id                TEXT,
    model                     TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    tokens_peak_context       INTEGER,
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    tokens_first_cache_read   INTEGER
);

CREATE INDEX overseer_runs_tick ON overseer_runs(tick_id);

-- How long each ticket plan is (DESIGN §25), measured once from its file as its planner wrote it, so the Plans report
-- reads it here rather than reading every plan's file again. A cache: every row can be measured again from the plan's
-- original, which is never written again. `version` is the measuring model's (`plan_metrics.VERSION`); a row of an
-- older one is measured again, and until then not read. `problem` says why a plan could not be measured, its original
-- gone or not the file written, and its measurements are then NULL, so it is not tried again.
CREATE TABLE plan_metrics (
    plan_id      INTEGER PRIMARY KEY REFERENCES plans(id),
    version      INTEGER NOT NULL,
    measured_at  TEXT NOT NULL,
    problem      TEXT,
    words        INTEGER,
    lines        INTEGER,
    code_blocks  INTEGER,
    tables       INTEGER,
    diagrams     INTEGER,
    CHECK (
        (problem IS NULL AND words IS NOT NULL AND lines IS NOT NULL AND code_blocks IS NOT NULL AND tables IS NOT NULL
            AND diagrams IS NOT NULL)
        OR (problem IS NOT NULL AND coalesce(words, lines, code_blocks, tables, diagrams) IS NULL)
    )
);

-- Feedback on a unit's PR that its `review` cursor passed with no worker sent to it (DESIGN §7): which item, by
-- GitHub's id and its journal number (§35), the tick that passed it, and why. The overseer names each feedback item its
-- `ticket-set` passes; the harness names one on a resolved thread, `resolved`. A cursor never moves back, so an item is
-- passed once; one passed again, after a forget, keeps its newest reason. Kept when its PR is read again: the reader
-- rewrites `observed_reviews`, but what was decided of an item stays decided.
CREATE TABLE passed_reviews (
    pr_url      TEXT NOT NULL,
    item        TEXT NOT NULL CHECK (item IN ('review', 'comment')),
    id          INTEGER NOT NULL,
    number      INTEGER NOT NULL,
    ticket_key  TEXT NOT NULL REFERENCES tickets(key),
    repo        TEXT,
    tick_id     INTEGER NOT NULL REFERENCES ticks(id),
    reason      TEXT NOT NULL CHECK (
        reason IN (
            'optional', 'would_reset_approval', 'question', 'already_done', 'out_of_scope', 'operator_said', 'resolved'
        )
    ),
    decider     TEXT NOT NULL CHECK (decider IN ('overseer', 'harness')),
    passed_at   TEXT NOT NULL,
    PRIMARY KEY (pr_url, item, id),
    CHECK (decider = 'harness' OR reason <> 'resolved')
);

CREATE INDEX passed_reviews_ticket ON passed_reviews(ticket_key);

-- Each run of a commit status a `vcs` source has observed, kept across later reads of its PR (DESIGN §35), for the CI
-- page. A status has no run id, and a read replaces `observed_checks` with its newest state, so a run is told from
-- what canopy saw of its context at one head: one seen pending again, or done with another conclusion, is a new run.
-- `conclusion` is NULL while it runs; `observed_at` is when it was first seen in the state the row holds.
CREATE TABLE observed_status_runs (
    id           INTEGER PRIMARY KEY,
    pr_url       TEXT NOT NULL,
    name         TEXT NOT NULL,
    head_sha     TEXT NOT NULL,
    conclusion   TEXT CHECK (
        conclusion IN (
            'success', 'failure', 'error', 'neutral', 'cancelled', 'skipped', 'timed_out', 'action_required',
            'startup_failure', 'stale'
        )
    ),
    observed_at  TEXT NOT NULL
);

CREATE INDEX observed_status_runs_context ON observed_status_runs(pr_url, name, head_sha);

CREATE INDEX observed_status_runs_observed ON observed_status_runs(observed_at);

-- Epics (DESIGN §43): work spanning several tickets, the operator's own subject, `epic:N`. Only the operator's channels
-- write these rows, refused inside a tick or any run: the submission is what authorizes the epic's plan runs, and its
-- text their instruction. `project` is the tracker project its breakdown's tickets are filed in, NULL for none;
-- `tracker_epic` a tracker key whose children are put to the operator as suggestions, NULL for none.
CREATE TABLE epics (
    id            INTEGER PRIMARY KEY,
    text          TEXT NOT NULL,
    project       TEXT,
    tracker_epic  TEXT,
    channel       TEXT NOT NULL CHECK (channel IN ('cli', 'web')),
    submitted_at  TEXT NOT NULL
);

-- The repositories an epic's plan reads, by their names in the map, at least one each.
CREATE TABLE epic_repos (
    epic_id  INTEGER NOT NULL REFERENCES epics(id),
    repo     TEXT NOT NULL,
    PRIMARY KEY (epic_id, repo)
);

-- An epic's member tickets, as the operator added and removed them. A removal ends the row rather than deleting it,
-- so what was a member stays to read. A ticket is a member of at most one epic at a time. `ticket_key` names
-- no `tickets` row: a ticket may be a member before canopy has seen it, and membership authorizes no work on it.
CREATE TABLE epic_members (
    id               INTEGER PRIMARY KEY,
    epic_id          INTEGER NOT NULL REFERENCES epics(id),
    ticket_key       TEXT NOT NULL,
    added_at         TEXT NOT NULL,
    added_channel    TEXT NOT NULL CHECK (added_channel IN ('cli', 'web')),
    removed_at       TEXT,
    removed_channel  TEXT CHECK (removed_channel IN ('cli', 'web')),
    CHECK ((removed_at IS NULL) = (removed_channel IS NULL))
);

CREATE UNIQUE INDEX epic_members_current ON epic_members(ticket_key) WHERE removed_at IS NULL;

CREATE INDEX epic_members_of ON epic_members(epic_id, id);

-- An epic's plan runs (DESIGN §43): each started by a tick in code, before its overseer, in a desk of a slot per
-- repository the epic names, leased as `canopy:epic:<id>`. An epic has no ticket, so its runs are not
-- `runs` rows; its slots are `epic_run_slots` rows. `message_id` is the newest message about the epic its
-- prompt carried, so a reply after it asks for the next plan. A plan run pushes nothing, so it has no branch or head.
CREATE TABLE epic_runs (
    id                        INTEGER PRIMARY KEY,
    epic_id                   INTEGER NOT NULL REFERENCES epics(id),
    tick_id                   INTEGER NOT NULL REFERENCES ticks(id),
    desk_path                 TEXT NOT NULL,
    pid                       INTEGER,
    agent_pid                 INTEGER,
    started_at                TEXT NOT NULL,
    ended_at                  TEXT,
    status                    TEXT NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'done', 'blocked', 'failed', 'unknown', 'crashed', 'timeout', 'stopped')
    ),
    result_json               TEXT,
    log_path                  TEXT NOT NULL,
    session_id                TEXT,
    cost_usd                  REAL,
    tokens_input              INTEGER,
    tokens_output             INTEGER,
    tokens_reasoning          INTEGER,
    tokens_cache_read         INTEGER,
    tokens_cache_write        INTEGER,
    tokens_peak_context       INTEGER,
    tokens_first_call         INTEGER,
    tokens_first_cache_write  INTEGER,
    tokens_first_cache_read   INTEGER,
    definitions_digest        TEXT,
    message_id                INTEGER REFERENCES messages(id),
    model                     TEXT,
    tool_calls                INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX epic_runs_of ON epic_runs(epic_id, id);

CREATE INDEX epic_runs_running ON epic_runs(status) WHERE status = 'running';

-- The slots an epic's plan run leased, one per repository, each returned when the run ends or reconcile finds it
-- dead. `git_link` is what the slot's `.git` file held when the run started, as `run_slots.git_link`.
CREATE TABLE epic_run_slots (
    run_id        INTEGER NOT NULL REFERENCES epic_runs(id),
    repo          TEXT NOT NULL,
    slot_path     TEXT NOT NULL,
    lease_id      TEXT NOT NULL,
    lease_holder  TEXT NOT NULL,
    base_branch   TEXT NOT NULL,
    pool          TEXT NOT NULL CHECK (pool IN ('treehouse', 'canopy')),
    git_link      BLOB,
    PRIMARY KEY (run_id, repo)
);

-- An epic's plans (DESIGN §43), one per plan run that wrote one, as `plans` holds a ticket's (§25). A plan's text
-- is never here: it is the file `<state_dir>/epics/<epic_id>/<run_id>.md`, which the row is recorded after.
-- `sha256` and `size` are the file's as the planner wrote it; the approved hash is the file's when the operator
-- approved it, their edits included, and `approved_channel` how they did. Only the operator approves one. A new plan
-- supersedes the one before it, so an epic has at most one plan waiting or approved; an approved plan stays
-- readable once superseded, as what the next approval is compared with. Rows are never deleted.
CREATE TABLE epic_plans (
    id                INTEGER PRIMARY KEY,
    epic_id           INTEGER NOT NULL REFERENCES epics(id),
    run_id            INTEGER NOT NULL UNIQUE REFERENCES epic_runs(id),
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved', 'superseded')),
    sha256            TEXT NOT NULL,
    size              INTEGER NOT NULL,
    approved_sha256   TEXT,
    approved_at       TEXT,
    approved_channel  TEXT CHECK (approved_channel IN ('cli', 'web')),
    CHECK ((approved_sha256 IS NULL) = (approved_at IS NULL) AND (approved_at IS NULL) = (approved_channel IS NULL)),
    CHECK (status != 'approved' OR approved_at IS NOT NULL),
    CHECK (status != 'proposed' OR approved_at IS NULL)
);

CREATE UNIQUE INDEX epic_plans_current ON epic_plans(epic_id) WHERE status != 'superseded';

CREATE INDEX epic_plans_of ON epic_plans(epic_id, id);

-- The breakdown entries each member of an epic fulfils (DESIGN §43), as the operator registered them: one or
-- more `B<n>` of the plan approved when they did, or none, for a ticket the breakdown did not foresee. A registration
-- replaces the member's entries; the ids are data, never instructions, checked against the approved plan as written.
CREATE TABLE epic_member_entries (
    member_id  INTEGER NOT NULL REFERENCES epic_members(id),
    entry      TEXT NOT NULL CHECK (entry GLOB 'B[1-9]*'),
    PRIMARY KEY (member_id, entry)
);

INSERT INTO schema_migrations (version, name) VALUES (1, 'init');
