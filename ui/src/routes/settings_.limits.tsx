import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { configQuery } from '@/api/queries'
import { ConfigFile, ConfigForm } from '@/components/config-form'
import { PageHeader } from '@/components/panel'
import { configQueryOf, LIMITS_HELP, settingsLine } from '@/lib/config-settings'

interface LimitsSearch {
    q?: string | undefined
}

/**
 * The loop settings of the workspace's private config, a page of Settings' own: its bands and one save bar (M41). Its
 * description is the settings' state in a line; what every visit shows the same is the title's help, and the file a
 * save writes sits under the description, where it can be copied.
 */
export const Route = createFileRoute('/settings_/limits')({
    validateSearch: (search: Record<string, unknown>): LimitsSearch => ({ q: configQueryOf(search['q']) }),
    component: LimitsPage,
})

function LimitsPage() {
    const { q } = Route.useSearch()
    const navigate = Route.useNavigate()
    const keys = useQuery(configQuery).data?.keys
    return (
        <>
            <PageHeader title="Loop settings" help={LIMITS_HELP} links={<ConfigFile />}>
                {keys === undefined ? null : settingsLine(keys)}
            </PageHeader>
            <ConfigForm q={q} onFilter={(text) => void navigate({ search: { q: text }, replace: true })} />
        </>
    )
}
