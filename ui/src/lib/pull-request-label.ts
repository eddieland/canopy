import { addressOf } from '@/lib/links'

// A GitHub PR's address: its owner, repository, and number, with nothing after but an optional slash.
const GITHUB_PR = /^https:\/\/github\.com\/([^/?#]+)\/([^/?#]+)\/pull\/(\d+)\/?$/u

/**
 * A PR's name, wherever the UI names one (`PullRequestLink`): `org/repo#123` for a GitHub PR, as GitHub writes a
 * reference, and any other URL as written without `https://`. The link's title keeps the whole URL.
 */
export function pullRequestLabel(url: string): string {
    const match = GITHUB_PR.exec(url)
    if (match === null) {
        return addressOf(url)
    }
    const [, owner, repo, number] = match
    return `${owner}/${repo}#${number}`
}

/** Whether a URL is a GitHub PR's own address, which `pullRequestLabel` names `org/repo#123`. */
export function isPullRequest(url: string): boolean {
    return GITHUB_PR.test(url)
}
