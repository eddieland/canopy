// Names for the generated API types. Import from here, not from schema.gen.ts, so call sites read as the domain.
import type { components } from './schema.gen'

type Schemas = components['schemas']

/** The server itself: what it runs and whether its data is real. */
export type Meta = Schemas['Meta']
/** Whether this browser is signed in, and if so the token its writes must carry. */
export type Session = Schemas['Session']
/** One item on the attention list (DESIGN §14): what needs the operator, and since when. */
export type AttentionItem = Schemas['AttentionItem']
/** One worker or split run (`run:ID`). */
export type Run = Schemas['Run']
/** A run's status in the five groups the UI colors (DESIGN §22): `failed` is every ending a human must look at. */
export type RunState = Schemas['RunState']
/** A ticket as the tickets list shows it. */
export type TicketSummary = Schemas['TicketSummary']
/** One ticket: what `canopy show` prints, and the latest decisions about it. */
export type TicketDetail = Schemas['TicketDetail']
/** One message in a ticket's conversation. */
export type Message = Schemas['Message']
/** A ticket's work in one repository: its PR and phase (DESIGN §18). */
export type Unit = Schemas['Unit']
/** A guard refused the operator's action: which guard, and why, as the CLI says it. */
export type Refusal = Schemas['Refusal']
/** What a start did: whether it was already started, and a run already working it. */
export type Started = Schemas['Started']
/** What a stop did: whether it was already stopped, the run still working it, and whether `now` ended it. */
export type Stopped = Schemas['Stopped']
/** What a reply recorded: the message, the message it answers, and whether it was new. */
export type Replied = Schemas['Replied']
/** What a forget cleared: the ticket's branch and its units' PRs, which are the operator's to close and delete. */
export type Forgot = Schemas['Forgot']
/** One message on the event stream, told apart by its `type` (`applyStreamEvent` in live.ts). */
export type StreamEvent = Schemas['StreamEvent']
/** One repository's treehouse pool, read when asked for. */
export type Pool = Schemas['Pool']
/** What the last day and the last 30 days cost, read together, so a month never shows less than its day. */
export type Spend = Schemas['Spend']
/** What the agent runtime reported spending in the last `hours` hours (DESIGN §13). */
export type SpendWindow = Schemas['SpendWindow']
/** A tick, as `canopy status`'s first line shows the latest (DESIGN §14), with how many decisions it recorded. */
export type Tick = Schemas['Tick']
/** The latest tick, or none before the first, and the newest message a tick has acknowledged. */
export type LastTick = Schemas['LastTick']
/** Whether the operator paused the loop: no tick starts until it is resumed. */
export type LoopState = Schemas['LoopState']
/** The operator paused the loop (DESIGN §6): since when, and through which channel. */
export type Pause = Schemas['Pause']
/** What a pause or a resume did: whether the loop was already so, and the state it left. */
export type PauseChanged = Schemas['PauseChanged']
/** What asking the loop to read its config again found: the keys that change, and whether a tick must end first. */
export type ConfigReload = Schemas['ConfigReload']
/** One tick: what `canopy decisions ID` prints. */
export type TickDetail = Schemas['TickDetail']
/** One decision a tick recorded (DESIGN §6): the overseer's, or the harness's attention items and refusals. */
export type Decision = Schemas['Decision']
/** One slot of a treehouse pool, as `treehouse status --json` reports it, with what in the journal holds it. */
export type Worktree = Schemas['Worktree']
/** A worktree's state in the five groups the UI colors (DESIGN §22). */
export type WorktreeState = Schemas['WorktreeState']
/** A configured chore as `canopy status` lists it: its window, its runs, when it is next due, its findings. */
export type ChoreSummary = Schemas['ChoreSummary']
/** One chore: what `canopy show chore:NAME` prints. */
export type ChoreDetail = Schemas['ChoreDetail']
/** One run of a chore (DESIGN §19). */
export type ChoreRun = Schemas['ChoreRun']
/** An open finding: one the chore's latest `ok` run reported (DESIGN §19). */
export type ChoreFinding = Schemas['ChoreFinding']
/** What a run's log or a tick's output holds of its session, read back from its events (DESIGN §22). */
export type Transcript = Schemas['Transcript']
/** One entry of a transcript, told apart by its `kind`: text, a tool call, a model call's end, or an error. */
export type TranscriptEntry = Transcript['entries'][number]
/** One tool call, once it ended: its input as indented JSON, and its output, or its error. */
export type TranscriptTool = Schemas['TranscriptTool']
/** A search: the words it looked for, its hits by source and newest first, and the sources that had more. */
export type SearchResults = Schemas['SearchResults']
/** One row holding every word of a search, and where it opens. */
export type SearchHit = Schemas['SearchHit']
/** Where a search hit is (DESIGN §22, Search), in the order the search reads them. */
export type SearchSource = Schemas['SearchSource']

/** Every run state, in display order. `satisfies` fails the typecheck if the schema gains a state these miss. */
export const RUN_STATES = ['running', 'blocked', 'failed', 'stopped', 'done'] as const satisfies readonly RunState[]

/** Every worktree state, in display order. */
export const WORKTREE_STATES = [
    'working',
    'held',
    'dirty',
    'idle',
    'broken',
] as const satisfies readonly WorktreeState[]
