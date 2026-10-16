import { createFileRoute } from '@tanstack/react-router'

import { ConfigFile, ConfigForm } from '@/components/config-form'
import { PageHeader } from '@/components/panel'

/** The limits and trust settings of the workspace's private config, a page of Settings' own: its panels and one save
 * bar (M41). */
export const Route = createFileRoute('/settings_/limits')({
    component: LimitsPage,
})

function LimitsPage() {
    return (
        <>
            <PageHeader title="Limits and trust">
                What the loop may run and spend, and whose words it acts on. Saved to <ConfigFile />, this
                workspace&apos;s own config, with its comments kept and the old file beside it as config.toml.bak; your
                user config is never changed. Limits move within their bounds; trust settings only get stricter;
                anything else is an edit to the file.
            </PageHeader>
            <ConfigForm />
        </>
    )
}
