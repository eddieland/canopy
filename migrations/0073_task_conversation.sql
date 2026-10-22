-- A one-off task's conversation (DESIGN §36): its runs' reports and questions, and the operator's replies, are
-- messages about the task, `subject_kind` 'task' and its id. A run's own messages name it here, as `run_id` names a
-- ticket's run; `run_id` references `runs`, which a task's run is not.
ALTER TABLE messages ADD COLUMN task_run_id INTEGER REFERENCES task_runs(id);

-- The newest message about its task when the run started: its prompt carries the conversation up to it, and a reply
-- of the operator's past it queues the task's next run. NULL when the task had none.
ALTER TABLE task_runs ADD COLUMN message_id INTEGER REFERENCES messages(id);

-- Every task run that ended before this migration gets the messages `_task` records now: a report, and for a `blocked`
-- run its question, in the order the runs ended, as migration 0003 gave tickets' runs theirs. A task's result names
-- its PRs as a list. An invalid result_json reads as none.
WITH ended AS (
    SELECT id, task_id, ended_at, status, CASE WHEN json_valid(result_json) THEN result_json END AS result
    FROM task_runs WHERE status != 'running' AND ended_at IS NOT NULL
)
INSERT INTO messages (subject_kind, subject_id, at, source, kind, channel, task_run_id, body)
SELECT 'task', CAST(task_id AS TEXT), at, 'worker', kind, 'run', id, body FROM (
    SELECT
        e.id, e.task_id, e.ended_at AS at, 0 AS seq, 'report' AS kind,
        coalesce(
            nullif(trim(json_extract(e.result, '$.summary')), ''),
            nullif(trim(json_extract(e.result, '$.harness')), ''),
            'ended ' || e.status
        ) || coalesce(
            char(10) || CASE WHEN json_type(e.result, '$.prs') = 'array' THEN (
                SELECT group_concat(p.value, char(10)) FROM json_each(e.result, '$.prs') AS p
                WHERE p.type = 'text' AND p.value != ''
            ) END,
            ''
        ) AS body
    FROM ended AS e
    UNION ALL
    SELECT e.id, e.task_id, e.ended_at, 1, 'question', trim(json_extract(e.result, '$.question'))
    FROM ended AS e
    WHERE e.status = 'blocked' AND json_type(e.result, '$.question') = 'text'
        AND trim(json_extract(e.result, '$.question')) != ''
)
ORDER BY at, id, seq;
