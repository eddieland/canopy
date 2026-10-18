import { useQuery } from '@tanstack/react-query'
import { RotateCw } from 'lucide-react'

import { metaQuery } from '@/api/queries'
import { Button } from '@/components/ui/button'
import { isOutdated, pageBuild } from '@/lib/build'

const HINT = 'canopy now serves a newer web UI than this page. Reload to use it; text typed here and not sent is lost.'

/**
 * The header's Reload, shown only while the server serves a newer build of the UI than this page was loaded from, as
 * after an upgrade restarts the loop: the stream's reconnect reads the server's meta again (useLiveUpdates). It never
 * reloads on its own, since the operator may be typing.
 */
export function NewerBuild() {
    const served = useQuery(metaQuery).data?.build
    if (!isOutdated(pageBuild, served)) {
        return null
    }
    return (
        // The accent's tint, not its fill: it stands out among the header's ghost buttons without outshouting them.
        <Button
            variant="ghost"
            size="sm"
            className="bg-accent/14 text-accent hover:bg-accent/22 hover:text-accent"
            title={HINT}
            data-testid="newer-build"
            onClick={() => globalThis.location.reload()}
        >
            <RotateCw aria-hidden />
            Reload
        </Button>
    )
}
