import type { QueryClient } from '@tanstack/react-query'

import { api, unwrap } from './client'
import { keys } from './queries'
import type {
    ChoreTried,
    ConfigReload,
    Dismissed,
    Draft,
    DraftsSent,
    Forgot,
    Granted,
    Limit,
    LoopState,
    LessonEditRequest,
    MemoryEdited,
    MemoryForgotten,
    MemoryPromoted,
    MemoryRejected,
    MemoryRenewed,
    NoticeChanged,
    PauseChanged,
    PlanChanged,
    PlanSaved,
    PlanThreadView,
    Reaction,
    Replied,
    ReviewDismissed,
    ReviewRequested,
    ReviewRequestStopped,
    ReviewSent,
    Session,
    PromoteRequest,
    Started,
    Stopped,
    TickAsked,
} from './types'

/**
 * The operator's actions: sign in and out, the CLI's verbs on a ticket, a note to a chore, trying a chore, dismissing
 * a finding, sending a review's findings to a worker, granting a run past a limit, asking for a PR to be reviewed,
 * pausing the loop, asking it for a tick now, a notice to workers, the verbs on agent memory, and those on a run's
 * drafts. Each goes through the same function on the server as `canopy start`, `stop`, `reply`, `forget`,
 * `chore try`, `dismiss`, `send`, `grant`, `start URL --review`, `stop URL`, `pause`, `resume`, `notice`,
 * `memory promote`, `reject`, `renew`, `edit`, and `forget`, and `draft edit`, `drop`, and `send`, or as `t` at the
 * loop's terminal, with the same guards; a refusal is an ApiError naming its guard.
 */

/** Signs this browser in with the listener secret. The secret is sent here once and never kept in the page. */
export async function signIn(secret: string): Promise<Session> {
    return unwrap(await api.POST('/api/session', { body: { secret } }))
}

/** Signs this browser out: the server drops its session cookie. */
export async function signOut(): Promise<Session> {
    return unwrap(await api.DELETE('/api/session'))
}

/** `canopy start`: the ticket is started privately, and the next tick picks it up. */
export async function startTicket(key: string): Promise<Started> {
    return unwrap(await api.POST('/api/tickets/{key}/start', { params: { path: { key } } }))
}

/** `canopy stop`, or `canopy stop --now` with `now`, which also ends the run working it. */
export async function stopTicket(key: string, now: boolean): Promise<Stopped> {
    return unwrap(await api.POST('/api/tickets/{key}/stop', { params: { path: { key } }, body: { now } }))
}

/** `canopy forget`, with the key as the operator typed it: the server refuses `not_confirmed` unless it matches. */
export async function forgetTicket(key: string, confirm: string): Promise<Forgot> {
    return unwrap(await api.POST('/api/tickets/{key}/forget', { params: { path: { key } }, body: { confirm } }))
}

/**
 * `canopy grant` for one more run past `limit`: `canopy grant KEY KIND --repo NAME` for a ticket's unit, or
 * `canopy grant URL review` for a PR's reviews. Every run still counts; the next tick decides whether to use it.
 */
export async function grantLimit(ticketKey: string | null, limit: Limit): Promise<Granted> {
    if (limit.kind === 'review') {
        if (limit.pr_url === null) {
            throw new Error('a review limit names its PR')
        }
        return unwrap(await api.POST('/api/pull-request/grants', { params: { query: { url: limit.pr_url } } }))
    }
    if (ticketKey === null) {
        throw new Error("a unit's limit names its ticket")
    }
    return unwrap(
        await api.POST('/api/tickets/{key}/grants', {
            params: { path: { key: ticketKey } },
            body: { kind: limit.kind, repo: limit.repo },
        }),
    )
}

/**
 * `canopy start URL --review`: canopy reviews a PR it does not own, once, at its head. Nothing is posted on the PR;
 * the next tick reviews it.
 */
export async function requestReview(url: string): Promise<ReviewRequested> {
    return unwrap(await api.POST('/api/pull-request/start', { params: { query: { url } } }))
}

/** `canopy stop URL`: the PR's review request ends, and a review of it already running finishes. */
export async function stopReview(url: string): Promise<ReviewRequestStopped> {
    return unwrap(await api.POST('/api/pull-request/stop', { params: { query: { url } } }))
}

/** `canopy reply`: a message on the ticket for the next tick to read. `submission` makes a resend a no-op. */
export async function replyTicket(key: string, body: string, submission: string): Promise<Replied> {
    return unwrap(
        await api.POST('/api/tickets/{key}/replies', { params: { path: { key } }, body: { body, submission } }),
    )
}

/**
 * `canopy plan KEY --approve`, `canopy plan KEY`, or `canopy plan KEY --skip`: approve the newest plan as its file
 * stands, ask for a new one, or skip the plan (DESIGN §25).
 */
export async function decidePlan(key: string, action: PlanChanged['action']): Promise<PlanChanged> {
    return unwrap(await api.POST('/api/tickets/{key}/plan', { params: { path: { key } }, body: { action } }))
}

/**
 * Write the editor's Markdown over the plan's file, as the operator's own editor would. `readSha256` is the file's hash
 * as the editor read it: a file changed since is refused (`bad_plan`), never overwritten unseen.
 */
export async function savePlan(key: string, plan: number, markdown: string, readSha256: string): Promise<PlanSaved> {
    return unwrap(
        await api.PUT('/api/tickets/{key}/plans/{plan_id}/file', {
            params: { path: { key, plan_id: plan } },
            body: { markdown, read_sha256: readSha256 },
        }),
    )
}

/** A comment on a passage of the ticket's plan: a new open thread, anchored by the passage's words. */
export async function commentPlan(
    key: string,
    anchor: { quote: string; prefix: string; suffix: string },
    body: string,
): Promise<PlanThreadView> {
    return unwrap(
        await api.POST('/api/tickets/{key}/plan-threads', { params: { path: { key } }, body: { ...anchor, body } }),
    )
}

/** A reply in one of the ticket's plan comment threads. */
export async function replyPlanThread(key: string, thread: number, body: string): Promise<PlanThreadView> {
    return unwrap(
        await api.POST('/api/tickets/{key}/plan-threads/{thread_id}/replies', {
            params: { path: { key, thread_id: thread } },
            body: { body },
        }),
    )
}

/** A change to one of the ticket's plan comment threads: its words, a reply's, whether resolved, or its passage. */
export async function changePlanThread(
    key: string,
    thread: number,
    change: {
        body?: string
        reply?: number
        resolved?: boolean
        anchor?: { quote: string; prefix: string; suffix: string }
    },
): Promise<PlanThreadView> {
    return unwrap(
        await api.PATCH('/api/tickets/{key}/plan-threads/{thread_id}', {
            params: { path: { key, thread_id: thread } },
            body: change,
        }),
    )
}

/** Delete one of the ticket's plan comment threads, with its replies. */
export async function deletePlanThread(key: string, thread: number): Promise<void> {
    unwrap(
        await api.DELETE('/api/tickets/{key}/plan-threads/{thread_id}', {
            params: { path: { key, thread_id: thread } },
        }),
    )
}

/** A note to a chore, as `canopy reply chore:NAME`: its next runs read it (DESIGN §19). */
export async function replyChore(name: string, body: string, submission: string): Promise<Replied> {
    return unwrap(
        await api.POST('/api/chores/{name}/replies', { params: { path: { name } }, body: { body, submission } }),
    )
}

/**
 * `canopy chore try NAME`: the chore runs now, recorded, whatever its schedule; its run goes on in the background.
 * Refused `running` while a run of it is running.
 */
export async function tryChore(name: string): Promise<ChoreTried> {
    return unwrap(await api.POST('/api/chores/{name}/tries', { params: { path: { name } } }))
}

/**
 * `canopy dismiss chore:NAME FINDING`: the finding is off the attention list until the chore stops reporting it. With
 * `undo`, `--undo`: it is listed again.
 */
export async function dismissFinding(name: string, finding: string, undo: boolean): Promise<Dismissed> {
    return unwrap(
        await api.POST('/api/chores/{name}/dismissals', { params: { path: { name } }, body: { finding, undo } }),
    )
}

/**
 * `canopy dismiss review:ID N`: no worker or tick acts on the review's finding number `finding`. With `undo`,
 * `--undo`.
 */
export async function dismissReviewFinding(run: number, finding: number, undo: boolean): Promise<ReviewDismissed> {
    return unwrap(
        await api.POST('/api/reviews/{run_id}/dismissals', {
            params: { path: { run_id: run } },
            body: { finding, undo },
        }),
    )
}

/**
 * `canopy send review:ID N...`: a reply on the review's ticket naming `findings` by number, which the next tick reads
 * as the operator's go-ahead on them. Idempotent on `submission`, drawn when the findings were picked, as a reply is.
 */
export async function sendReviewFindings(run: number, findings: number[], submission: string): Promise<ReviewSent> {
    return unwrap(
        await api.POST('/api/reviews/{run_id}/sends', {
            params: { path: { run_id: run } },
            body: { findings, submission },
        }),
    )
}

/**
 * `canopy draft edit run:ID N --text TEXT --react NAME`: the operator's words for the run's draft number `number`, its
 * text and its reaction (null for none, which `--no-react` sets), kept as a new version beside the run's own, held to
 * the bounds a draft is.
 */
export async function editDraft(run: number, number: number, text: string, reaction: Reaction | null): Promise<Draft> {
    return unwrap(
        await api.POST('/api/runs/{run_id}/drafts/{number}/edit', {
            params: { path: { run_id: run, number } },
            body: { text, reaction },
        }),
    )
}

/** `canopy draft drop run:ID N`: nobody sends the draft. With `undo`, `--undo`: it waits on the operator again. */
export async function dropDraft(run: number, number: number, undo: boolean): Promise<Draft> {
    return unwrap(
        await api.POST('/api/runs/{run_id}/drafts/{number}/drop', {
            params: { path: { run_id: run, number } },
            body: { undo },
        }),
    )
}

/**
 * `canopy draft send`: the drafts as the operator's own words, each named by the hash of the text the page showed, so
 * what posts is what was read. One PR's go as one comment review; any refusal posts nothing.
 */
export async function sendDrafts(drafts: Pick<Draft, 'run' | 'number' | 'hash'>[]): Promise<DraftsSent> {
    return unwrap(
        await api.POST('/api/drafts/send', {
            body: { drafts: drafts.map(({ run, number, hash }) => ({ run, number, hash })) },
        }),
    )
}

/** `canopy pause`: the loop starts no tick until it is resumed. A tick already running finishes. */
export async function pauseLoop(): Promise<PauseChanged> {
    return unwrap(await api.POST('/api/loop/pause'))
}

/** `canopy resume`: the loop ticks when its wait runs out, at once if it already has. */
export async function resumeLoop(): Promise<PauseChanged> {
    return unwrap(await api.POST('/api/loop/resume'))
}

/**
 * `canopy notice TEXT --for DURATION`: every run dispatched until it lapses hears it (DESIGN §8). It replaces the
 * notice in force. A blank text is refused (`empty`), and one over 1024 bytes (`too_long`).
 */
export async function setNotice(text: string, minutes: number): Promise<NoticeChanged> {
    return unwrap(await api.POST('/api/loop/notice', { body: { text, minutes } }))
}

/** `canopy notice --clear`: runs dispatched from now on hear no notice. */
export async function clearNotice(): Promise<NoticeChanged> {
    return unwrap(await api.POST('/api/loop/notice/clear'))
}

/**
 * Ask the loop to read its config files again, as SIGHUP does (DESIGN §6). A file that does not load is refused
 * (`config_invalid`) and the loop keeps the config it has.
 */
export async function reloadConfig(): Promise<ConfigReload> {
    return unwrap(await api.POST('/api/loop/reload'))
}

/**
 * Ask the loop for a tick now, as `t` at its terminal does (DESIGN §6): its wait ends at once, paused or not, and a
 * pause stays. Asked for during a tick, it starts when that one ends.
 */
export async function tickNow(): Promise<TickAsked> {
    return unwrap(await api.POST('/api/loop/tick'))
}

/**
 * `canopy memory promote ID [--text TEXT] [--repo NAME]`: a pending proposal, or a ticket's note, as a lesson in the
 * operator's name. A `text` of null keeps the source's own, and a `repo` of null a proposal's, or every one for a note.
 */
export async function promoteMemory(id: number, request: PromoteRequest): Promise<MemoryPromoted> {
    return unwrap(
        await api.POST('/api/memory/{memory_id}/promote', { params: { path: { memory_id: id } }, body: request }),
    )
}

/** `canopy memory reject ID`: the proposal ends, and no lesson is made of it. */
export async function rejectMemory(id: number): Promise<MemoryRejected> {
    return unwrap(await api.POST('/api/memory/{memory_id}/reject', { params: { path: { memory_id: id } } }))
}

/** `canopy memory renew ID`: the lesson comes up for review later, and a run's report that it is wrong is cleared. */
export async function renewMemory(id: number): Promise<MemoryRenewed> {
    return unwrap(await api.POST('/api/memory/{memory_id}/renew', { params: { path: { memory_id: id } } }))
}

/**
 * `canopy memory edit ID [--text TEXT] [--repo NAME | --every-repo]`: a new version of a lesson in force, the old one
 * kept as its history. A `text` of null keeps the lesson's words, and a `repo` of null its repository, unless
 * `every_repo`.
 */
export async function editMemory(id: number, request: LessonEditRequest): Promise<MemoryEdited> {
    return unwrap(
        await api.POST('/api/memory/{memory_id}/edit', { params: { path: { memory_id: id } }, body: request }),
    )
}

/** `canopy memory forget ID`, with the memory's ref as typed: refused `not_confirmed` unless it matches. */
export async function forgetMemory(id: number, confirm: string): Promise<MemoryForgotten> {
    return unwrap(
        await api.POST('/api/memory/{memory_id}/forget', { params: { path: { memory_id: id } }, body: { confirm } }),
    )
}

/**
 * After a verb on memory: read every tier's memory and every ticket's notes again now, rather than wait for a tick. The
 * attention list stays as the last tick left it: an item about memory leaves at the next tick, as an answered one does.
 */
export function refreshMemory(client: QueryClient): Promise<void> {
    const ticket = keys.ticketMemory('')
    return client.invalidateQueries({
        predicate: ({ queryKey }) =>
            queryKey[0] === keys.memory[0] || (queryKey[0] === ticket[0] && queryKey[2] === ticket[2]),
    })
}

/** After a pause, a resume, or a notice set or cleared: show the state it left now, rather than wait for the stream. */
export function showLoop(client: QueryClient, loop: LoopState): void {
    client.setQueryData(keys.loop, loop)
}

/** After a note to a chore or a try: read it again now, rather than wait for the stream. */
export function refreshChore(client: QueryClient, name: string): Promise<void> {
    return client.invalidateQueries({ queryKey: keys.chore(name) })
}

/** After a dismissal: read the chore and the attention list again now, rather than wait for the stream. */
export async function refreshFindings(client: QueryClient, name: string): Promise<void> {
    await Promise.all([
        client.invalidateQueries({ queryKey: keys.chore(name) }),
        client.invalidateQueries({ queryKey: keys.attention }),
    ])
}

/** After a dismissal of a review's finding: read the review again now. */
export function refreshReview(client: QueryClient, run: number): Promise<void> {
    return client.invalidateQueries({ queryKey: keys.review(run) })
}

/** After a grant: read the ticket and the PR the limit is on again now; the stream sends neither for a grant. */
export async function refreshLimits(client: QueryClient, ticketKey: string | null, limit: Limit): Promise<void> {
    await Promise.all([
        ...(ticketKey === null ? [] : [client.invalidateQueries({ queryKey: keys.ticket(ticketKey) })]),
        ...(limit.pr_url === null ? [] : [client.invalidateQueries({ queryKey: keys.pullRequest(limit.pr_url) })]),
    ])
}

/** After a review request is made or stopped: read the PRs list and every PR's page again; the stream sends neither. */
export function refreshPullRequests(client: QueryClient): Promise<void> {
    return client.invalidateQueries({ queryKey: keys.pullRequests })
}

/**
 * After a verb on a PR's drafts: read its threads and the attention list again now; the stream sends neither. The
 * attention item stays until the next tick, as an answered one does.
 */
export async function refreshThreads(client: QueryClient, url: string): Promise<void> {
    await Promise.all([
        client.invalidateQueries({ queryKey: keys.pullRequestThreads(url) }),
        client.invalidateQueries({ queryKey: keys.attention }),
    ])
}

/**
 * After a verb on a ticket's own drafts: read the ticket and the attention list again now, as after a PR's drafts
 * (`refreshThreads`). The attention item stays until the next tick, as an answered one does.
 */
export async function refreshTicketDrafts(client: QueryClient, key: string): Promise<void> {
    await Promise.all([
        client.invalidateQueries({ queryKey: keys.ticket(key) }),
        client.invalidateQueries({ queryKey: keys.attention }),
    ])
}

/** After an action on a ticket: read it again now, rather than wait for the stream to say it changed. */
export function refreshTicket(client: QueryClient, key: string): Promise<void> {
    return client.invalidateQueries({ queryKey: keys.ticket(key) })
}

/** A submission id for a reply form, drawn when the form is rendered and kept until the reply is recorded. */
export function newSubmission(): string {
    return crypto.randomUUID()
}
