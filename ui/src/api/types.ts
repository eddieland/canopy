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
/** A running run's latest tool call, as `_run` read it from the worker's events (DESIGN §8). */
export type RunActivity = Schemas['RunActivity']
/** A run's status in the five groups the UI colors (DESIGN §22): `failed` is every ending a human must look at. */
export type RunState = Schemas['RunState']
/** A ticket as the tickets list shows it. */
export type TicketSummary = Schemas['TicketSummary']
/** One ticket: what `canopy show` prints, and the latest decisions about it. */
export type TicketDetail = Schemas['TicketDetail']
/** What a ticket's or a PR's agent runs cost in all (DESIGN §13), and how many runs and reviews that counts. */
export type CostTotal = Schemas['CostTotal']
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
/** A limit `canopy grant` raises: a ticket's unit's runs of one kind, or a PR's review runs (DESIGN §22). */
export type Limit = Schemas['Limit']
/** What a grant recorded: one more run allowed, every earlier one still counted. The next tick decides. */
export type Granted = Schemas['Granted']
/** The operator's request to review a PR the loop does not own (DESIGN §21): open, or how it ended. */
export type ReviewRequest = Schemas['ReviewRequest']
/** What a review request recorded: the open request, and whether it was already open or replaced another. */
export type ReviewRequested = Schemas['ReviewRequested']
/** What stopping a review request did: the request as it was, and a review of the PR still running. */
export type ReviewRequestStopped = Schemas['ReviewRequestStopped']
/** What a dismissal left: the chore's finding, and whether it is now dismissed. */
export type Dismissed = Schemas['Dismissed']
/** What a dismissal of a review's finding left: the run, the finding's number, and whether it is now dismissed. */
export type ReviewDismissed = Schemas['ReviewDismissed']
/** What sending a review's findings recorded: the operator message on the review's ticket that names them. */
export type ReviewSent = Schemas['ReviewSent']
/** One message on the event stream, told apart by its `type` (`applyStreamEvent` in live.ts). */
export type StreamEvent = Schemas['StreamEvent']
/** One repository's treehouse pool, read when asked for. */
export type Pool = Schemas['Pool']
/** What the last day and the last 30 days cost, read together, so a month never shows less than its day. */
export type Spend = Schemas['Spend']
/** What the agent runtime reported spending in the last `hours` hours (DESIGN §13). */
export type SpendWindow = Schemas['SpendWindow']
/** What a window of whole UTC days cost, by day, by kind, and by what its ticks bought, as `canopy spend` prints. */
export type SpendBreakdown = Schemas['SpendBreakdown']
/** What each kind of agent run cost: the overseer (idle ticks' part of it too), dry runs, workers, chores, reviews. */
export type SpendCosts = Schemas['SpendCosts']
/** One UTC day's costs. */
export type SpendDay = Schemas['SpendDay']
/** What a group of ticks bought (DESIGN §6, Idle pacing): idle, busy, hand-run, not ok, or a dry run. */
export type SpendGroup = Schemas['SpendGroup']
/** What one ticket's own runs in a spend window cost, and whether the loop marked it done in that window. */
export type SpendTicket = Schemas['SpendTicket']
/** What the runs that pushed to one PR, and the reviews of it, in a spend window cost. */
export type SpendPullRequest = Schemas['SpendPullRequest']
/** What one tool's calls in one kind's runs in a spend window returned: the calls, errors, and characters. */
export type SpendTool = Schemas['SpendTool']
/** A tick, as `canopy status`'s first line shows the latest (DESIGN §14), with how many decisions it recorded. */
export type Tick = Schemas['Tick']
/** The latest tick, or none before the first, and the newest message a tick has acknowledged. */
export type LastTick = Schemas['LastTick']
/** Whether the operator paused the loop (no tick starts until it is resumed), and the notice to workers in force. */
export type LoopState = Schemas['LoopState']
/** The operator's notice to workers in force (DESIGN §8): what it says, when it was set, and when it lapses. */
export type WorkerNotice = Schemas['WorkerNotice']
/** What setting or clearing a notice did, and the state it left. */
export type NoticeChanged = Schemas['NoticeChanged']
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
/** What one chore's runs cost in the last day and the last 30 days (DESIGN §13). */
export type ChoreSpend = Schemas['ChoreSpend']
/** What one chore's runs that started in a window cost: how many, how many reported a cost, and the total. */
export type ChoreSpendWindow = Schemas['ChoreSpendWindow']
/** One run of a chore (DESIGN §19). */
export type ChoreRun = Schemas['ChoreRun']
/** An open finding: one the chore's latest `ok` run reported (DESIGN §19). */
export type ChoreFinding = Schemas['ChoreFinding']
/** One chore run: its row as its chore's page lists it, and the whole of what it reported (DESIGN §19, §22). */
export type ChoreRunDetail = Schemas['ChoreRunDetail']
/** A finding as one chore run reported it (DESIGN §19). */
export type ChoreRunFinding = Schemas['ChoreRunFinding']
/** What a run's or chore run's log, or a tick's output, holds of its session, read from its events (DESIGN §22). */
export type Transcript = Schemas['Transcript']
/** One entry of a transcript, told apart by its `kind`: text, a tool call, a model call's end, or an error. */
export type TranscriptEntry = Transcript['entries'][number]
/** One tool call, once it ended: its input as indented JSON, and its output, or its error. */
export type TranscriptTool = Schemas['TranscriptTool']
/** One model call's end: why, what it cost, and its tokens together and by kind. */
export type TranscriptStep = Schemas['TranscriptStep']
/** One model call's tokens by kind: what it was sent, from the cache or not, and what it wrote. */
export type TranscriptTokens = Schemas['TranscriptTokens']
/** The message canopy gave the runtime to start a session: its first model call's input, as far as any file says. */
export type TranscriptPrompt = Schemas['TranscriptPrompt']
/** The end of a tick's overseer output as written, stdout then stderr: what the transcript leaves out too. */
export type TickOutput = Schemas['TickOutput']
/** A search: the words it looked for, its hits by source and newest first, and the sources that had more. */
export type SearchResults = Schemas['SearchResults']
/** One row holding every word of a search, and where it opens. */
export type SearchHit = Schemas['SearchHit']
/** Where a search hit is (DESIGN §22, Search), in the order the search reads them. */
export type SearchSource = Schemas['SearchSource']
/** One review run of a PR at a commit (DESIGN §21): canopy's own review, never on the PR (D114). */
export type ReviewSummary = Schemas['ReviewSummary']
/** A PR the journal knows (DESIGN §22): one of the loop's own, by its ticket's unit, or one canopy reviewed. */
export type PullRequest = Schemas['PullRequest']
/** One PR: its review runs, newest first, and the decisions that name it. */
export type PullRequestDetail = Schemas['PullRequestDetail']
/** One review run in full: its summary, findings anchored on its diff, the diff, and the PR's other runs. */
export type ReviewDetail = Schemas['ReviewDetail']
/** One finding, with the file and new-side line it falls on in the diff, when the diff shows them. */
export type ReviewFinding = Schemas['ReviewFinding']
/** How much a finding holds the merge: `blocking`, `major`, or `minor`. */
export type FindingSeverity = Schemas['FindingSeverity']
/** The reviewed commit's diff: the PR's own text, untrusted and bounded. */
export type ReviewDiff = Schemas['ReviewDiff']
/** One file the reviewed commit changes, with its hunks. */
export type DiffFile = Schemas['DiffFile']
/** One line of a hunk, with its number on each side it is on. */
export type DiffLine = Schemas['DiffLine']

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
