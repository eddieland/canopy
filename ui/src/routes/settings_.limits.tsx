import { createFileRoute } from '@tanstack/react-router'

import { ConfigFile, ConfigForm } from '@/components/config-form'
import { PageHeader } from '@/components/panel'
import { configQueryOf, SOURCES_HELP } from '@/lib/config-settings'

interface LimitsSearch {
    q?: string | undefined
}

/** The loop settings of the workspace's private config, a page of Settings' own: its panels and one save
 * bar (M41). */
export const Route = createFileRoute('/settings_/limits')({
    validateSearch: (search: Record<string, unknown>): LimitsSearch => ({ q: configQueryOf(search['q']) }),
    component: LimitsPage,
})

function LimitsPage() {
    const { q } = Route.useSearch()
    const navigate = Route.useNavigate()
    return (
        <>
            <PageHeader title="Loop settings" help={SOURCES_HELP}>
                What the loop runs, spends, polls, and keeps, and whose words it acts on. Saved to <ConfigFile />, this
                workspace&apos;s own config, with its comments kept and the old file beside it as config.toml.bak; your
                user config is never changed. Limits and retentions move within their bounds; trust settings only get
                stricter; anything else is an edit to the file.
            </PageHeader>
            <ConfigForm q={q} onFilter={(text) => void navigate({ search: { q: text }, replace: true })} />
        </>
    )
}
