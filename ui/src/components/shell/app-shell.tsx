import { useQuery } from '@tanstack/react-query'
import { Outlet } from '@tanstack/react-router'
import { Menu } from 'lucide-react'
import { useEffect, useState, ViewTransition } from 'react'

import { sessionQuery, tickQuery } from '@/api/queries'
import { LogoDecoration } from '@/components/season-logo'
import { SignIn } from '@/components/sign-in'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { useAwayNote } from '@/hooks/use-away-note'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { useLiveUpdates } from '@/hooks/use-live-updates'
import { StreamContext } from '@/hooks/use-loop-down'
import { useRailMode } from '@/hooks/use-rail-mode'
import type { RailMode } from '@/hooks/use-rail-mode'
import { useTickAsked } from '@/hooks/use-tick-asked'
import { useBuddy } from '@/lib/buddy'
import { IN_PAGE } from '@/lib/in-page'
import { useSeason } from '@/lib/seasons'
import { isSearchShortcut } from '@/lib/search'
import { cn } from '@/lib/utils'
import { usePalettes } from '@/theme/palette'
import { useTheme } from '@/theme/use-theme'

import { Buddy } from './buddy'
import { Favicon } from './favicon'
import { Game2048 } from './game-2048'
import { JumpPalette } from './jump-palette'
import { LiveReadouts, StreamReadout } from './live-readouts'
import { LoopDownBand } from './loop-down-band'
import { LoopPause } from './loop-pause'
import { Mark, Wordmark } from '@/components/mark'
import { Nav } from './nav'
import { NewerBuild } from './newer-build'
import { RailFooter, RailSpend, RailWorking } from './rail'
import { Rave } from './rave'
import { ReviewDialog } from './review-dialog'
import { SearchBox } from './search-box'
import { ThemeToggle } from './theme-toggle'
import { TicketDialog } from './ticket-dialog'
import { Ticker } from './ticker'
import { TickNow } from '@/components/tick-now'
import { NoticeBanner } from './worker-notice'

/**
 * The scroll restoration id of the element the page scrolls in, everything under the header: the router restores it
 * on going back and puts it at the top on going somewhere new (`scrollToTopSelectors` in `main.tsx`).
 */
export const PAGE_SCROLLER = 'page'

/**
 * The frame every page renders in: header (with its ticker), side rail (search, navigation, what is working now, Sprig
 * once Settings turns it on and the rail has room for it, and at its foot the spend over a footer), the routed page,
 * and over it all the jump palette while ⌘K has it open (`JumpPalette`), the Review a PR dialog while `R` or a pasted
 * PR's URL has it open (`ReviewDialog`), the Start a ticket dialog while `T` has it open (`TicketDialog`), and
 * the lightswitch rave while Settings' light switch is on, 2048 once it is typed away from a field (`Game2048`), and
 * the tab's icon (`Favicon`). Coming back to the tab after a while away, a note of what changed (`useAwayNote`).
 * Signed out, the sign-in page instead, whatever the route: every API route but the session's needs a session
 * (DESIGN §22).
 *
 * The header stays put and only what is under it scrolls (`PAGE_SCROLLER`), so the header spans the window's width:
 * a scrollbar, or the gutter kept for one, sits beside the rail and the page, never beside the header.
 *
 * Under `lg` the rail is a strip of the nav's icons (`useRailMode`): the button atop it opens the whole rail as a sheet
 * over the page, as does `/`, which lands in its search box. A link followed or a search sent from the sheet closes
 * it.
 *
 * Navigations run inside React transitions (TanStack Router starts them), so the old page stays until the new one
 * is ready, and the <ViewTransition> around the outlet cross-fades between them. The new page's blocks rise in one
 * after another (`stagger`). A transition that redraws part of a page (`inPage`), as a search's rows, is not
 * cross-faded.
 */
export function AppShell() {
    // Follows the system theme and other tabs on every page, the sign-in page included, and so does each palette.
    useTheme()
    usePalettes()
    const session = useQuery(sessionQuery)
    const signedIn = session.data?.signed_in === true
    const stream = useLiveUpdates(signedIn)
    useAwayNote(signedIn)
    const buddy = useBuddy()
    const mode = useRailMode()
    const [railOpen, setRailOpen] = useState(false)
    const [jumpOpen, setJumpOpen] = useState(false)
    const sheet = mode !== 'full'
    // Widened to a whole rail, the sheet is closed, so narrowing again does not bring it back by itself.
    if (!sheet && railOpen) {
        setRailOpen(false)
    }
    useEffect(() => {
        if (!sheet) {
            return
        }
        // The search box is in the sheet, so `/` opens it there; the sheet's first focus is the box.
        function onKey(event: KeyboardEvent) {
            if (isSearchShortcut(event, event.target)) {
                event.preventDefault()
                setRailOpen(true)
            }
        }
        globalThis.addEventListener('keydown', onKey)
        return () => {
            globalThis.removeEventListener('keydown', onKey)
        }
    }, [sheet])
    if (session.data === undefined) {
        return <div className="min-h-dvh" />
    }
    if (!signedIn) {
        return <SignIn />
    }
    // The palette opens over the page, so the rail's sheet, which it would cover, closes.
    function jump(open: boolean) {
        if (open) {
            setRailOpen(false)
        }
        setJumpOpen(open)
    }
    return (
        // What the stream says, for whatever under the shell reads it: the readout, the band, the loop's actions.
        <StreamContext value={stream}>
            <Favicon />
            <Sheet open={sheet && railOpen} onOpenChange={setRailOpen}>
                <div className="grid h-dvh grid-rows-[3rem_minmax(0,1fr)] print:h-auto">
                    <header
                        data-testid="app-header"
                        className={cn(
                            'relative z-10 flex items-center justify-between gap-4 border-b border-edge bg-surface/85',
                            'px-4',
                        )}
                    >
                        {/* The aurora: a hairline through the nav's colors, in its order, along the header's foot,
                        over its border. */}
                        <span
                            aria-hidden
                            className="aurora pointer-events-none absolute inset-x-0 -bottom-px opacity-90"
                        />
                        <div className="flex items-center gap-2.5">
                            <LiveMark stream={stream.status} />
                            <StreamReadout stream={stream.status} />
                        </div>
                        <Ticker />
                        {/* Three groups, the actions, the readouts, and the theme, a rule between each. */}
                        <div className="flex items-center gap-2">
                            <NewerBuild />
                            <LoopPause />
                            <TickNow />
                            <Rule />
                            <LiveReadouts />
                            <Rule />
                            <ThemeToggle />
                        </div>
                    </header>
                    <div
                        ref={takeKeys}
                        tabIndex={-1}
                        data-scroll-restoration-id={PAGE_SCROLLER}
                        className={cn('page-scroll grid outline-none', COLUMNS[mode])}
                    >
                        <SkipToContent />
                        {/* The rail spans the whole row, so its border and fill reach the page's foot. What it holds
                        sticks, a column as tall as the window under the header (its 3rem row above), so its foot, the
                        spend and the footer, stays at the window's foot however long the page; the part above it
                        scrolls on its own in a window too short. The room left between them is Sprig's, when it is
                        on. */}
                        {mode === 'full' && (
                            <aside className="border-r border-edge bg-surface/60">
                                <div
                                    className={cn(
                                        'sticky top-0 flex h-[calc(100dvh-3rem)] flex-col',
                                        'print:static print:h-auto',
                                    )}
                                >
                                    <RailColumn buddy={buddy === 'on'} onJump={() => jump(true)} />
                                </div>
                            </aside>
                        )}
                        {mode === 'strip' && (
                            <aside className="border-r border-edge bg-surface/60" data-testid="rail-strip">
                                <div className="sticky top-0 flex flex-col items-center pt-2 print:static">
                                    <RailButton />
                                    <div className="w-full">
                                        <Nav compact />
                                    </div>
                                </div>
                            </aside>
                        )}
                        <main id={MAIN} tabIndex={-1} className="min-w-0 p-6 outline-none">
                            <LoopDownBand />
                            <NoticeBanner />
                            <ViewTransition update={{ [IN_PAGE]: 'none', default: 'auto' }}>
                                <div className="stagger mx-auto flex max-w-[112rem] flex-col gap-6">
                                    <Outlet />
                                </div>
                            </ViewTransition>
                        </main>
                    </div>
                </div>
                {sheet && (
                    <SheetContent
                        data-testid="rail-sheet"
                        className="w-52"
                        // A link followed or a search sent leaves for another page: the sheet would cover it.
                        onClick={(event) => {
                            if (event.target instanceof Element && event.target.closest('a') !== null) {
                                setRailOpen(false)
                            }
                        }}
                        onSubmit={() => {
                            setRailOpen(false)
                        }}
                    >
                        <SheetTitle className="sr-only">Rail</SheetTitle>
                        <SheetDescription className="sr-only">
                            Search, the pages, what is working now, and the spend
                        </SheetDescription>
                        <RailColumn buddy={buddy === 'on'} onJump={() => jump(true)} />
                    </SheetContent>
                )}
                <JumpPalette open={jumpOpen} onOpenChange={jump} />
                <ReviewDialog />
                <TicketDialog />
                <Rave />
                <Game2048 />
            </Sheet>
        </StreamContext>
    )
}

// The page's columns by how the rail shows: whole, or a strip.
const COLUMNS: Record<RailMode, string> = {
    full: 'grid-cols-[13rem_minmax(0,1fr)]',
    strip: 'grid-cols-[3.5rem_minmax(0,1fr)]',
}

// The page's own content, which the skip link moves the focus to.
const MAIN = 'main'

/**
 * The first stop the keyboard reaches on every page, from a fresh load or from the header: a link past the rail's
 * search, nav, and runs to the page itself, unseen until it has the focus (ui/DESIGN.md, "Shape and space"). The
 * focus moves to the page's `main`, so the next Tab is the page's first stop. It moves by script, not by the link's
 * `#main`, which the base path would make another page's address.
 */
function SkipToContent() {
    return (
        <a
            href={`#${MAIN}`}
            onClick={(event) => {
                event.preventDefault()
                document.querySelector<HTMLElement>(`#${MAIN}`)?.focus()
            }}
            className={cn(
                'sr-only rounded-sm border bg-surface px-3 py-1.5 text-sm font-medium',
                'focus:not-sr-only focus:fixed focus:top-14 focus:left-4 focus:z-20',
            )}
        >
            Skip to content
        </a>
    )
}

/**
 * What the rail holds, whether beside the page or in the sheet, in two groups (DESIGN's Shape and space): the top, the
 * search box, the nav, and what is working, and the foot, the spend standing on the footer. The room left between them
 * is one gap, Sprig's slot when it is on, so Sprig stands on the foot.
 */
function RailColumn({ buddy, onJump }: { buddy: boolean; onJump: () => void }) {
    return (
        <>
            {/* pb-3: the gap's least, so with none to spare the foot's hairline still has room above it. */}
            <div className="panel-scroll min-h-0 pb-3">
                <SearchBox onJump={onJump} />
                <Nav />
                <RailWorking />
            </div>
            {buddy ? <Buddy /> : <div className="flex-1" />}
            <div data-testid="rail-foot">
                <RailSpend />
                <RailFooter />
            </div>
        </>
    )
}

/** The button atop the strip that opens the whole rail in a sheet. */
function RailButton() {
    return (
        <SheetTrigger asChild>
            <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Open the rail"
                title="Search, what is working now, and the spend"
                data-testid="rail-open"
            >
                <Menu aria-hidden />
            </Button>
        </SheetTrigger>
    )
}

/**
 * The header's logo and name, alive with the stream and the latest tick, and with the tick Tick now asked for. In a
 * season, while Sprig is on, what the season hangs over the logo hangs there too.
 */
function LiveMark({ stream }: { stream: StreamStatus }) {
    const tick = useQuery(tickQuery).data?.tick
    const asked = useTickAsked()
    const season = useSeason()
    const buddy = useBuddy()
    return (
        <span className="relative flex items-center gap-2.5">
            <Mark live={stream === 'open'} ticking={tick?.status === 'running' || asked} beat={tick?.id} />
            <Wordmark beat={tick?.id} />
            {buddy === 'on' && season !== null ? <LogoDecoration id={season} /> : null}
        </span>
    )
}

/**
 * Gives the page's scroller the focus when nothing else has it, as on a fresh load: the keys that scroll (Page Down,
 * Space, the arrows) scroll the focused element's scroller, and with the focus on the body that is the window, which
 * no longer scrolls. Focus a page's own element took first stays where it is.
 */
function takeKeys(scroller: HTMLDivElement | null) {
    if (scroller !== null && document.activeElement === document.body) {
        scroller.focus({ preventScroll: true })
    }
}

/** A hairline between the header's groups. */
function Rule() {
    return <span aria-hidden className="h-5 w-px bg-border" />
}
