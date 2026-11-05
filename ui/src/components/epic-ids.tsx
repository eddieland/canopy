import { useReducer } from 'react'
import type { ReactNode } from 'react'

import type { EpicOutline } from '@/api/types'
import { Tip } from '@/components/tip'
import {
    LitContext,
    litOf,
    OutlineContext,
    point,
    PointContext,
    useLit,
    usePoint,
    useWords,
} from '@/hooks/use-outline-lights'
import { cn } from '@/lib/utils'

/**
 * Where an epic's page lights its outline's ids: pointing at an id anywhere under it, by hover or by focus, lights
 * that id wherever it shows and the entries that cite it (`cites`), so who covers, provides, and uses what reads both
 * ways. The mouse and the focus each point at one id, the mouse's lit first, so leaving one never puts out the other.
 * It is the page's small bit of fun, and it only adds: nothing dims, moves, or hides, and the same facts are in each
 * id's tip and in the requirements' own lines.
 */
export function OutlineLights({ outline, children }: { outline: EpicOutline | null; children: ReactNode }) {
    const [pointed, pointAt] = useReducer(point, { hover: null, focus: null })
    return (
        <OutlineContext value={outline}>
            <PointContext value={pointAt}>
                <LitContext value={litOf(pointed)}>{children}</LitContext>
            </PointContext>
        </OutlineContext>
    )
}

/**
 * One of an outline's ids, `R1`, `C1`, or `B1`, as data: pointing at it lights it and every entry that cites it, and
 * its tip says its words (a requirement's or a contract's text, an entry's title), or `fact` in their place. Lit, it
 * fills with the accent, as a stop on a transit map lights up on its line; at rest it is plain monospace.
 */
export function OutlineId({ id, fact, className }: { id: string; fact?: string; className?: string }) {
    const on = useLit() === id
    const pointAt = usePoint()
    const words = useWords(id)
    return (
        <Tip fact={fact ?? words}>
            <span
                data-lit={on ? '' : undefined}
                onPointerEnter={() => {
                    pointAt({ by: 'hover', id, on: true })
                }}
                onPointerLeave={() => {
                    pointAt({ by: 'hover', id, on: false })
                }}
                onFocus={() => {
                    pointAt({ by: 'focus', id, on: true })
                }}
                onBlur={() => {
                    pointAt({ by: 'focus', id, on: false })
                }}
                className={cn(
                    'readout inline-block rounded-xs px-1 text-xs',
                    'motion-safe:transition-colors motion-safe:duration-150 motion-safe:ease-out',
                    on ? 'bg-accent text-accent-foreground' : 'text-foreground',
                    className,
                )}
            >
                {id}
            </span>
        </Tip>
    )
}
