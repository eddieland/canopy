import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { RotateCw } from 'lucide-react'

import { instructionsQuery } from '@/api/queries'
import { InstructionsForm } from '@/components/instructions-form'
import { Notice } from '@/components/notice'
import { PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { INSTRUCTIONS_HELP, instructionsLine } from '@/lib/instructions'

/**
 * The operator's standing instructions to each agent (DESIGN §12), a page of Settings' own: every agent's file, the
 * one `paths.*_instructions` names, in a panel of its own with its text in the editor. Its description is the files'
 * state in a line; what every visit shows the same is the title's help. Read when the page opens, again when the
 * operator asks, and set by each save.
 */
export const Route = createFileRoute('/settings_/instructions')({
    component: InstructionsPage,
})

function InstructionsPage() {
    const query = useQuery(instructionsQuery)
    const { data, error, refetch, isFetching } = query
    return (
        <>
            <PageHeader
                title="Standing instructions"
                help={INSTRUCTIONS_HELP}
                links={
                    data === undefined ? null : (
                        // One read is every file's, so the page reads them again, not each panel.
                        <Button
                            variant="ghost"
                            size="xs"
                            className="-ml-2 self-start"
                            onClick={() => void refetch()}
                            disabled={isFetching}
                            title="Reads every file again; an edit not saved stays"
                            data-testid="instructions-refresh"
                        >
                            <RotateCw />
                            {isFetching ? 'Reading' : 'Read again'}
                        </Button>
                    )
                }
            >
                {data === undefined ? null : instructionsLine(data.files)}
            </PageHeader>
            {data === undefined ? (
                <Panel>
                    <PanelHeader label="Standing instructions" />
                    <PanelLoading query={query} rows={6} className="min-h-80" />
                </Panel>
            ) : (
                <>
                    {/* A failed read again keeps the files on screen, under why. */}
                    <Notice error={error} />
                    <InstructionsForm list={data} />
                </>
            )}
        </>
    )
}
