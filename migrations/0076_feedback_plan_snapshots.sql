-- What each feedback plan saw (DESIGN §32, Planning again): from the read its run made of its PRs before the planner
-- started, each PR's head, each check's conclusion at that head, and each item and reply it was given, by id with a
-- SHA-256 of its body, never its text. The observations (0043, 0052) are replaced whole on every read of a PR, so this
-- is what says what changed on a PR since its plan was written. Kept with their plan; rows are never deleted.

-- Each PR a plan read, and its head then.
CREATE TABLE feedback_plan_prs (
    plan_id   INTEGER NOT NULL REFERENCES feedback_plans(id),
    pr_url    TEXT NOT NULL,
    head_sha  TEXT,
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

-- The SHA-256 of what changed that an approval of a stale plan was last refused for (`stale`): approving again, with
-- nothing more changed, approves it.
ALTER TABLE feedback_plans ADD COLUMN stale_shown TEXT;
