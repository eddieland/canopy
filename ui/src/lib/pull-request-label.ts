import { addressOf } from '@/lib/links'

// A GitHub PR's address: its owner, repository, and number, then anything a link into the PR adds after it: a tab
// (`/files`), a thread (`#discussion_r123`), or a query.
const GITHUB_PR = /^https:\/\/github\.com\/([^/?#]+)\/([^/?#]+)\/pull\/(\d+)(?:[/?#].*)?$/u
// Any host's PR address, as canopy takes one (`PR_URL_RE` in `canopy.core.conversation`): a GitHub Enterprise PR's,
// say, which the pattern above does not name.
const ANY_PR = /^https:\/\/[^\s/]+\/[^\s/]+\/[^\s/]+\/pull\/[1-9]\d{0,9}\/?$/u

/**
 * A PR's name, wherever the UI names one (`PullRequestLink`): `org/repo#123` for a GitHub PR or a link into one, such
 * as a thread, as GitHub writes a reference, and any other URL as written without `https://`. The link's title keeps
 * the whole URL.
 */
export function pullRequestLabel(url: string): string {
    const match = GITHUB_PR.exec(url)
    if (match === null) {
        return addressOf(url)
    }
    const [, owner, repo, number] = match
    return `${owner}/${repo}#${number}`
}

/** Whether a URL is a GitHub PR's address, or a link into one, which `pullRequestLabel` names `org/repo#123`. */
export function isPullRequest(url: string): boolean {
    return GITHUB_PR.test(url)
}

/**
 * A GitHub PR's own address, `https://github.com/org/repo/pull/123`, from it or any link into it, as the journal and
 * the server know the PR; null for any other URL.
 */
export function pullRequestUrl(url: string): string | null {
    const match = GITHUB_PR.exec(url)
    if (match === null) {
        return null
    }
    const [, owner, repo, number] = match
    return `https://github.com/${owner}/${repo}/pull/${number}`
}

/**
 * What the Review a PR form shows under its URL field for what is written there: the PR's name as `pullRequestLabel`
 * writes it, `org/repo#123` for a GitHub PR or a link into one, or any other host's PR address as written; null for
 * anything canopy would not take as a PR's URL, which it refuses (`bad_pr`).
 */
export function pullRequestReference(url: string): string | null {
    return GITHUB_PR.test(url) || ANY_PR.test(url) ? pullRequestLabel(url) : null
}
