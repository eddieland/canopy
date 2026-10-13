import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'

import { dismissFinding, refreshFindings } from '@/api/mutations'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { dismissedText } from '@/lib/outcomes'
import { cn } from '@/lib/utils'

/**
 * `canopy dismiss` on one of a chore's open findings: Dismiss keeps it off the attention list until the chore stops
 * reporting it, and List again takes that back (DESIGN §19). The chore's runs go on reporting it either way.
 */
export function DismissFinding({
    chore,
    finding,
    dismissed,
    className,
}: {
    chore: string
    finding: string
    dismissed: boolean
    className?: string
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const dismiss = useMutation({
        mutationFn: (undo: boolean) => dismissFinding(chore, finding, undo),
        onSuccess: (result) => {
            setSaid(dismissedText(result))
            void refreshFindings(client, chore)
        },
    })
    return (
        <div className={cn('flex flex-col gap-1.5', className)}>
            <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => dismiss.mutate(dismissed)}
                disabled={dismiss.isPending}
                data-testid={`${dismissed ? 'undismiss' : 'dismiss'}-${finding}`}
            >
                {dismissed ? <Eye /> : <EyeOff />}
                {dismissed ? 'List again' : 'Dismiss'}
            </Button>
            <Notice error={dismiss.error}>{said}</Notice>
        </div>
    )
}
