import { useState } from 'react'
import type { ReactNode } from 'react'

import type { EpicOutline } from '@/api/types'
import { Tip } from '@/components/tip'
import { LightContext, LitContext, OutlineContext, useLight, useLit, useWords } from '@/hooks/use-outline-lights'
import { cn } from '@/lib/utils'

/**
 * Where an epic's page lights its outline's ids: pointing at an id anywhere under it, by hover or by focus, lights
 * that id wherever it shows and the entries that cite it (`cites`), so who covers, provides, and uses what reads both
 * ways. It is the page's small bit of fun, and it only adds: nothing dims, moves, or hides, and the same facts are in
 * each id's tip and in the requirements' own lines.
 */
export function OutlineLights({ outline, children }: { outline: EpicOutline | null; children: ReactNode }) {
    const [lit, light] = useState<string | null>(null)
    return (
        <OutlineContext value={outline}>
            <LightContext value={light}>
                <LitContext value={lit}>{children}</LitContext>
            </LightContext>
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
    const light = useLight()
    const words = useWords(id)
    const leave = () => {
        light((current) => (current === id ? null : current))
    }
    return (
        <Tip fact={fact ?? words}>
            <span
                data-lit={on ? '' : undefined}
                onPointerEnter={() => {
                    light(id)
                }}
                onPointerLeave={leave}
                onFocus={() => {
                    light(id)
                }}
                onBlur={leave}
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
