import { createFileRoute } from '@tanstack/react-router'

import { ConfigFile, ConfigForm } from '@/components/config-form'
import { PageHeader } from '@/components/panel'

/** The limits and trust settings of the user config, a page of Settings' own: its panels and one save bar (M41). */
export const Route = createFileRoute('/settings_/limits')({
    component: LimitsPage,
})

function LimitsPage() {
    return (
        <>
            <PageHeader title="Limits and trust">
                What the loop may run and spend, and whose words it acts on. Saved to <ConfigFile /> with its comments
                kept, the old file beside it as config.toml.bak. Limits move within their bounds; trust settings only
                get stricter; anything else is an edit to the file.
            </PageHeader>
            <ConfigForm />
        </>
    )
}
