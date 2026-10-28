import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent, ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { bestScore, getGame, GOAL, hasGame, play, restart, setGame, useGame } from '@/lib/game-2048'
import type { Direction, Saved } from '@/lib/game-2048'
import { age, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/** What is typed, away from a text field, to open the game. */
export const SECRET = '2048'

/** How far a swipe must travel, in pixels, to slide the tiles. */
export const SWIPE = 24

/**
 * 2048, an Easter egg (ui/DESIGN.md, Fun): typing 2-0-4-8 anywhere but a text field opens it over the page, as a
 * dialog, so it covers nothing until asked and Escape puts it away. The arrow keys, WASD, or a swipe slide the tiles.
 * The game in play is kept in this browser as each move lands (src/lib/game-2048.ts), so closing it, reloading, or
 * opening it in another tab picks up the same board; every finished game goes into the best scores under it, and so
 * does one given up for a new game.
 */
export function Game2048() {
    const [open, setOpen] = useState(false)
    useEffect(() => {
        let typed = ''
        function onKey(event: KeyboardEvent) {
            if (event.ctrlKey || event.metaKey || event.altKey || isField(event.target)) {
                typed = ''
                return
            }
            typed = (typed + event.key).slice(-SECRET.length)
            if (typed === SECRET) {
                typed = ''
                const saved = getGame()
                if (!hasGame(saved)) {
                    setGame(restart(saved, new Date().toISOString()))
                }
                setOpen(true)
            }
        }
        globalThis.addEventListener('keydown', onKey)
        return () => {
            globalThis.removeEventListener('keydown', onKey)
        }
    }, [])
    return (
        <Dialog open={open} onOpenChange={setOpen}>
            {open && <Game />}
        </Dialog>
    )
}

// Where each key slides the tiles: the arrows, and WASD for a hand already on the letters.
const KEYS: Partial<Record<string, Direction>> = {
    ArrowUp: 'up',
    ArrowDown: 'down',
    ArrowLeft: 'left',
    ArrowRight: 'right',
    w: 'up',
    s: 'down',
    a: 'left',
    d: 'right',
}

/** The tiles a move just made, added or merged, which pop in; `turn` tells one move's from the next. */
interface Fresh {
    /** How many moves this dialog has seen. */
    turn: number
    /** The cells the move filled, by index. */
    cells: readonly number[]
}

/** The game in its dialog: the scores, the board, a line on how it stands, and the best games. */
function Game() {
    const saved = useGame()
    const [fresh, setFresh] = useState<Fresh>({ turn: 0, cells: [] })
    const content = useRef<HTMLDivElement>(null)
    const swipe = useRef<{ x: number; y: number } | null>(null)

    function move(direction: Direction) {
        const before = getGame()
        const result = play(before, direction, new Date().toISOString())
        if (result.saved === before) {
            return
        }
        setGame(result.saved)
        setFresh((last) => ({
            turn: last.turn + 1,
            cells: result.added === null ? result.merged : [...result.merged, result.added],
        }))
    }

    function onKeyDown(event: ReactKeyboardEvent) {
        const direction = KEYS[event.key]
        if (direction === undefined || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) {
            return
        }
        event.preventDefault()
        move(direction)
    }

    function onPointerUp(event: ReactPointerEvent) {
        const start = swipe.current
        swipe.current = null
        if (start === null) {
            return
        }
        const dx = event.clientX - start.x
        const dy = event.clientY - start.y
        if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE) {
            return
        }
        if (Math.abs(dx) > Math.abs(dy)) {
            move(dx > 0 ? 'right' : 'left')
        } else {
            move(dy > 0 ? 'down' : 'up')
        }
    }

    function newGame() {
        setGame(restart(getGame(), new Date().toISOString()))
        setFresh((last) => ({ turn: last.turn + 1, cells: [] }))
        content.current?.focus()
    }

    return (
        <DialogContent
            ref={content}
            data-testid="game-2048"
            className="max-w-sm p-4"
            onKeyDown={onKeyDown}
            onOpenAutoFocus={(event) => {
                // The dialog itself takes the focus, not New game, so the first key slides the tiles and Enter
                // throws no game away.
                event.preventDefault()
                content.current?.focus()
            }}
        >
            <div className="flex items-start justify-between gap-3">
                <div>
                    <DialogTitle className="text-2xl font-semibold tracking-tight">{GOAL}</DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground">
                        Join the numbers and get to the {GOAL} tile.
                    </DialogDescription>
                </div>
                <div className="flex gap-2">
                    <Readout label="Score" value={saved.score} />
                    <Readout label="Best" value={bestScore(saved)} />
                </div>
            </div>
            <ol
                aria-label="Board"
                className="mt-4 grid touch-none grid-cols-4 gap-2 rounded-md bg-border p-2 select-none"
                onPointerDown={(event) => {
                    swipe.current = { x: event.clientX, y: event.clientY }
                }}
                onPointerUp={onPointerUp}
                onPointerCancel={() => {
                    swipe.current = null
                }}
            >
                {saved.board.map((value, cell) => {
                    const isFresh = fresh.cells.includes(cell)
                    return (
                        <Tile
                            // A fresh tile is mounted anew each move, so its pop plays again.
                            key={isFresh ? `${cell}:${fresh.turn}` : cell}
                            value={value}
                            fresh={isFresh}
                        />
                    )
                })}
            </ol>
            <div className="mt-3 flex items-center justify-between gap-3">
                <Status saved={saved} />
                <Button variant="outline" size="sm" onClick={newGame}>
                    New game
                </Button>
            </div>
            <Scores saved={saved} />
        </DialogContent>
    )
}

/** A score over its label, in a box of its own. */
function Readout({ label, value }: { label: string; value: number }) {
    return (
        <div className="flex min-w-16 flex-col items-center rounded-md bg-surface-raised px-3 py-1">
            <span className="text-2xs tracking-wide text-muted-foreground uppercase">{label}</span>
            <span className="readout text-base font-semibold">{value}</span>
        </div>
    )
}

/** A cell of the board, row by row: empty, or a tile with its number, sized down as the number grows. */
function Tile({ value, fresh }: { value: number; fresh: boolean }) {
    if (value === 0) {
        return <li aria-label="empty" className="aspect-square rounded-sm bg-background" />
    }
    const digits = String(value).length
    return (
        <li
            data-tile={value > GOAL ? 'big' : value}
            data-fresh={fresh ? '' : undefined}
            className={cn(
                'game-tile readout flex aspect-square items-center justify-center rounded-sm font-bold',
                digits <= 2 ? 'text-3xl' : digits === 3 ? 'text-2xl' : 'text-lg',
            )}
        >
            {value}
        </li>
    )
}

/** How the game stands: over, past the goal, or how to play. Announced as it changes. */
function Status({ saved }: { saved: Saved }) {
    let text: ReactNode
    if (saved.recorded) {
        text = 'No moves left. That one goes in the scores.'
    } else if (saved.won) {
        text = `You made ${GOAL}. It keeps going, as the backlog does.`
    } else {
        text = (
            <>
                <Kbd>←</Kbd> <Kbd>↑</Kbd> <Kbd>→</Kbd> <Kbd>↓</Kbd> or <Kbd>WASD</Kbd> to slide, or swipe
            </>
        )
    }
    return <output className="text-xs text-muted-foreground">{text}</output>
}

/** The best finished games, best first: each one's score, its largest tile, and how long ago it ended. */
function Scores({ saved }: { saved: Saved }) {
    const now = useNow()
    return (
        <section aria-labelledby="game-2048-scores" className="mt-4 border-t pt-3">
            <h3 id="game-2048-scores" className="text-xs font-medium text-muted-foreground">
                Best games
            </h3>
            {saved.scores.length === 0 ? (
                <p className="mt-1.5 text-xs text-muted-foreground">Finished games show up here.</p>
            ) : (
                <ol className="mt-1.5 flex flex-col gap-0.5 text-xs">
                    {saved.scores.map((s, i) => (
                        <li key={`${s.at}:${s.score}`} className="flex items-center gap-3">
                            <span className="readout w-5 text-muted-foreground">{i + 1}.</span>
                            <span className="readout w-16 font-medium">{s.score}</span>
                            <span className="flex-1 text-muted-foreground">
                                top tile <span className="readout">{s.tile}</span>
                            </span>
                            <time dateTime={s.at} className="text-muted-foreground">
                                <span className="readout">{age(s.at, now)}</span> ago
                            </time>
                        </li>
                    ))}
                </ol>
            )}
        </section>
    )
}

// Whether a key press lands in a text field, where 2048 is just a number someone is typing.
function isField(target: EventTarget | null): boolean {
    return (
        target instanceof HTMLElement &&
        (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
    )
}
