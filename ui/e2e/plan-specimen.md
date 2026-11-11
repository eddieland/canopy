# Retry exports that fail mid-read

## Context

A scheduled export runs as a job in **web**, which reads the report's rows from **api** a page at a time. When the
connection drops, the job fails whole and the owner gets nothing.

```mermaid
flowchart TD
    Menu[web: schedule menu] --> Form[web: schedule form]
    Form -->|saves| Table[(schedules table)]
    Cron[web: nightly cron] -->|enqueues| Queue[web: job queue]
    Queue --> Job[web: export_job]
    subgraph api
        Query[api: ReportQuery]
        Rows[api: iter_rows]
    end
    Job --> Query
    Query --> Rows
    Rows -->|a page| Job
    Job --> Writer[web: CSV writer]
    Writer --> Mail[web: mail to owner]
```

The same path, as the job reads it, left to right:

```mermaid
flowchart LR
    Menu[Schedule menu] --> Form[Schedule form] -->|saves| Table[(schedules table)]
    Cron[Nightly cron] -->|enqueues| Queue[Job queue] --> Job[export_job.run]
    Job --> Failed{Failed read?}
    Failed -->|no| Rows[api: ReportQuery.iter_rows] --> Writer[CSV writer] --> Mail[Mail to owner]
    Failed -->|yes, under limit| Wait[Wait with backoff] --> Job
    Failed -->|yes, at limit| Dead[Dead letter] --> Notify[Notify operator]
```

## Step 1: api and web: resume a read

```mermaid
sequenceDiagram
    participant Job as web: export_job
    participant Query as api: ReportQuery
    participant DB as postgres
    Job->>Query: iter_rows(report_id)
    loop each page, as it is read
        Query->>DB: SELECT a page
        DB-->>Query: rows
        Query-->>Job: a page of rows
    end
    alt the connection drops
        Query-->>Job: RetryableReadError(cursor)
        Note over Job: waits, then resumes from the cursor
        Job->>Query: iter_rows(report_id, resume_from=cursor)
    else the read ends
        Job->>Job: write CSV
    end
```

| Repository | File | Change | Signature | Test | Acceptance |
| --- | --- | --- | --- | --- | --- |
| api | `api/reports/query/iterators/paged_rows.py` | raise `RetryableReadError` when the connection drops mid-page, keeping the cursor so the caller resumes from the page that failed rather than the first | `iter_rows(report_id: int, *, resume_from: Cursor \| None = None) -> Iterator[Row]` | `test_paged_rows.py` | a dropped page resumes |
| web | `app/jobs/export_job.py` | catch it and wait | `run(schedule_id: int) -> ExportResult` | `test_export_job.py` | a job retries |
| web | `app/jobs/backoff.py` | new | `delay(attempt: int, base_s: float) -> float` | `test_backoff.py` | the waits double |

## Step 2: web: a status for the wait

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: worker picks it up
    running --> waiting: retryable error
    waiting --> running: backoff elapsed
    waiting --> dead: limit reached
    dead --> queued: operator requeues
    running --> done: CSV mailed
    running --> failed: other error
    done --> [*]
    failed --> [*]
```

```mermaid
flowchart LR
    Job[export_job] --> Backoff[backoff.delay] --> Job
```

| Attempt | Delay (s) | Cumulative (s) | Share of budget |
| ---: | ---: | ---: | ---: |
| 1 | 30 | 30 | 3% |
| 2 | 60 | 90 | 10% |
| 3 | 120 | 210 | 23% |
| 4 | 240 | 450 | 50% |

| Key | Default |
| --- | --- |
| `retry.limit` | `4` |
| `retry.base_s` | `30` |

```python
def delay(attempt: int, base_s: float) -> float:
    """The wait before `attempt`, doubling each time."""
    return base_s * 2 ** (attempt - 1)
```

## Tests

- [x] `delay` doubles
- [ ] the job stops at `retry.limit`
- [ ] a dead export notifies the operator

> A migration adds the `waiting` status. Roll back by deleting rows in it first.

---

## Risks

```mermaid
pie title Where exports fail
    "api read" : 70
    "mail" : 20
    "other" : 10
```

```mermaid
flowchart TD
    A[web --> B[api
    B -->
```
