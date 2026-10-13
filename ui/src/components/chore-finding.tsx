import { ExternalLink } from 'lucide-react'

import type { ChoreFinding, ChoreRunFinding } from '@/api/types'
import { Age } from '@/components/age'
import { LinkedText } from '@/components/linked-text'
import { Chip } from '@/components/status'
import { cn } from '@/lib/utils'

/**
 * A chore's finding: its id, its title and link, and below them its detail; an open finding also says how long it has
 * been open. All of it is the agent's: text, never markup.
 */
export function ChoreFindingRow({ finding }: { finding: ChoreFinding | ChoreRunFinding }) {
    return (
        <li className="flex flex-col gap-1 px-3 py-2.5" data-testid={`finding-${finding.id}`}>
            <div className="flex items-center gap-3">
                <Chip>{finding.id}</Chip>
                <span className="min-w-0 truncate text-sm">{finding.title}</span>
                {'since' in finding && <Age at={finding.since} className="ml-auto" />}
            </div>
            {finding.detail && (
                <p className="text-sm break-words whitespace-pre-wrap text-muted-foreground">
                    <LinkedText text={finding.detail} />
                </p>
            )}
            {finding.link && (
                <a
                    href={finding.link}
                    target="_blank"
                    rel="noreferrer noopener"
                    className={cn(
                        'inline-flex items-center gap-1 self-start font-mono text-xs text-accent underline-offset-4',
                        'hover:underline',
                    )}
                >
                    {finding.link.replace(/^https:\/\//, '')}
                    <ExternalLink className="size-3" />
                </a>
            )}
        </li>
    )
}
