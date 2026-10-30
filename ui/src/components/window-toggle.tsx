import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { windowId, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'

/**
 * A report page's window, as a segmented control in a panel's header (ui/DESIGN.md, "The spend chart"): each window
 * the page offers, by its length, the one shown pressed. Pressing another calls `onPick` with it, for the page to put
 * in its search params; pressing the one shown keeps it. Each item's test id is `testId`'s, then `-window-` and the
 * window's id: `spend-window-24h`.
 */
export function WindowToggle({
    windows,
    shown,
    onPick,
    testId,
}: {
    windows: readonly ReportWindow[]
    shown: ReportWindow
    onPick: (picked: ReportWindow) => void
    testId: string
}) {
    return (
        <ToggleGroup
            type="single"
            value={windowId(shown)}
            aria-label="Window"
            onValueChange={(value) => {
                const picked = windows.find((w) => windowId(w) === value)
                // Pressing the window shown turns it off, which reads as no value: keep it.
                if (picked !== undefined) {
                    onPick(picked)
                }
            }}
        >
            {windows.map((w) => (
                <ToggleGroupItem key={windowId(w)} value={windowId(w)} data-testid={`${testId}-window-${windowId(w)}`}>
                    {windowName(w)}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}
