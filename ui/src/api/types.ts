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
/** One time the operator forgot a ticket's work (DESIGN §22), and the branch and PRs it dropped. */
export type TicketForget = Schemas['TicketForget']
/** What a ticket's or a PR's agent runs cost in all (DESIGN §13), and how many runs and reviews that counts. */
export type CostTotal = Schemas['CostTotal']
/** A ticket's plans: whether it needs one, its newest as the file stands, every plan, and the operator's comments. */
export type TicketPlans = Schemas['TicketPlans']
/** A plan as its file stands now, read bounded and never through a link (DESIGN §25). */
export type PlanFile = Schemas['PlanFile']
/** One of a ticket's plans: its status and approval, never its text. */
export type PlanSummary = Schemas['PlanSummary']
/** One of the operator's comments on a plan: a thread on a passage, with its replies. */
export type PlanThreadView = Schemas['PlanThreadView']
/** What the operator's word on a plan did: approve, request, or skip. */
export type PlanChanged = Schemas['PlanChanged']
/** A plan's file as saved from the editor: its hash now, which the next save sends back. */
export type PlanSaved = Schemas['PlanSaved']
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
/** What trying a chore started: its recorded run, going on in the background (DESIGN §19). */
export type ChoreTried = Schemas['ChoreTried']
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
/** What asking the loop for a tick now found: whether a running tick must end first. */
export type TickAsked = Schemas['TickAsked']
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
/** A finished piece of the agent's text, or of its reasoning. */
export type TranscriptText = Schemas['TranscriptText']
/** One tool call, once it ended: its input as indented JSON, and its output, or its error. */
export type TranscriptTool = Schemas['TranscriptTool']
/** One model call's end: why, what it cost, and its tokens together and by kind. */
export type TranscriptStep = Schemas['TranscriptStep']
/** An error the runtime reported: its name and its message. */
export type TranscriptError = Schemas['TranscriptError']
/** One model call's tokens by kind: what it was sent, from the cache or not, and what it wrote. */
export type TranscriptTokens = Schemas['TranscriptTokens']
/** The message canopy gave the runtime to start a session: its first model call's input, as far as any file says. */
export type TranscriptPrompt = Schemas['TranscriptPrompt']
/** The end of a tick's overseer output as written, stdout then stderr: what the transcript leaves out too. */
export type RawOutput = Schemas['RawOutput']
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
/** One hunk of a file's diff: what follows its `@@` ranges, and its lines. */
export type DiffHunk = Schemas['DiffHunk']
/** One line of a hunk, with its number on each side it is on. */
export type DiffLine = Schemas['DiffLine']
/** A PR's review threads on the diff a run kept, and every draft for it (DESIGN §29). */
export type PullRequestThreads = Schemas['PullRequestThreads']
/** One review thread as canopy's reader last read it, where it sits on the diff, and the drafts answering it. */
export type ReviewThread = Schemas['Thread']
/** One comment on a review thread: someone else's text, shown as text. */
export type ThreadComment = Schemas['ThreadComment']
/** A comment a run drafted in place of posting it: a worker's text until the operator sends it. */
export type Draft = Schemas['Draft']
/** Where a draft stands, as `canopy draft list` prints it. */
export type DraftStatus = Schemas['DraftStatusName']
/** What a send did: the drafts posted, sent before, not sent and why, and those it cannot say of. */
export type DraftsSent = Schemas['DraftsSent']

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
/** One tier of agent memory and what reads it (DESIGN §28), in the words every surface uses. */
export type MemoryTier = Schemas['MemoryTier']
/** Agent memory's tiers while one is on: the header's readout and each tier's mode. */
export type MemoryState = Schemas['MemoryState']
/** One note, proposal, or lesson. Its text is a worker's, or the operator's for a lesson: plain text. */
export type MemoryEntry = Schemas['MemoryEntry']
/** A proposal waiting on the operator, with where it came from. */
export type MemoryProposal = Schemas['MemoryProposal']
/** What a run would be served of one tier, as its prompt would carry it. */
export type MemoryDigest = Schemas['MemoryDigest']
/** One ticket's notes in force, counted, for the memory page's list across tickets. */
export type TicketNotes = Schemas['TicketNotes']
/** Every tier's memory: the tickets with notes in force, the proposals waiting, and the lessons. */
export type MemoryOverview = Schemas['MemoryOverview']
/** One ticket's notes, and what its next run would be served. */
export type TicketMemory = Schemas['TicketMemory']
/** What a run wrote and read of memory, and what it had refused. */
export type RunMemory = Schemas['RunMemory']
/** A promote, as `canopy memory promote ID [--text TEXT] [--repo NAME]` takes it. */
export type PromoteRequest = Schemas['PromoteRequest']
/** What a promote made: the lesson, what it came from, the lesson it superseded, and whether runs read it now. */
export type MemoryPromoted = Schemas['MemoryPromoted']
/** A proposal the operator rejected. */
export type MemoryRejected = Schemas['MemoryRejected']
/** A lesson the operator renewed, and when it is next due for review. */
export type MemoryRenewed = Schemas['MemoryRenewed']
/** A memory whose text a forget deleted, its row left. */
export type MemoryForgotten = Schemas['MemoryForgotten']
