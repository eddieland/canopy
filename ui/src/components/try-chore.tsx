import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FlaskConical } from 'lucide-react'
import { useState } from 'react'

import { refreshChore, tryChore } from '@/api/mutations'
import type { ChoreSummary } from '@/api/types'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { triedText } from '@/lib/outcomes'

/**
 * `canopy chore try` on one chore (DESIGN §19, §22): it runs now, recorded, whatever its schedule and capacity, and the
 * run goes on in the background, its row in Recent runs. A chore with a run running cannot be tried, as the server
 * refuses `running`, so the button waits for it.
 */
export function TryChore({ chore }: { chore: ChoreSummary }) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const attempt = useMutation({
        mutationFn: () => tryChore(chore.name),
        onSuccess: (tried) => {
            setSaid(triedText(tried))
            void refreshChore(client, chore.name)
        },
    })
    const running = chore.running !== null
    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex flex-wrap items-center gap-2">
                <Button
                    variant="outline"
                    onClick={() => attempt.mutate()}
                    disabled={attempt.isPending || running}
                    title={running ? 'A run of it is running; try it once that ends' : `canopy chore try ${chore.name}`}
                    data-testid="try-chore"
                >
                    <FlaskConical />
                    Try now
                </Button>
            </div>
            <Notice error={attempt.error}>
                {said ?? 'Runs it now, whatever its schedule, as canopy chore try does, and records the run.'}
            </Notice>
        </div>
    )
}
