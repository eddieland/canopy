import { addressOf } from '@/lib/links'

// A GitHub PR's address: its owner, repository, and number, then anything a link into the PR adds after it: a tab
// (`/files`), a thread (`#discussion_r123`), or a query.
const GITHUB_PR = /^https:\/\/github\.com\/([^/?#]+)\/([^/?#]+)\/pull\/(\d+)(?:[/?#].*)?$/u

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
