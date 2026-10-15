import { GitHubChip } from '@/components/github-chip'
import { onGitHub, splitLinks } from '@/lib/links'

/**
 * Untrusted journal text with its http and https URLs as links (D113). Every piece is React text, which escapes it;
 * a link's text is its URL as written, and it opens in a new tab with no referrer. With `chips`, as a conversation and
 * a chore's finding have it, a github.com URL is a `GitHubChip` instead, named for what it links to. Never inside
 * another link.
 */
export function LinkedText({ text, chips = false }: { text: string; chips?: boolean }) {
    return splitLinks(text).map((piece, i) => {
        if (piece.href === undefined) {
            return piece.text
        }
        if (chips && onGitHub(piece.href)) {
            return <GitHubChip key={i} href={piece.href} />
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
