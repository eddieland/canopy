import type { PullRequest, RequestedReview, ReviewSummary } from '@/api/types'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { inRepos, reposIn, reposWords } from '@/lib/repo-filter'

/**
 * The pull requests and reviews pages' filters (DESIGN.md, the PR and review filters): the repositories a PR may be in
 * (`?repo=`, `repoListOf`), and words its row holds (`?q=`). Both go over the list the server sent.
 */

/** The longest text filter kept: longer than any PR, ticket, and title a row shows. */
export const PR_QUERY_MAX = 200

/** What a PR or review list is filtered by, its page's search: each undefined when it filters nothing. */
export interface PullRequestFilter {
    /** Words each shown row holds. */
    q?: string | undefined
    /** The repositories, as `?repo=` keeps them, one of which each shown row's PR is in. */
    repo?: string | undefined
}

/** A `?q=` as the pages filter by it: a string, cut to `PR_QUERY_MAX`, else undefined when it holds no word. */
export function prQueryOf(raw: unknown): string | undefined {
    if (typeof raw !== 'string') {
        return undefined
    }
    const text = raw.slice(0, PR_QUERY_MAX)
    return text.trim() === '' ? undefined : text
}

/**
 * The repositories a list's rows are in, by name, each one to filter by: those `?repo=` chooses too, so one no row is
 * in still shows as chosen, and can be taken away.
 */
export function reposOf(rows: Iterable<{ repo: string | null }>, chosen: string | undefined): string[] {
    const repos = new Set<string>()
    for (const row of rows) {
        if (row.repo !== null) {
            repos.add(row.repo)
        }
    }
    for (const repo of reposIn(chosen)) {
        repos.add(repo)
    }
    return [...repos].toSorted()
}

/**
 * Whether the pull requests page shows a PR: it is in one of `repo`'s repositories, and its name, URL, repository,
 * ticket's key and title, or own title holds every word of `q`, in any case and anywhere in a word, so `web#88` finds
 * acme/web#88.
 */
export function pullRequestShown(
    pr: Pick<PullRequest, 'url' | 'repo' | 'ticket_key' | 'ticket_title' | 'title'>,
    filter: PullRequestFilter,
): boolean {
    const words = `${prWords(pr.url, pr.repo)} ${pr.ticket_key ?? ''} ${pr.ticket_title ?? ''} ${pr.title ?? ''}`
    return inRepos(pr.repo, filter.repo) && holdsEvery(words, filter.q)
}

/**
 * Whether the reviews page shows a review: its PR is in one of `repo`'s repositories, and its PR's name or URL,
 * repository, ticket, or commit holds every word of `q`.
 */
export function reviewShown(
    review: Pick<ReviewSummary, 'pr_url' | 'repo' | 'ticket_key' | 'sha'>,
    filter: PullRequestFilter,
): boolean {
    const words = `${prWords(review.pr_url, review.repo)} ${review.ticket_key ?? ''} ${review.sha}`
    return inRepos(review.repo, filter.repo) && holdsEvery(words, filter.q)
}

/**
 * Whether the reviews page shows a PR waiting on its review: its name or URL holds every word of `q`, and no `repo` is
 * chosen, since which repository holds it is the overseer's reading at the next tick.
 */
export function requestShown(request: Pick<RequestedReview, 'pr_url'>, filter: PullRequestFilter): boolean {
    return filter.repo === undefined && holdsEvery(prWords(request.pr_url, null), filter.q)
}

/** What a filtered list says of the filter that left nothing: ` in api or web with “retry”`. */
export function filterWords(filter: PullRequestFilter): string {
    const repo = filter.repo === undefined ? '' : ` in ${reposWords(filter.repo)}`
    const q = filter.q === undefined ? '' : ` with “${filter.q.trim()}”`
    return `${repo}${q}`
}

/** How many rows a list shows, and of how many when a filter left some out: `3 of 12`; blank until both are read. */
export function countText(shown: number | undefined, total: number | undefined, filtered: boolean): string {
    if (shown === undefined || total === undefined) {
        return ''
    }
    return filtered ? `${shown} of ${total}` : String(total)
}

function prWords(url: string, repo: string | null) {
    return `${pullRequestLabel(url)} ${url} ${repo ?? ''}`
}

function holdsEvery(text: string, query: string | undefined) {
    const haystack = text.toLowerCase()
    const words = query?.toLowerCase().trim().split(/\s+/u) ?? []
    return words.every((word) => haystack.includes(word))
}
