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
/** What the runs did since a moment: how many ended, and how many PRs they opened first. */
export type RunsSince = Schemas['RunsSince']
/** A running run's latest tool call, as `_run` read it from the worker's events (DESIGN §8). */
export type RunActivity = Schemas['RunActivity']
/** Where a running agent's work stands, in its own words: its progress (DESIGN §41). */
export type RunCard = Schemas['RunCard']
/** A decision a running agent asks the operator for in its progress, with the answer they gave (DESIGN §41). */
export type RunCardQuestion = Schemas['RunCardQuestion']
/** The operator's answer to a running run's question, as recorded: what `canopy reply run:ID LETTER` says. */
export type Answered = Schemas['Answered']
/** Which models served an agent run, read from its session after it ended (DESIGN §13), or why none are shown. */
export type ModelsServed = Schemas['ModelsServed']
/** One model that wrote an agent run's replies, with how many and what they cost. */
export type ServedModel = Schemas['ServedModel']
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
/** What one model cost over a ticket's runs, as their sessions say (DESIGN §13). */
export type ModelCost = Schemas['ModelCost']
/** A ticket's plans: whether it needs one, its newest as the file stands, every plan, and the operator's comments. */
export type TicketPlans = Schemas['TicketPlans']
/** A plan as its file stands now, read bounded and never through a link (DESIGN §25). */
export type PlanFile = Schemas['PlanFile']
/** The persona a run wrote in (DESIGN §31), and its instructions as its file stands now. */
export type RunPersona = Schemas['RunPersona']
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
/** A start, and the persona and model each of the ticket's agents takes from it, as the ticket's override. */
export type StartRequest = Schemas['StartRequest']
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
/** The persona one of a ticket's agents writes in at its next run, and where that comes from (DESIGN §31). */
export type AgentPersona = Schemas['AgentPersona']
/** The model one of a ticket's agents runs on at its next run, and where that comes from (DESIGN §13). */
export type AgentModel = Schemas['AgentModel']
/** The models the runtime lists, as `canopy models` prints them (DESIGN §13): what the operator may choose from. */
export type ModelList = Schemas['ModelList']
/** The model config chooses for each of canopy's agents and each chore, and the files that set them (DESIGN §13). */
export type ConfigModels = Schemas['ConfigModels']
/** The model `[runtime.models]` chooses for one of canopy's agents, or none: the runtime's default. */
export type ConfiguredModel = Schemas['ConfiguredModel']
/** The model one chore runs on as config chooses it, and where that choice comes from (DESIGN §13, §19). */
export type ChoreModel = Schemas['ChoreModel']
/** A persona a run could get, as `canopy personas` lists it (DESIGN §31): what the operator may choose from. */
export type PersonaChoice = Schemas['PersonaChoice']
/** Every persona a run could get, and the one a review request that chooses none is reviewed in (DESIGN §31). */
export type PersonaList = Schemas['PersonaList']
/** Every skill the runtime finds for canopy's agents, with each one's file and text (DESIGN §13). */
export type SkillList = Schemas['SkillList']
/** A skill the runtime finds: its file, where that is, and its text. */
export type Skill = Schemas['Skill']
/** Where a skill's file is: canopy's own, the workspace's, the operator's home, the runtime's, or elsewhere. */
export type SkillSource = Schemas['SkillSource']
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
/** What a mark of subjects seen recorded: every subject named, and the ones not seen before. */
export type SeenMarked = Schemas['SeenMarked']
/** One message on the event stream, told apart by its `type` (`applyStreamEvent` in live.ts). */
export type StreamEvent = Schemas['StreamEvent']
/** One repository's pool of worktrees, read when asked for. */
export type Pool = Schemas['Pool']
/** The machine the loop runs on, and the loop's own process, read when asked for. */
export type HostResources = Schemas['HostResources']
/** One filesystem canopy writes to, with what it keeps there. */
export type Disk = Schemas['Disk']
/** What canopy keeps on a disk. */
export type DiskUse = Schemas['DiskUse']
/** The readings of the machine the server keeps in memory, the last hour's at most, oldest first. */
export type HostHistory = Schemas['HostHistory']
/** What the system resources page's graphs draw of one reading of the machine. */
export type HostSample = Schemas['HostSample']
/** The machine's processes as read when asked for, each measured since the read before; none off Linux. */
export type HostProcesses = Schemas['HostProcesses']
/** One process on the machine: its parent, name, command line, account, state, processors kept busy, and memory. */
export type HostProcess = Schemas['HostProcess']
/** What a process was doing when read; the load average counts the `running` and `disk` ones. */
export type ProcessState = Schemas['ProcessState']
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
/** What one kind's runs in a spend window spent on one model, as their sessions say; a null model for the unnamed. */
export type SpendModel = Schemas['SpendModel']
/** One week of a kind's first model calls, or one chore's or one model's of the kind: their size and cache hit rate. */
export type SpendFirstCallWeek = Schemas['SpendFirstCallWeek']
/** The local month so far against the operator's monthly budget. */
export type SpendMonth = Schemas['SpendMonth']
/** What every session the runtime keeps that started in a spend window cost, canopy's apart from the rest. */
export type SpendSessions = Schemas['SpendSessions']
/** A kind of agent run, as the spend breakdown counts it: the overseer, workers, plans, chores, reviews, or tasks. */
export type SpendKind = Schemas['SpendKind']
/** The last months, oldest first, as the reports page shows them. */
export type MonthlyReport = Schemas['MonthlyReport']
/** One local calendar month: what each kind of run cost, by model, in dollars and tokens, and the tickets it landed. */
export type ReportMonth = Schemas['ReportMonth']
/** What one kind of run cost in a month, in dollars and tokens. */
export type ReportKind = Schemas['ReportKind']
/** What one model's replies cost in a month, over every kind of run; a null model for the unnamed. */
export type ReportModel = Schemas['ReportModel']
/** A ticket the loop marked done as merged in a month, and what getting there took. */
export type ReportTicket = Schemas['ReportTicket']
/** The tokens a month's runs reported, by kind, and the share of what was sent read from the cache. */
export type ReportTokens = Schemas['ReportTokens']
/** How the worker runs of a window of local days answered each repository's checklist, as `canopy checklist` counts. */
export type ChecklistCounts = Schemas['ChecklistCounts']
/** One item of one repository's checklist: the runs reminded of it, and how many gave each answer. */
export type ChecklistItemCounts = Schemas['ChecklistItemCounts']
/** The window before the checklist's counts: the items given, held, and unanswered, over every item. */
export type ChecklistPrevious = Schemas['ChecklistPrevious']
/** What a run answered of one item of its repository's checklist, with a held item's reason, on the run's page. */
export type ChecklistAnswer = Schemas['ChecklistAnswer']
/** A worker's answer to a checklist item: pass, fixed, held, n/a, or unanswered. */
export type ItemAnswer = Schemas['ItemAnswer']
/** How the last days' runs ended, the newest failures, what the guards refused, and each day's counts. */
export type HealthReport = Schemas['HealthReport']
/** How many of one kind's runs, of one sort, ended in one status, and what they cost. */
export type HealthOutcome = Schemas['HealthOutcome']
/** One run that ended in a failed status, with what it was about by its kind. */
export type HealthFailure = Schemas['HealthFailure']
/** How often a guard refused what a tick asked for. */
export type HealthRefusal = Schemas['HealthRefusal']
/** One local day's ended and failed runs, by kind. */
export type HealthDay = Schemas['HealthDay']
/** A count of runs by kind. */
export type HealthCounts = Schemas['HealthCounts']
/** The window before a health report's: its runs, failures, and what they cost. */
export type HealthPrevious = Schemas['HealthPrevious']
/** The window's failures one harness note explained, or `other`: how many, of which kinds, and the newest. */
export type HealthCause = Schemas['HealthCause']
/** One thing a guard refused: the ticket, chore, or PR it named, the run's kind, how often, and the latest tick. */
export type HealthAsk = Schemas['HealthAsk']
/** How long one sort of run took against its kind's timeout: its median, slowest, timeouts, and spread. */
export type HealthDuration = Schemas['HealthDuration']
/** A sort's ended runs by their length's share of its timeout, a band each. */
export type HealthBins = Schemas['HealthBins']
/** How many of a kind's ended runs reported no cost, of how many. */
export type SpendUnpriced = Schemas['SpendUnpriced']
/** Which checks failed in a window, what fixing them cost, and whether the flaky kicks worked. */
export type CiReport = Schemas['CiReport']
/** One check's runs in a window, by its name across every PR, and how often a new head fixed it. */
export type CiCheck = Schemas['CiCheck']
/** One local day's red check runs, by the chart's series. */
export type CiDay = Schemas['CiDay']
/** A `resume` for `ci`, or a retired `fix-ci`, with the checks it found red. */
export type CiFix = Schemas['CiFix']
/** A check a fix found red, and how its first run on the next head ended. */
export type CiFixedCheck = Schemas['CiFixedCheck']
/** A flaky kick, and whether the checks red before it came back red. */
export type CiKick = Schemas['CiKick']
/** A PR the window's kicks reran the checks of, against `trust.max_flaky_kicks`. */
export type CiKickedPullRequest = Schemas['CiKickedPullRequest']
/** A PR with a check run in a window: its first red run, and its first green head after it. */
export type CiPullRequest = Schemas['CiPullRequest']
/** How a check run counts: red, green, or neither. */
export type CiVerdict = Schemas['CiVerdict']
/** The window before a CI report's: its heads, green first, red runs, and fixes. */
export type CiPrevious = Schemas['CiPrevious']
/** Where a window's review feedback came from, how long it took, and what answering it cost. */
export type ReviewsReport = Schemas['ReviewsReport']
/** A PR in a window: its feedback, how soon its first review came, and what answering cost. */
export type ReviewsPullRequest = Schemas['ReviewsPullRequest']
/** Someone who left feedback in a window, trusted or not, with how soon they reviewed. */
export type ReviewsReviewer = Schemas['ReviewsReviewer']
/** One local day's first reviews, by how long each waited. */
export type ReviewsDay = Schemas['ReviewsDay']
/** A feedback plan made in a window, how it was approved, and the resumes after it. */
export type ReviewsRound = Schemas['ReviewsRound']
/** A window's feedback plans of one effort, beside the resumes that followed. */
export type ReviewsEffort = Schemas['ReviewsEffort']
/** canopy's review runs of one purpose and status in a window. */
export type ReviewsRunCount = Schemas['ReviewsRunCount']
/** The window before a Reviews report's: its reviews, PRs, first reviews and their median, and rounds. */
export type ReviewsPrevious = Schemas['ReviewsPrevious']
/** How a window's plans were approved, by the level their planners were offered, and what their PRs needed. */
export type PlansReport = Schemas['PlansReport']
/** A ticket plan written in a window: how it went, how long approving it took, and the resumes its ticket needed. */
export type PlansRow = Schemas['PlansRow']
/** A window's approved plans of one level and one outcome, and what their tickets needed after. */
export type PlansGroup = Schemas['PlansGroup']
/** A window's plans the operator approved, of one size, and how long approving them took. */
export type PlansLength = Schemas['PlansLength']
/** A level of `policy.planner_may_approve`: `off` where the planner was asked nothing. */
export type PlanLevel = Schemas['PlanLevel']
/** How a plan went: approved by its planner or by you, as written or revised, replaced, dropped, or waiting. */
export type PlanOutcome = Schemas['PlanOutcome']
/** A tick, as `canopy status`'s first line shows the latest (DESIGN §14), with how many decisions it recorded. */
export type Tick = Schemas['Tick']
/** The latest tick, or none before the first, and the newest message a tick has acknowledged. */
export type LastTick = Schemas['LastTick']
/** Whether the operator paused the loop (no tick starts until it is resumed), and the notice to workers in force. */
export type LoopState = Schemas['LoopState']
/** What may run at once, `[capacity]`: the limits the runs page counts what is running against (DESIGN §8). */
export type Capacity = Schemas['Capacity']
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
/** One slot of a pool, as the pool's `status` reports it, with what in the journal holds it. */
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
/** A task as `canopy task list` lists it: its text, where it runs, and where it stands (DESIGN §36). */
export type TaskSummary = Schemas['TaskSummary']
/** Where a task stands: queued, awaiting the operator's reply, stopped, or its latest run's status. */
export type TaskStanding = TaskSummary['standing']
/** One run of a task's worker (DESIGN §36). */
export type TaskRun = Schemas['TaskRun']
/** One task, as `canopy show task:N` prints it: the task, every run, its conversation, and its tickets. */
export type TaskDetail = Schemas['TaskDetail']
/** One run of a task, with the whole of what it said, as its page shows it. */
export type TaskRunDetail = Schemas['TaskRunDetail']
/** A ticket a task's run reported filing, unlabeled, so worked only once the operator says so. */
export type TaskTicket = Schemas['TaskTicket']
/** The report a task run left, as its file stands now, or why it is no report any more (DESIGN §36). */
export type TaskReport = Schemas['TaskReport']
/** What a task's submission recorded: its id, where it runs, and whether any tick may start it (DESIGN §36). */
export type TaskSubmitted = Schemas['TaskSubmitted']
/** What a reply to a task recorded, and the run of it still working, which the next run waits on. */
export type TaskReplied = Schemas['TaskReplied']
/** What a stop of a task did: already stopped, or dropped while queued, and the run still working it. */
export type TaskStopped = Schemas['TaskStopped']
/** A text file the operator attached to a ticket or a task, for its runs to read as data (DESIGN §22). */
export type Attachment = Schemas['Attachment']
/** A ticket's or a task's attachments, and the limits `policy` holds them to. */
export type Attachments = Schemas['Attachments']
/** What an upload recorded: the attachment, as its subject's page lists it. */
export type Attached = Schemas['Attached']
/** What a removal of an attachment removed: its name. */
export type Detached = Schemas['Detached']
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
/** A PR the operator asked canopy to review that no review of is running yet: it waits on a tick (DESIGN §21). */
export type RequestedReview = Schemas['RequestedReview']
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
/** A review of a PR the loop does not own as the comment review it would post (DESIGN §34), at its newest version. */
export type ReviewDraft = Schemas['ReviewDraft']
/** One comment of a review's draft, on a line of the diff the review kept. */
export type ReviewDraftComment = Schemas['ReviewDraftComment']
/** One version of a review's draft, as its history lists it. */
export type ReviewDraftVersion = Schemas['ReviewDraftVersion']
/** What a publish of a review's draft did: the draft as it now stands, and why nothing posted, if nothing did. */
export type ReviewDraftPublished = Schemas['ReviewDraftPublished']
/** What a note on a review's draft recorded, as `canopy reply review:ID` reports it. */
export type ReviewDraftNoted = Schemas['ReviewDraftNoted']
/** How much a finding holds the merge: `blocking`, `major`, or `minor`. */
export type FindingSeverity = Schemas['FindingSeverity']
/**
 * Why the operator dismissed a review's finding (DESIGN §21): `wrong`, `intentional`, `not_worth_it`, or
 * `out_of_scope`.
 */
export type DismissalReason = Schemas['DismissalReasonName']
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
/** The feedback plan item a thread's draft started from, and whether canopy found the run's text departs from it. */
export type DraftFromPlan = Schemas['DraftFromPlan']
/** Where a draft stands, as `canopy draft list` prints it. */
export type DraftStatus = Schemas['DraftStatusName']
/** A reaction a thread's draft stages on the comment it names, by GitHub's name for it. */
export type Reaction = Schemas['ReactionName']
/** What a send did: the drafts posted, sent before, not sent and why, and those it cannot say of. */
export type DraftsSent = Schemas['DraftsSent']
/** A ticket's current feedback plan, as its PR's page shows it beside the threads (DESIGN §32). */
export type FeedbackPlan = Schemas['FeedbackPlan']
/** Where a feedback plan stands: waiting, stale, approved, or spent by the resume that went ahead on it. */
export type FeedbackPlanStatus = Schemas['FeedbackPlanStatusName']
/** An item a feedback plan covers, and what it proposes for it. */
export type FeedbackPlanItem = Schemas['FeedbackPlanItem']
/** What an approval of a feedback plan did: the items it addresses, those it leaves out, and its message. */
export type FeedbackPlanApproved = Schemas['FeedbackPlanApproved']
/** A ticket's feedback plan while it waits on the operator, as its ticket's summary names it for the attention list. */
export type WaitingFeedbackPlan = Schemas['WaitingFeedbackPlan']
/** The feedback plan a `feedback-plan` run wrote, as the run's page names it: its PRs and where it stands. */
export type FeedbackPlanWritten = Schemas['FeedbackPlanWritten']

/** Every run state, in display order. `satisfies` fails the typecheck if the schema gains a state these miss. */
export const RUN_STATES = ['running', 'blocked', 'failed', 'stopped', 'done'] as const satisfies readonly RunState[]

/** Every kind of run the spend breakdown counts, in `canopy spend`'s order. */
export const SPEND_KINDS = [
    'overseer',
    'workers',
    'plans',
    'chores',
    'reviews',
    'tasks',
] as const satisfies readonly SpendKind[]

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
/** What a lesson was promoted from: a proposal, or a ticket's note. */
export type MemoryOrigin = Schemas['MemoryOrigin']
/** What canopy memory search finds as the operator: every memory that keeps its text, best match first. */
export type MemoryFound = Schemas['MemoryFound']
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
/** A lesson the operator pinned: never due for review, and served before the rest. */
export type MemoryPinned = Schemas['MemoryPinned']
/** A lesson the operator unpinned: due for review again later. */
export type MemoryUnpinned = Schemas['MemoryUnpinned']
/** A memory whose text a forget deleted, its row left. */
export type MemoryForgotten = Schemas['MemoryForgotten']
/** An edit, as `canopy memory edit ID [--text TEXT] [--repo NAME | --every-repo]` takes it. */
export type LessonEditRequest = Schemas['LessonEditRequest']
/** What an edit made: the lesson's new version, the one it replaced, and whether runs read it now. */
export type MemoryEdited = Schemas['MemoryEdited']
/** Every version of a lesson or a note, newest first. */
export type MemoryHistory = Schemas['MemoryHistory']
/** The keys the settings page edits in the operator's user config, each with its value, source, and bound (M41). */
export type ConfigSettings = Schemas['ConfigSettings']
/** One key the settings page edits: a limit within its bound, or a trust setting that may only get stricter. */
export type ConfigKey = Schemas['ConfigKey']
/** A config key's value: a count or minutes, a switch, a choice, a list's entries, or counts by repository. */
export type ConfigValue = Schemas['ConfigValue']
/** What a save from the settings page wrote, apart from what the reload it asked for found. */
export type ConfigSaved = Schemas['ConfigSaved']
