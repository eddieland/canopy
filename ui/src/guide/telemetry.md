# Telemetry

canopy can record what it does as OpenTelemetry traces and metrics, for a collector you run to send on to whatever
already holds yours. It's off until you turn it on, and it holds canopy's own facts, never what canopy read. This page
covers what each signal holds, the two ways out, the collector, dashboard, and alerts canopy ships, and every name, for
when you write queries of your own.

## What each signal holds

**Traces** say what happened and how long it took. Each tick is a trace, with a span for each of its steps (`gc`,
`reconcile`, `state`, `overseer`, `spawn`, and the rest), each command canopy ran under the step that ran it, and each
of the overseer's tool calls under its run. Each run a tick starts is a trace of its own, linked to the `spawn` step
that started it, with a span for each model call and each tool call its agent made, at the times the runtime printed
them. Each request the web UI's server answers is a trace too, and a journal query slower than 50 ms is a span of its
own. A decision recorded, a lease taken or returned, and a process killed are events on the span they happened in.

**Metrics** say how much and how often: runs that ended, by role and status; what they cost and the tokens they spent,
by model; how long ticks, their steps, and runs took; decisions, made or refused; deliveries to your notification
sinks; connector runs. As each tick closes it also sets what the loop holds: when a tick last closed, the open tickets
by phase, the runs at work against each role's capacity, the attention list's length, and the disk free.

**Neither holds what canopy read.** No ticket key, title, or comment, no prompt, no PR, no model output, no tool's
input or output, no path, no overseer's rationale. An attribute or label is an id, a count, a time, a cost, or one of
canopy's own words: a status, a kind, a step, a role, and the models you configured. A span that failed names its
exception's type, never its message, since a message can quote whatever the code was reading when it went wrong. So
telemetry can go to a backend you'd never paste a ticket into, which is rather the point.

Everything both send names canopy (`service.name`), its version (`service.version`), and the workspace, by a random id
kept in `.canopy/instance-id` (`service.instance.id`) rather than its path, so one backend tells your workspaces and
machines apart. Attributes of your own go beside them, from `[telemetry.resource]`.

**There are no logs.** `canopy.log` is the one place canopy writes text it read, an error's message among it, so canopy
never sends it anywhere. Your collector can read it as a file, as the example below does, and then where it goes is
your choice rather than canopy's.

## Turning it on

```toml
[telemetry]
traces = "file"     # or "otlp"
metrics = "file"    # or "otlp"
# endpoint = "http://127.0.0.1:4318"   # for "otlp"
```

Every `telemetry` key is yours alone, so it goes in `.canopy/config.toml` or `~/.config/canopy/config.toml`, never the
workspace file: what leaves your machine, and where to, is not a choice a commit gets to make for you. Each canopy
process reads it as it opens the workspace; restart `canopy loop` for the loop's own.

## The two ways out

**`file`** appends to `.canopy/traces.jsonl` and `.canopy/metrics.jsonl`, readable by you alone: a line of OTLP JSON
per export, which is what a collector's `otlp_json_file` receiver reads. A span is written as it ends, and metrics every
30 seconds and as each process exits, so a run that dies early loses little. Nothing leaves the machine, and a live
tick rotates both files as it rotates `canopy.log`, past `retention.log_max_mib`.

**`otlp`** posts the same to the OTLP/HTTP endpoint you name: spans to `/v1/traces` under it, metrics to
`/v1/metrics`, as JSON. It's the one network call canopy itself makes, through no proxy and following no redirect, so
they reach that endpoint or nothing does. An export the endpoint refuses is dropped, never sent again, so a collector
that's down costs you spans, never a step. `canopy status` ends with a Telemetry section saying where each signal goes
and whether its last export was taken, and the metrics count each signal's exports, taken or not, on the next one
that is ([Running the loop](running-the-loop#checking-on-it)).

Use `file` when the collector runs on the same machine as you, and `otlp` when it doesn't, or you'd rather canopy
didn't keep the files. Either way it's the same data.

**Counts are deltas.** canopy is many short processes, the loop's, each run's, each command's you type, and each
sends what it counted since its last export rather than a running total. A collector has to add them up before
anything that wants totals, Prometheus above all: that's the `delta_to_cumulative` processor, and the example has it.
Skip it and every counter looks like a seismograph.

## The example collector

canopy's repository ships a working setup in
[examples/otel](https://github.com/eddieland/canopy/tree/main/examples/otel): a collector config, a Prometheus config
with alert rules, and a Grafana dashboard. To use it with `traces = "file"` and `metrics = "file"`:

1. Install the OpenTelemetry Collector's contrib distribution, `otelcol-contrib`, v0.158 or later.
2. Run it as yourself, pointing it at the workspace's state directory:
   `CANOPY_STATE_DIR=/path/to/workspace/.canopy otelcol-contrib --config examples/otel/collector.yaml`.
3. Run Prometheus with `examples/otel/prometheus.yaml`, or add its scrape job and `alerts.yaml` to the one you run.
4. Import `examples/otel/dashboard.json` into Grafana and pick that Prometheus as its data source.

It reads both files and `canopy.log`, takes what canopy posts to `http://127.0.0.1:4318` with `otlp`, adds the deltas
up, serves metrics at `http://127.0.0.1:8889/metrics`, and sends traces to an OTLP/gRPC backend such as Tempo or Jaeger
at `127.0.0.1:4317` and logs to Loki's OTLP endpoint; `CANOPY_TRACES_TO` and `CANOPY_LOGS_TO` move them. Without a log
backend, remove its `logs` pipeline. In Prometheus, the collector names each series' `job` canopy and its `instance`
the workspace's id.

```yaml examples/otel/collector.yaml
```

## The dashboard and the alerts

The dashboard opens on how long ago a tick last closed, the runs at work, what's waiting on you, the spend over the
range, the disk free, and exports lost, then charts runs by status and role, cost and tokens by model, how long ticks
and their steps take, ticks by status, tickets by phase, and decisions. Its `Filter` narrows every panel by a label,
such as one workspace's `instance`.

`alerts.yaml` holds four rules, each per workspace:

- **CanopyLoopStalled**: no tick has closed in three hours. A quiet loop ticks every two hours at most
  (`loop.idle_max_minutes`), so this means it's stopped, paused, or stuck. Raise it if you raised that.
- **CanopyRunsFailing**: half the last six hours' runs ended without doing their work, out of four or more.
- **CanopyTicksFailing**: half the last six hours' ticks didn't close `ok`, out of four or more.
- **CanopySpendHigh**: runs cost more than 5 USD in the last hour. The 5 is a placeholder for a number you'd actually
  want to be woken for.

## Names in Prometheus

The collector's Prometheus exporter turns each metric's name into Prometheus's: each dot becomes an underscore, then
its unit is added (`s` as `_seconds`, `By` as `_bytes`, `USD` as it is, and `{token}` not at all), then `_total` to a
counter and `_ratio` to a gauge whose unit is `1`. The last is the exporter's guess that a unitless gauge is a ratio;
canopy's are counts of things, so read `canopy_tickets_ratio` as "tickets". A histogram is three series, its name
with `_bucket`, `_sum`, and `_count`. The tables below give each metric's name in Prometheus, and a test holds them,
the dashboard, and the alerts to what canopy records.

## Every metric

Each counter and histogram is sent as deltas; each gauge as what it is now. A label is the word of one of canopy's
vocabularies, `true` or `false` for `dry_run`, or for `model` the model your config chose; `kind` on `canopy.runs` is
only a worker's.

| Metric | Kind | Unit | Labels | In Prometheus | What it counts |
|---|---|---|---|---|---|
| `canopy.ticks` | counter | `1` | `status`, `dry_run` | `canopy_ticks_total` | ticks that closed |
| `canopy.tick.duration` | histogram | `s` | `status` | `canopy_tick_duration_seconds` | how long a tick took |
| `canopy.tick.step.duration` | histogram | `s` | `step` | `canopy_tick_step_duration_seconds` | how long each step of a tick took |
| `canopy.decisions` | counter | `1` | `kind`, `outcome`, `decider`, `dry_run` | `canopy_decisions_total` | decisions recorded, made or refused |
| `canopy.notifications` | counter | `1` | `status` | `canopy_notifications_total` | deliveries to notification sinks |
| `canopy.connector.runs` | counter | `1` | `kind`, `status` | `canopy_connector_runs_total` | runs of the connectors |
| `canopy.runs` | counter | `1` | `role`, `status`, `kind` | `canopy_runs_total` | agent runs that ended |
| `canopy.run.duration` | histogram | `s` | `role`, `status` | `canopy_run_duration_seconds` | how long an agent run ran |
| `canopy.cost` | counter | `USD` | `role`, `model` | `canopy_cost_USD_total` | what runs cost, as the runtime reported |
| `canopy.tokens` | counter | `{token}` | `role`, `model`, `type` | `canopy_tokens_total` | the tokens runs spent |
| `canopy.runs.active` | gauge | `1` | `role` | `canopy_runs_active_ratio` | runs at work as a tick closed |
| `canopy.tick.last` | gauge | `s` | `status` | `canopy_tick_last_seconds` | when the last tick of each status closed, in Unix time |
| `canopy.tickets` | gauge | `1` | `phase` | `canopy_tickets_ratio` | open tickets, by phase |
| `canopy.capacity.used` | gauge | `1` | `role` | `canopy_capacity_used_ratio` | runs filling each role's capacity |
| `canopy.capacity.limit` | gauge | `1` | `role` | `canopy_capacity_limit_ratio` | each role's capacity, from config |
| `canopy.attention.open` | gauge | `1` | | `canopy_attention_open_ratio` | items on the attention list |
| `canopy.disk.free` | gauge | `By` | | `canopy_disk_free_bytes` | bytes free on the state directory's disk |
| `canopy.telemetry.exports` | counter | `1` | `signal`, `outcome` | `canopy_telemetry_exports_total` | telemetry's own exports, sent or failed |
| `canopy.telemetry.spans.dropped` | counter | `1` | | `canopy_telemetry_spans_dropped_total` | spans dropped before any export |

## Every span

A span's own attributes are named `canopy.` and a word; those OpenTelemetry's conventions name keep their names. Any
span may also carry `canopy.journal_queries` and `canopy.journal_seconds`: the journal queries run under it, its
children's included, and how long they took.

| Span | What it is | Attributes |
|---|---|---|
| `tick` | a tick, a trace of its own | `canopy.tick_id`, `canopy.dry_run`, `canopy.status`, `canopy.cost_usd`, `canopy.new_tokens` |
| `gc`, `reconcile`, `connectors`, `derive`, `spawn`, `upkeep` | a step of a tick | |
| `tasks`, `epics` | the steps that start your tasks' and epics' runs | `canopy.started` |
| `state` | the step that builds the overseer's state | `canopy.left` |
| `overseer` | the step that runs the overseer | `canopy.failed`, `canopy.cost_usd`, `canopy.new_tokens` |
| `run`, `task`, `epic`, `chore`, `review` | an agent run, a trace of its own, linked to what started it | `canopy.run_id`, `canopy.task_run_id`, `canopy.epic_run_id`, `canopy.chore_run_id`, `canopy.review_run_id`, `canopy.role`, `canopy.kind`, `canopy.attempt`, `canopy.model`, `canopy.sandboxed`, `canopy.status` |
| `<program>`, `<program> <subcommand>` | a command canopy ran and waited for, such as `git fetch` | `process.executable.name`, `process.exit.code`, `canopy.subcommand`, `canopy.timed_out` |
| `tools/call <tool>` | one of the overseer's tool calls, in canopy's MCP server | `gen_ai.operation.name`, `gen_ai.tool.name` |
| `chat`, `chat <model>` | a model call in a run | `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.usage.cache_creation.input_tokens`, `canopy.reasoning_tokens`, `canopy.cost_usd` |
| `execute_tool <tool>` | a tool call in a run | `gen_ai.operation.name`, `gen_ai.tool.name` |
| `<operation>` | a journal query slower than 50 ms, named for its first word, such as `SELECT` | `db.system.name`, `db.operation.name`, `db.query.text` |
| `<method>`, `<method> <route>` | a request the web UI's server answered, a trace of its own | `http.request.method`, `http.route`, `http.response.status_code` |

A slow query's `db.query.text` is canopy's own SQL, with a `?` for each value, never a value.

## Every event

| Event | When | Attributes |
|---|---|---|
| `decision` | a decision was recorded, on the span that recorded it | `canopy.decision_id`, `canopy.kind`, `canopy.outcome`, `canopy.guard`, `canopy.decider`, `canopy.run_kind` |
| `lease.taken` | a run took a worktree from a pool | `canopy.pool` |
| `lease.return` | a worktree went back to its pool | `canopy.pool`, `canopy.outcome` |
| `process.killed` | canopy killed a process group, its timeout's doing or not | `canopy.timed_out` |
