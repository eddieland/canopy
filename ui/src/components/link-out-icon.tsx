import { ExternalLink } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { onGitHub } from '@/lib/links'
import { cn } from '@/lib/utils'

// GitHub's mark (Octicons' `mark-github`, MIT), in pieces only to keep the lines short.
const GITHUB_MARK = [
    'M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2',
    '0-.75-.25-1.23-.54-1.48 1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0',
    '0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16',
    '1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 3.95-.23.2-.44.55-.51',
    '1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68',
    '1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z',
].join(' ')

/**
 * The one icon a link out wears: GitHub's mark when it goes to github.com, so a PR or branch reads as GitHub's at a
 * glance, and `icon` anywhere else, `ExternalLink` unless the link says what it opens.
 */
export function LinkOutIcon({
    href,
    icon: Icon = ExternalLink,
    className,
}: {
    /** Where the link goes. */
    href: string
    /** The icon for a link off GitHub. */
    icon?: LucideIcon
    /** Classes for the icon, over its default `size-3`. */
    className?: string
}) {
    if (!onGitHub(href)) {
        return <Icon aria-hidden className={cn('size-3', className)} />
    }
    // Lucide no longer ships brand icons; the mark is bundled, so nothing loads from GitHub.
    return (
        <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden className={cn('size-3', className)}>
            <path d={GITHUB_MARK} />
        </svg>
    )
}

/**
 * The icon that follows a name linking in, opening the same thing outside canopy in a new tab: a PR on GitHub, a
 * ticket in the tracker. It wears `LinkOutIcon`, and `label` names it for a screen reader and on hover.
 */
export function LinkOut({ href, label }: { href: string; label: string }) {
    return (
        <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            title={label}
            aria-label={label}
            className="inline-flex shrink-0 items-center rounded-sm p-0.5 text-accent hover:bg-surface-raised"
        >
            <LinkOutIcon href={href} />
        </a>
    )
}
