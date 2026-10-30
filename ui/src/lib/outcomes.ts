import { ApiError } from '@/api/client'
import type {
    Answered,
    AgentModel,
    Attached,
    Detached,
    AgentPersona,
    ChoreTried,
    ConfigReload,
    Dismissed,
    Draft,
    DraftsSent,
    FeedbackPlanApproved,
    Forgot,
    Granted,
    MemoryEdited,
    MemoryEntry,
    MemoryForgotten,
    MemoryPinned,
    MemoryPromoted,
    MemoryRenewed,
    MemoryUnpinned,
    NoticeChanged,
    PlanChanged,
    Replied,
    ReviewDismissed,
    ReviewDraft,
    ReviewDraftNoted,
    ReviewDraftPublished,
    ReviewRequested,
    ReviewRequestStopped,
    ReviewSent,
    Started,
    Stopped,
    TaskSubmitted,
    TaskReplied,
    TaskStopped,
} from '@/api/types'
import { currentClock } from '@/lib/clock'
import { REACTION_LOOKS } from '@/lib/drafts'
import { RUNTIME_DEFAULT } from '@/lib/models'
import { taskRef } from '@/lib/refs'
import { localTime } from '@/lib/time'
import type { NewToast } from '@/lib/toasts'

// What each of the operator's actions did, in the words the CLI's verb prints (canopy/cli/conversation.py), and what
// one that failed says in canopy's words rather than the browser's.

/**
 * What a failed action says: a refusal's reason, or the server's own words, as they are; for an answer that gave only
 * its status, whether the action was done; and when no answer came at all (the browser's `Failed to fetch`, an aborted
 * request), that canopy did not answer, which almost always means the loop that serves the page stopped. A failed read
 * says the same in its own sentence (`readFailure`).
 */
export function failedText(error: unknown): string {
    if (error instanceof ApiError) {
        if (!error.bare) {
            return error.message
        }
        // A 4xx is turned away before the action runs; a 5xx may come after it ran, or from a proxy in front of canopy.
        return error.status < 500
            ? `canopy answered ${error.status}: nothing was done`
            : `canopy failed (${error.status}): it may not have been done`
    }
    // fetch rejects with a bare TypeError when no answer comes, so a TypeError from a bug in the page reads the same:
    // fetch gives nothing narrower to tell them apart by.
    if (error instanceof TypeError || (error instanceof DOMException && error.name === 'AbortError')) {
        return 'canopy did not answer: is `canopy loop` running?'
    }
    if (error instanceof Error) {
        return error.message
    }
    return typeof error === 'string' ? error : 'the request failed'
}

/** What a start did, as `canopy start` says it: whether it was already started, and any run still working it. */
export function startedText(key: string, started: Started): string {
    const state = started.already ? 'was already started' : 'is started'
    const head = `${key} ${state}, privately: workers read it and write nothing to it.`
    if (started.running_run === null) {
        return `${head} The next tick picks it up.`
    }
    const kind = started.running_private
        ? 'private'
        : 'public, dispatched before this start, so it may write to the ticket'
    return `${head} Run ${started.running_run} (${kind}) is still working it.`
}

/** What a stop did, as `canopy stop` says it: whether it was already stopped, and with `now`, whether its run ended. */
export function stoppedText(key: string, stopped: Stopped, now: boolean): string {
    const head = `${key} ${stopped.already ? 'was already stopped' : 'is stopped'}; nothing dispatches it now.`
    if (stopped.running_run === null) {
        return head
    }
    if (!now) {
        return `${head} Run ${stopped.running_run} is still working it and will finish.`
    }
    return stopped.ended
        ? `${head} Run ${stopped.running_run} was ended and its slots returned.`
        : `${head} Run ${stopped.running_run} had already ended.`
}

/**
 * What a stop of a task did, as `canopy stop task:N` says it (canopy/cli/tasks.py): already stopped, dropped before
 * its first run, or stopped; then the run still working it, which finishes unless `now` ended it. Stop now is the
 * page's `--now`.
 */
export function taskStoppedText(id: number, stopped: TaskStopped, now: boolean): string {
    const ref = taskRef(id)
    let head = `${ref} is stopped; nothing starts it again.`
    if (stopped.already) {
        head = `${ref} was already stopped.`
    } else if (stopped.dropped) {
        head = `${ref} is stopped; it had not started, and nothing starts it now.`
    }
    const run = stopped.running_run
    if (run === null) {
        return head
    }
    if (!now) {
        return `${head} Its run ${run} is still working and will finish; Stop now ends it.`
    }
    return stopped.ended
        ? `${head} Its run ${run} was ended and its slot returned.`
        : `${head} Its run ${run} had already ended.`
}

/** What a forget cleared, and what is left for the operator: closing its PRs and deleting its branch on origin. */
export function forgotText(key: string, forgot: Forgot): string {
    const head = `${key} is forgotten: its next implement starts over on a new branch.`
    const named = [...(forgot.branch === null ? [] : [`branch ${forgot.branch}`]), ...forgot.prs]
    if (named.length === 0) {
        return head
    }
    return (
        `${head} canopy no longer tracks ${named.join(', ')}. ` +
        'Close its PRs and delete its branch on origin yourself: until you do, the overseer still finds them and the ' +
        'ticket cannot start over.'
    )
}

/** Where an agent's persona comes from, in the words `canopy persona KEY` uses. */
export const PERSONA_SOURCES: Record<AgentPersona['source'], string> = {
    ticket: "this ticket's override",
    config: '[personas]',
    default: "canopy's default",
}

/** What choosing or clearing a ticket's persona did, as `canopy persona` says it. */
export function personaText(ticketKey: string, now: AgentPersona): string {
    const source = PERSONA_SOURCES[now.source]
    return `${ticketKey}'s ${now.agent} runs write in ${now.persona} from their next run: ${source}.`
}

/**
 * Where an agent's model comes from, as its row on a ticket's page says it: `canopy model KEY`'s words, but for the
 * runtime's default, which the row names as the model does.
 */
export const MODEL_SOURCES: Record<AgentModel['source'], string> = {
    ticket: "this ticket's override",
    config: '[runtime.models]',
    default: RUNTIME_DEFAULT,
}

/** An agent's model as a ticket's page names it: its id, or the runtime's default when nothing sets one. */
export function modelName(model: string | null): string {
    return model ?? MODEL_SOURCES.default
}

/**
 * What choosing or clearing a ticket's model did, as `canopy model` says it, naming config's variant when the override
 * sets it aside.
 */
export function modelText(ticketKey: string, now: AgentModel): string {
    const source = now.source === 'default' ? 'nothing sets one' : MODEL_SOURCES[now.source]
    const model = now.model ?? "the runtime's default"
    const dropped =
        now.dropped_variant === null ? '' : ` (config's variant \`${now.dropped_variant}\` no longer applies)`
    return `${ticketKey}'s ${now.agent} runs use ${model} from their next run: ${source}${dropped}.`
}

/**
 * What a grant did, as `canopy grant` says it: the runs so far, which still count, and the limit now. `subject` is the
 * ticket's key, or the PR's URL for its reviews.
 */
export function grantedText(subject: string, granted: Granted): string {
    if (granted.kind === 'review') {
        return (
            `${subject} has had ${granted.runs} review runs, and may now have ${granted.limit}. ` +
            'The next tick decides whether to review it.'
        )
    }
    return (
        `${subject} in ${granted.repo ?? 'its repository'} has had ${granted.runs} ${granted.kind} runs, and may now ` +
        `have ${granted.limit}. The next tick decides whether to dispatch it.`
    )
}

/** What an answer to a running agent's question did, as `canopy reply run:ID LETTER` says it. */
export function answeredText(answered: Answered): string {
    const said = answered.already
        ? `It was already answered ${answered.letter}: ${answered.option}. Nothing new recorded.`
        : `Answered ${answered.letter}: ${answered.option}.`
    const heard = answered.heard
        ? 'Its agent hears it on its next tool call.'
        : 'Its agent had already ended, and will not hear it.'
    return `${said} ${heard}`
}

/** What a note to a chore did, as `canopy reply chore:NAME` says it: its next runs read it, not the next tick. */
export function notedText(name: string, replied: Replied): string {
    if (replied.new) {
        return `Recorded message ${replied.message_id} on chore:${name}. Its next run reads it.`
    }
    return `Message ${replied.message_id} on chore:${name} already says this; nothing new recorded.`
}

/** What trying a chore started, as `canopy chore try` says it: a recorded run, its findings listed when it ends. */
export function triedText(tried: ChoreTried): string {
    return (
        `chore try ${tried.chore}: recorded as chore run ${tried.run_id}, running now. ` +
        'Its findings reach the attention list when it ends.'
    )
}

/** What a dismissal did, as `canopy dismiss` says it: off the attention list until it clears, or listed again. */
export function dismissedText(dismissed: Dismissed): string {
    const head = `chore:${dismissed.chore} ${dismissed.finding}`
    if (dismissed.dismissed) {
        return `${head} is dismissed: it is off the attention list until the chore stops reporting it.`
    }
    return `${head} is listed again while the chore reports it.`
}

/** What a dismissal of a review's finding did, as `canopy dismiss review:ID N --reason REASON` says it. */
export function reviewDismissedText(dismissed: ReviewDismissed): string {
    const head = `review:${dismissed.run} finding ${dismissed.finding}`
    if (dismissed.dismissed) {
        return `${head} is dismissed${dismissedAs(dismissed)}: no worker or tick acts on it.`
    }
    return `${head} is no longer dismissed: a resume hands it to the worker again.`
}

/**
 * What dismissing a finding of a review with a draft did, in the draft's terms (DESIGN §34): left out of the operator's
 * review, or back in it, in the reviewer's words.
 */
export function reviewPointText(dismissed: ReviewDismissed): string {
    const head = `review:${dismissed.run} finding ${dismissed.finding}`
    if (dismissed.dismissed) {
        return `${head} is dismissed${dismissedAs(dismissed)}: left out of your review.`
    }
    return `${head} is no longer dismissed: back in your review, in the reviewer's words.`
}

// ` as wrong`, as the CLI names the reason a finding was dismissed for; nothing for an answer without one.
function dismissedAs(dismissed: ReviewDismissed): string {
    return dismissed.reason === null ? '' : ` as ${dismissed.reason}`
}

/** What sending a review's findings did, as `canopy send review:ID N...` says it. */
export function reviewSentText(sent: ReviewSent): string {
    const head = `review:${sent.run} findings ${sent.findings.join(', ')}`
    const to = `${sent.ticket_key} as message ${sent.message_id}`
    if (sent.new) {
        return `${head} went to ${to}: the next tick reads it as your go-ahead.`
    }
    return `${head} already went to ${to}.`
}

/** What a change to review run `run`'s draft did, as `canopy review edit` says it: its version and hash now. */
export function reviewDraftEditedText(run: number, draft: ReviewDraft): string {
    return `Review run ${run}'s draft is version ${draft.version} now, hash ${draft.hash}: ${draft.change}.`
}

/** What a note on review run `run`'s draft recorded, as `canopy reply review:ID` says it. */
export function reviewDraftNotedText(run: number, noted: ReviewDraftNoted): string {
    return (
        `Recorded note ${noted.note} on review run ${run}'s draft, at version ${noted.after_version}. The next tick ` +
        'revises it, unless you change the draft first.'
    )
}

/**
 * What a publish of review run `run`'s draft did, as `canopy review publish` says it, where the draft's own linked
 * line does not say it: perhaps posted, which a read of the PR settles; or not published, and why. Null for a publish
 * that posted or staged it, which that line says.
 */
export function reviewDraftPublishedText(run: number, published: ReviewDraftPublished): string | null {
    const { draft } = published
    const version = `Version ${published.published} of review run ${run}'s draft`
    switch (draft.status) {
        case 'published':
        case 'staged': {
            return null
        }
        case 'unconfirmed': {
            return (
                `${version} may have been posted: the post ended without saying. A read of the PR settles it; canopy ` +
                'posts it no other time.'
            )
        }
        case 'waiting':
        case 'publishing':
        case 'discarded': {
            return `${version} was not published: ${published.failed ?? draft.why ?? 'nothing was posted'}`
        }
    }
}

/**
 * The toast a publish shows, in the words `canopy review publish` starts with: published, with where it is; staged,
 * with the PR's files page, where GitHub's own submit is; perhaps posted; or not published. A check only for the
 * first two.
 */
export function reviewDraftPublishedToast(run: number, prUrl: string, published: ReviewDraftPublished): NewToast {
    const { draft } = published
    const version = `version ${published.published} of review run ${run}'s draft`
    switch (draft.status) {
        case 'published': {
            return { title: `Published ${version}`, detail: draft.published_url ?? prUrl, tone: 'done' }
        }
        case 'staged': {
            return { title: `Staged ${version} in a review on GitHub`, detail: `${prUrl}/files`, tone: 'done' }
        }
        case 'unconfirmed': {
            return { title: `${capitalized(version)} may have been posted`, tone: 'failed' }
        }
        case 'waiting':
        case 'publishing':
        case 'discarded': {
            return { title: `${capitalized(version)} was not published`, tone: 'failed' }
        }
    }
}

/** The toast a discard shows, in the words `canopy review discard` says it with, and the PR it was of. */
export function reviewDraftDiscardedToast(run: number, prUrl: string): NewToast {
    return { title: `Discarded review run ${run}'s draft; nothing was posted`, detail: prUrl, tone: 'done' }
}

function capitalized(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}

/** What an edit of a draft did, as `canopy draft edit` says it: the text is the operator's now, named by its hash. */
export function draftEditedText(draft: Draft): string {
    return `Run ${draft.run}'s draft ${draft.number} is in your words now, hash ${draft.hash}.`
}

/** What a drop or its undo did, as `canopy draft drop` says it: where the draft stands now. */
export function draftDroppedText(draft: Draft): string {
    return `Run ${draft.run}'s draft ${draft.number} is ${draft.status}.`
}

/**
 * What a send did, as `canopy draft send` says it, a sentence for each draft: sent, with where it went; sent before;
 * not sent, and why; or perhaps posted, which a read of its PR settles, since canopy sends it no other time.
 */
export function draftsSentText(sent: DraftsSent): string {
    return [
        ...sent.posted.map((d) => `Sent run ${d.run}'s draft ${d.number}${sentTo(d)}.`),
        ...sent.already.map((d) => `Run ${d.run}'s draft ${d.number} was sent already${sentTo(d)}.`),
        ...sent.failed.map(({ draft, why }) => `Run ${draft.run}'s draft ${draft.number} was not sent: ${ended(why)}`),
        ...sent.unconfirmed.map(
            (d) =>
                `Run ${d.run}'s draft ${d.number} may have been posted: the post ended without saying. A read of its ` +
                'PR settles it; canopy sends it no other time.',
        ),
        ...sent.staged.map((d) => `Staged run ${d.run}'s draft ${d.number} in a review for you to submit on GitHub.`),
    ].join(' ')
}

/**
 * What a stage did, as `canopy draft stage` says it: each draft in the review, each reaction that went on its comment
 * at once, since GitHub can't keep one pending, and whatever a send would say of the rest.
 */
export function draftsStagedText(sent: DraftsSent): string {
    const reacted = [...sent.posted, ...sent.staged].flatMap((d) => (d.reacted === null ? [] : [{ d, r: d.reacted }]))
    return [
        ...sent.staged.map((d) => `Staged run ${d.run}'s draft ${d.number} in a review for you to submit on GitHub.`),
        ...reacted.map(
            ({ d, r }) =>
                `Run ${d.run}'s draft ${d.number} put ${REACTION_LOOKS[r].label.toLowerCase()} on its comment now, ` +
                "not in the review: GitHub can't keep a reaction pending.",
        ),
        draftsSentText({ ...sent, posted: [], staged: [] }),
    ]
        .filter((line) => line !== '')
        .join(' ')
}

/**
 * The toast a stage shows: how many drafts wait in the pending review, with where to finish it, `url`'s files page,
 * where GitHub's own submit is, and how many reactions went on GitHub at once. A check only when every draft is in
 * the review or, a reaction alone, on its comment.
 */
export function draftsStagedToast(sent: DraftsSent, url: string): NewToast {
    const total =
        sent.staged.length + sent.posted.length + sent.already.length + sent.failed.length + sent.unconfirmed.length
    const n = sent.staged.length
    const k = [...sent.posted, ...sent.staged].filter((d) => d.reacted !== null).length
    const staged = n === 1 ? 'Staged 1 draft in a review on GitHub' : `Staged ${n} drafts in a review on GitHub`
    const reactions = k === 1 ? '1 reaction' : `${k} reactions`
    let title = 'Staged nothing'
    if (n > 0) {
        title = k > 0 ? `${staged}, and added ${reactions} now` : staged
    } else if (k > 0) {
        title = `Added ${reactions} now`
    }
    return {
        title,
        ...(n > 0 && { detail: `${url}/files` }),
        tone: n + sent.posted.length === total ? 'done' : 'failed',
    }
}

/**
 * The toast a send shows, so a click on Send is acknowledged past the card's own line, which leaves with its attention
 * item at the next tick: what became of the one draft, or how many of several reached the PR, with where they went
 * when that is one place. A check only when every draft is on the PR; a cross when any is not, or may not be.
 */
export function draftsSentToast(sent: DraftsSent): NewToast {
    const done = [...sent.posted, ...sent.already]
    const total = done.length + sent.failed.length + sent.unconfirmed.length
    const urls = new Set(done.flatMap((d) => (d.sent_url === null ? [] : [d.sent_url])))
    const [url] = urls
    return {
        title: total === 1 ? oneSent(sent) : manySent(done.length, total),
        ...(urls.size === 1 && url !== undefined && { detail: url }),
        tone: done.length === total ? 'done' : 'failed',
    }
}

// What became of the one draft a send took, in the words `draftsSentText` starts its sentence with.
function oneSent(sent: DraftsSent): string {
    const [posted] = sent.posted
    const [already] = sent.already
    const [failed] = sent.failed
    const [unconfirmed] = sent.unconfirmed
    if (posted !== undefined) {
        return `Sent run ${posted.run}'s draft ${posted.number}`
    }
    if (already !== undefined) {
        return `Run ${already.run}'s draft ${already.number} was sent already`
    }
    if (failed !== undefined) {
        return `Run ${failed.draft.run}'s draft ${failed.draft.number} was not sent`
    }
    return unconfirmed === undefined
        ? 'Sent nothing'
        : `Run ${unconfirmed.run}'s draft ${unconfirmed.number} may have been posted`
}

// How many of several drafts a send put on the PR.
function manySent(done: number, total: number): string {
    if (done === total) {
        return `Sent ${total} drafts`
    }
    return done === 0 ? `${total} drafts not sent` : `Sent ${done} of ${total} drafts`
}

// Where a sent draft went, after a colon, or nothing when the post named no URL.
function sentTo(draft: Draft): string {
    return draft.sent_url === null ? '' : `: ${draft.sent_url}`
}

// The harness's words as a sentence: with a full stop unless they end in one.
function ended(words: string): string {
    return /[.!?]$/u.test(words) ? words : `${words}.`
}

/** What a reply did, as `canopy reply` says it: the message it recorded, or the one that already said it. */
export function repliedText(key: string, replied: Replied): string {
    const answered = replied.answers === null ? '' : `, answering message ${replied.answers}`
    if (replied.new) {
        return `Recorded message ${replied.message_id} on ${key}${answered}. The next tick reads it.`
    }
    return `Message ${replied.message_id} on ${key} already says this${answered}; nothing new recorded.`
}

// What `canopy task submit` adds while `capacity.max_tasks` is 0.
const NO_TASK_CAPACITY = 'capacity.max_tasks is 0, so no tick starts a task until you raise it.'

/**
 * The toast a submission shows as its form opens the task's page, in the words `canopy task submit` says it: the task,
 * which the next tick starts, and, while `capacity.max_tasks` is 0, that no tick will until the operator raises it, as
 * its title; where it runs, its repository and branch, under it.
 */
export function taskSubmittedToast(submitted: TaskSubmitted): NewToast {
    const head = `Submitted task:${submitted.id}; the next tick starts it.`
    return {
        title: submitted.no_capacity ? `${head} ${NO_TASK_CAPACITY}` : head,
        detail: `${submitted.repo} on ${submitted.branch}`,
        tone: 'done',
    }
}

/**
 * What a reply to a task did, as `canopy reply task:N` says it: the message it recorded, or the one that already said
 * it, then what starts the task's next run: the first tick after its running run ends, or the next tick.
 */
export function taskRepliedText(id: number, replied: TaskReplied): string {
    const next =
        replied.running_run === null
            ? 'The next tick starts its next run, on its branch.'
            : `Its run ${replied.running_run} is still working; the first tick after it ends starts the next run.`
    const ref = taskRef(id)
    const answered = replied.answers === null ? '' : `, answering message ${replied.answers}`
    const head = replied.new
        ? `Recorded message ${replied.message_id} on ${ref}${answered}.`
        : `Message ${replied.message_id} on ${ref} already says this${answered}; nothing new recorded.`
    return `${head} ${next}`
}

/** What setting a notice did, as `canopy notice` says it: the runs that hear it. The banner says until when. */
export function noticeSetText(changed: NoticeChanged): string {
    if (changed.loop.notice === null) {
        return 'The notice lapsed already: runs dispatched from now on hear none.'
    }
    return 'Notice set: runs dispatched from now on hear it until it lapses. The loop ticks soon.'
}

/** What a reload found, as the loop's terminal says it: the keys that changed, when the loop runs on them, and which
 * wait for a restart. With nothing changed there is nothing to apply, so it says only that. */
export function reloadedText(reload: ConfigReload): string {
    if (reload.changed.length === 0) {
        return 'Nothing changed: the config files say what the loop already runs on.'
    }
    const what = `${reload.changed.join(', ')} changed`
    const when = reload.after_tick
        ? 'The loop runs on the new config once the running tick ends.'
        : 'The loop runs on the new config now.'
    const count = reload.restart.length
    const restart =
        count === 0 ? '' : ` ${reload.restart.join(', ')} take${count === 1 ? 's' : ''} effect on a restart.`
    return `${what}. ${when}${restart}`
}

/**
 * What a review request did, as `canopy start URL --review` says it: new, or already open, its notes replaced when
 * `noted`, the request having given some, the personas it is reviewed in when `chose`, the request having named
 * some, or when an open request kept its own, and the model its reviews run on when `onModel`, the request having
 * named one.
 */
export function reviewRequestedText(
    url: string,
    requested: ReviewRequested,
    noted = false,
    chose = false,
    onModel = false,
): string {
    // A request that has personas keeps them when none are chosen: say which, lest the form's default read as theirs.
    const kept = requested.already && requested.request.personas.length > 0
    const written = chose || kept ? ` ${reviewPersonasText(requested.request.personas)}` : ''
    const model = requested.request.model
    const on = onModel && model !== null ? ` Its reviews run on ${model}.` : ''
    if (requested.already) {
        return `${url} was already requested for review.${noted ? ' Its notes are replaced.' : ''}${written}${on}`
    }
    return `${url} is requested for review. The next tick reviews its head, once.${written}${on}`
}

/** The personas a review request is reviewed in, as `canopy start URL --review --persona NAME` says it. */
export function reviewPersonasText(names: readonly string[]): string {
    if (names.length === 1) {
        return `Its review is written in ${names[0]}.`
    }
    return `It is reviewed once in each of ${names.join(', ')}, side by side.`
}

/** What stopping a review request did, as `canopy stop URL` says it, and a review of the PR still running. */
export function reviewStoppedText(url: string, stopped: ReviewRequestStopped): string {
    const head = `${url}'s review request is stopped; nothing reviews it now.`
    if (stopped.running_review === null) {
        return head
    }
    return `${head} Review run ${stopped.running_review} of it is still running and will finish.`
}

/** What the operator's word on a plan did, as `canopy plan` says it (canopy/cli/plans.py). */
export function planText(key: string, changed: PlanChanged): string {
    if (changed.action === 'approve') {
        return `Plan ${changed.plan} of ${key} is approved as its file stands now. The next tick can implement it.`
    }
    const superseded =
        changed.superseded === null ? '' : `Plan ${changed.superseded} of ${key} is superseded; its file stays. `
    if (changed.action === 'skip') {
        const state = changed.already ? 'was already skipped' : 'is skipped'
        return `${superseded}${key}'s plan ${state}: its implement goes ahead without one.`
    }
    if (changed.already) {
        return `${key} already waits on a plan: the next tick dispatches a planner if none is running.`
    }
    return (
        `${superseded}${key} is planned first: the next tick dispatches a planner, and nothing is ` +
        'implemented until you approve its plan.'
    )
}

/**
 * What an approval of a feedback plan did, as `canopy plan KEY --approve` says it (canopy/cli/plans.py): whole, or
 * for some of its items, each named by its number and observed id, and the message on the ticket naming them.
 */
export function feedbackPlanApprovedText(approved: FeedbackPlanApproved): string {
    const { plan, ticket_key: key, addressed, left } = approved
    const total = addressed.length + left.length
    const once = `The next tick can resume ${key} on it, once.`
    let head =
        `Feedback plan ${plan} of ${key}, covering ${total} item${total === 1 ? '' : 's'}, is approved whole as its ` +
        `file stands now. ${once}`
    if (left.length > 0) {
        head =
            `Feedback plan ${plan} of ${key} is approved as its file stands now, for ${addressed.length} of its ` +
            `${total} items: ${itemNames(addressed)}. ${once} Left out, for the next plan: ${itemNames(left)}.`
    }
    return approved.message === null ? head : `${head} Message ${approved.message} on ${key} names the items.`
}

/**
 * A feedback plan's items as canopy names them wherever it mentions them (canopy/core/prompts.py `item_names`): by
 * number and observed id, never by their text.
 */
export function itemNames(items: readonly { number: number; item_id: number }[]): string {
    const words = items.map((i) => `${i.number} (id ${i.item_id})`)
    const [first, second] = words
    if (words.length === 1 && first !== undefined) {
        return `item ${first}`
    }
    if (words.length === 2 && first !== undefined && second !== undefined) {
        return `items ${first} and ${second}`
    }
    return `items ${words.slice(0, -1).join(', ')}, and ${words.at(-1) ?? ''}`
}

/**
 * What a promote made, as `canopy memory promote` says it (canopy/cli/memory.py): the lesson and its review date, the
 * lesson it replaces, and whether runs read it now or it is recorded and served to none.
 */
export function promotedText(promoted: MemoryPromoted): string {
    const { lesson, source } = promoted
    const kind = source.scope === 'proposal' ? 'Proposal' : 'Note'
    const where = lesson.repo === null ? '' : ` for ${lesson.repo}`
    const due = dueText(lesson)
    const head = `${kind} ${source.id} is lesson ${lesson.id} (\`${lesson.key}\`)${where}${due}.`
    const replaces =
        promoted.superseded === null ? '' : ` It replaces lesson ${promoted.superseded}, under the same key.`
    const served = promoted.served
        ? ' Every run dispatched from now on reads it.'
        : ' It is recorded, not served: memory.proposals is record, so no run reads it until it is use.'
    return `${head}${replaces}${promoted.private ? ` ${PRIVATE_WORDS}` : ''}${served}`
}

/**
 * The warning `canopy memory promote` gives for a lesson whose text is still a private ticket's run's own words, said
 * after the promote and by the form before it.
 */
export const PRIVATE_WORDS =
    "Warning: its text is from a private ticket's run, and may hold what you kept off the tracker. If it is not fit " +
    'for every worker, edit it into your own words, then forget the version the edit replaces: its history keeps ' +
    'the old words.'

/**
 * What an edit made, as `canopy memory edit` says it: the lesson's new version and its review date, that the old one
 * stays in its history, and whether runs read it now or it is recorded and served to none.
 */
export function editedText(edited: MemoryEdited): string {
    const { lesson, replaced } = edited
    const where = lesson.repo === null ? '' : ` for ${lesson.repo}`
    const due = dueText(lesson)
    const head =
        `Lesson ${replaced.id} is edited into lesson ${lesson.id} (\`${lesson.key}\`)${where}, version ` +
        `${lesson.version}${due}. Lesson ${replaced.id} stays in its history.`
    const served = edited.served
        ? ' Every run dispatched from now on reads the new version.'
        : ' It is recorded, not served: memory.proposals is record, so no run reads it until it is use.'
    return `${head}${served}`
}

// When a lesson a promote or an edit made is due for review, as `canopy memory` says it after the lesson's name; a
// pinned one never is.
function dueText(lesson: MemoryEntry): string {
    if (lesson.pinned_at !== null) {
        return ', pinned, never due for review'
    }
    return lesson.review_at === null ? '' : `, due for review at ${localTime(lesson.review_at, currentClock())}`
}

/** What a reject did, as `canopy memory reject` says it. */
export function rejectedText(id: number): string {
    return `Proposal ${id} is rejected.`
}

/**
 * What a renew did, as `canopy memory renew` says it: when the lesson is next due for review, or for a pinned one,
 * which never is, that a run's report it is wrong is cleared.
 */
export function renewedText(renewed: MemoryRenewed): string {
    if (renewed.review_at === null) {
        return `Lesson ${renewed.id} is renewed: any report that it is wrong is cleared. Pinned, it is never due.`
    }
    return `Lesson ${renewed.id} is renewed: due for review at ${localTime(renewed.review_at, currentClock())}.`
}

/** What a pin did, as `canopy memory pin` says it. */
export function pinnedText(pinned: MemoryPinned): string {
    return `Lesson ${pinned.id} is pinned: never due for review, and served before every lesson not pinned.`
}

/** What an unpin did, as `canopy memory unpin` says it: when the lesson is next due for review. */
export function unpinnedText(unpinned: MemoryUnpinned): string {
    return `Lesson ${unpinned.id} is unpinned: due for review at ${localTime(unpinned.review_at, currentClock())}.`
}

/**
 * What a forget deleted, as `canopy memory forget` says it, and that the text may stay in the journal's log a while
 * when a reader held it open.
 */
export function memoryForgottenText(forgot: MemoryForgotten): string {
    const head = `Memory ${forgot.id} (${forgot.scope} \`${forgot.key}\`) is forgotten: its text is deleted.`
    if (forgot.checkpointed) {
        return head
    }
    return (
        `${head} A reader held the journal's write-ahead log open, so the deleted text may stay in the log until ` +
        "SQLite's next checkpoint."
    )
}

/** What an upload did, as `canopy attach` says it (canopy/cli/attachments.py): the name, its size, and the subject. */
export function attachedText(ref: string, attached: Attached): string {
    const { name, size } = attached.attachment
    return `Attached ${name} (${size} bytes) to ${ref}; its next run reads it.`
}

/** What a removal did, as `canopy detach` says it. */
export function detachedText(ref: string, detached: Detached): string {
    return `Removed ${detached.name} from ${ref}.`
}
