import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'

import { dismissFinding, refreshFindings } from '@/api/mutations'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { dismissedText } from '@/lib/outcomes'

/**
 * `canopy dismiss` on one of a chore's open findings (DESIGN §19): `button` dismisses it, keeping it off the attention
 * list until the chore stops reporting it, or lists it again; `notice` says what the last click did, or why it was
 * refused, and is nothing before one. The button sits in the finding's head line, the notice under the finding.
 */
export function useDismissFinding(chore: string, finding: string, dismissed: boolean) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const dismiss = useMutation({
        mutationFn: (undo: boolean) => dismissFinding(chore, finding, undo),
        onSuccess: (result) => {
            setSaid(dismissedText(result))
            void refreshFindings(client, chore)
        },
    })
    const button = (
        <Button
            variant="ghost"
            size="xs"
            // Negative margins keep the head line as tall as it is without the button.
            className="-my-1 font-mono font-normal text-muted-foreground"
            title={
                dismissed
                    ? 'List it on the attention list again'
                    : 'Keep it off the attention list until the chore stops reporting it'
            }
            onClick={() => dismiss.mutate(dismissed)}
            disabled={dismiss.isPending}
            data-testid={`${dismissed ? 'undismiss' : 'dismiss'}-${finding}`}
        >
            {dismissed ? <Eye /> : <EyeOff />}
            {dismissed ? 'list again' : 'dismiss'}
        </Button>
    )
    const notice = <Notice error={dismiss.error}>{said}</Notice>
    return { button, notice }
}
