import { splitLinks } from '@/lib/links'

/**
 * Untrusted journal text with its http and https URLs as links (D112). Every piece is React text, which escapes it;
 * a link's text is its URL as written, and it opens in a new tab with no referrer. Never inside another link.
 */
export function LinkedText({ text }: { text: string }) {
    return splitLinks(text).map((piece, i) =>
        piece.href === undefined ? (
            piece.text
        ) : (
            <a
                key={i}
                href={piece.href}
                target="_blank"
                rel="noreferrer noopener"
                className="text-accent underline underline-offset-4 hover:decoration-2"
            >
                {piece.text}
            </a>
        ),
    )
}
