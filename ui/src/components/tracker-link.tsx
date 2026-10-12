import { ExternalLink } from 'lucide-react'

import { cn } from '@/lib/utils'

/** A link out to a ticket's page in the tracker, shown as its address without the scheme. */
export function TrackerLink({ href, className }: { href: string; className?: string }) {
    return (
        <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className={cn('inline-flex items-center gap-1 text-accent underline-offset-4 hover:underline', className)}
        >
            {href.replace(/^https:\/\//, '')}
            <ExternalLink className="size-3" />
        </a>
    )
}
