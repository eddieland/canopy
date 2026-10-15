import { PullRequestLink } from '@/components/pull-request-link'
import { splitLinks } from '@/lib/links'
import { isPullRequest } from '@/lib/pull-request-label'

/**
 * Untrusted journal text with its http and https URLs as links (D113). Every piece is React text, which escapes it;
 * a link's text is its URL as written, and it opens in a new tab with no referrer. With `pullRequests`, as a
 * conversation and a chore's finding have it, a GitHub PR's address is named as the PR is anywhere: a
 * `PullRequestLink`, as `InlineCode` does for the harness's lines. Never inside another link.
 */
export function LinkedText({ text, pullRequests = false }: { text: string; pullRequests?: boolean }) {
    return splitLinks(text).map((piece, i) => {
        if (piece.href === undefined) {
            return piece.text
        }
        if (pullRequests && isPullRequest(piece.href)) {
            return <PullRequestLink key={i} url={piece.href} />
        }
        return (
            <a
                key={i}
                href={piece.href}
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent underline underline-offset-4 hover:decoration-2"
            >
                {piece.text}
            </a>
        )
    })
}
