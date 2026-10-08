import { Panel } from '@/components/panel'

/** The attention page with nothing listed: a small canopy swaying in the wind, one leaf drifting off it. */
export function AllClear() {
    return (
        <Panel data-testid="all-clear">
            <div className="grid min-h-40 place-items-center content-center gap-3 p-6 text-center">
                <svg viewBox="0 0 64 52" className="h-14 text-accent" aria-hidden>
                    <line
                        x1="32"
                        y1="50"
                        x2="32"
                        y2="30"
                        stroke="currentColor"
                        strokeWidth="1.5"
                        strokeLinecap="round"
                        className="text-muted-foreground"
                    />
                    <g className="origin-[32px_50px] animate-sway">
                        <circle cx="22" cy="26" r="10" fill="currentColor" fillOpacity="0.12" stroke="currentColor" />
                        <circle cx="42" cy="26" r="10" fill="currentColor" fillOpacity="0.12" stroke="currentColor" />
                        <circle cx="32" cy="16" r="12" fill="currentColor" fillOpacity="0.16" stroke="currentColor" />
                    </g>
                    <ellipse cx="47" cy="35" rx="2.2" ry="1.2" fill="currentColor" className="animate-drift" />
                </svg>
                <div className="flex flex-col gap-0.5">
                    <span className="text-sm">Nothing needs you.</span>
                    <span className="font-mono text-xs text-muted-foreground">all clear under the canopy</span>
                </div>
            </div>
        </Panel>
    )
}
