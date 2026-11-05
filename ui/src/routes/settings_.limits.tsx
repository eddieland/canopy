import { createFileRoute } from '@tanstack/react-router'

import { ConfigFile, ConfigForm } from '@/components/config-form'
import { PageHeader } from '@/components/panel'
import { SOURCES_HELP } from '@/lib/config-settings'

/** The loop settings of the workspace's private config, a page of Settings' own: its panels and one save
 * bar (M41). */
export const Route = createFileRoute('/settings_/limits')({
    component: LimitsPage,
})

function LimitsPage() {
    return (
        <>
            <PageHeader title="Loop settings" help={SOURCES_HELP}>
                What the loop runs, spends, polls, and keeps, and whose words it acts on. Saved to <ConfigFile />, this
                workspace&apos;s own config, with its comments kept and the old file beside it as config.toml.bak; your
                user config is never changed. Limits and retentions move within their bounds; trust settings only get
                stricter; anything else is an edit to the file.
            </PageHeader>
            <ConfigForm />
        </>
    )
}
