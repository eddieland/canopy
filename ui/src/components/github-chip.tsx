import { LinkOutIcon } from '@/components/link-out-icon'
import { gitHubLabel } from '@/lib/links'
import { cn } from '@/lib/utils'

/**
 * A github.com URL as a chip: GitHub's mark, then what the URL names (`gitHubLabel`: `acme/web#88`, an advisory's
 * id), opening it in a new tab. The name is read from the URL alone, so the chip never names one place and opens
 * another (D113); the whole URL shows on hover. It stays inline, so in prose it wraps as the words around it do.
 */
export function GitHubChip({ href, className }: { href: string; className?: string }) {
    const label = gitHubLabel(href)
    return (
        <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            title={href}
            aria-label={`${label} on GitHub`}
            className={cn(
                'rounded-sm border px-1 py-px font-mono text-xs break-all text-accent box-decoration-clone',
                'outline-none hover:border-accent focus-visible:ring-3 focus-visible:ring-ring/50',
                className,
            )}
        >
            <LinkOutIcon href={href} className="mr-1 inline-block align-[-0.125em]" />
            {label}
        </a>
    )
}
