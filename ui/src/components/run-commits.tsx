import type { RunCommit, RunKick } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { Chip } from '@/components/status'
import { shortSha } from '@/lib/reviews'
import { commitMarks, commitUrl, KICKED, kickText } from '@/lib/run-changes'
import { cn } from '@/lib/utils'

/**
 * The commits in a run's range in one repository (DESIGN §45), oldest first, as the run's end logged them: each one's
 * short commit, opening its page on GitHub through `prUrl` when the commit is on origin, its subject, the worker's text
 * shown as text, and canopy's marks on it as chips (`commitMarks`). `leftOut` names the older commits the run did
 * not record, and `kick` the copy canopy pushed after the run, which a PR's runs list shows as the branch's history.
 * Nothing when it has neither commits nor a kick.
 */
export function RunCommits({
    commits,
    prUrl,
    onOrigin,
    leftOut = '',
    kick = null,
    className,
}: {
    /** The commits, oldest first. */
    commits: readonly RunCommit[]
    /** The PR the commits went to, whose commit pages they link to. */
    prUrl: string | null | undefined
    /** Whether the commits are on origin, so their pages exist: not for a slot the run left unpushed. */
    onOrigin: boolean
    /** What the list says of the older commits it does not hold; empty for none. */
    leftOut?: string
    /** The kick canopy pushed after the run. */
    kick?: RunKick | null
    /** Classes for the list. */
    className?: string
}) {
    if (commits.length === 0 && kick === null) {
        return null
    }
    return (
        <ul className={cn('flex flex-col gap-0.5 font-mono text-xs', className)} data-testid="run-commits">
            {leftOut !== '' && <li className="text-muted-foreground">{leftOut}</li>}
            {commits.map((commit) => (
                <CommitRow key={commit.sha} commit={commit} url={onOrigin ? commitUrl(prUrl, commit.sha) : null} />
            ))}
            {kick !== null && (
                <li className="flex items-center gap-2 text-muted-foreground" title={KICKED} data-testid="run-kick">
                    <span>{kickText(kick)}</span>
                    <Age at={kick.kicked_at} variant="ago" />
                </li>
            )}
        </ul>
    )
}

/** One commit: its short id, linked out when it has a page, its subject, and canopy's marks on it. */
function CommitRow({ commit, url }: { commit: RunCommit; url: string | null }) {
    const sha = shortSha(commit.sha)
    return (
        <li className="flex min-w-0 items-center gap-2" data-testid="run-commit">
            {url === null ? (
                <span className="shrink-0 text-muted-foreground" title={commit.sha}>
                    {sha}
                </span>
            ) : (
                <a
                    href={url}
                    target="_blank"
                    rel="noreferrer noopener"
                    title={`${commit.sha} on GitHub`}
                    className="shrink-0 text-accent underline-offset-4 hover:underline"
                >
                    {sha}
                </a>
            )}
            {/* The worker's text, as text (D113), cut to the row with the whole on its hover. */}
            <span className="min-w-0 truncate" title={commit.subject}>
                <LinkedText text={commit.subject} />
            </span>
            {commitMarks(commit).map((mark) => (
                <Chip key={mark.word} word={mark.word} meaning={mark.meaning} />
            ))}
        </li>
    )
}
