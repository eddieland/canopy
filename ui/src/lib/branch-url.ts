/** Where a repository's `branch_url` puts a branch's name. The server checks it holds this exactly once. */
const BRANCH = '{branch}'

/**
 * A branch's page on its repository's host, from the repository's `branch_url`, or undefined when that is unset. Each
 * of the name's `/`-separated parts is encoded, so `agent/ABC-1` stays a path, as GitHub's `/tree/` URLs expect, and
 * nothing in a part can leave its place in the URL.
 */
export function branchUrl(template: string | null | undefined, branch: string): string | undefined {
    if (!template?.includes(BRANCH)) {
        return undefined
    }
    return template.replace(
        BRANCH,
        branch
            .split('/')
            .map((part) => encodeURIComponent(part))
            .join('/'),
    )
}
