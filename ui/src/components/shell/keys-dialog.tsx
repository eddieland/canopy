import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { usePageKey } from '@/hooks/use-page-key'
import { KEY_LINES } from '@/lib/keys'
import { isApple, sendShortcut, useSendKey } from '@/lib/send-key'

const APPLE = isApple(navigator.userAgent)

// A key in `aria-keyshortcuts` terms as its keycap prints it.
const CAPS: Partial<Record<string, string>> = { Meta: '⌘', Control: 'Ctrl' }

/**
 * The keys the pages answer to (`KEY_LINES`), listed in a dialog that `?` opens from anywhere but a text field
 * (ui/DESIGN.md, "Keys"): each line its keycaps and what they do, then the key that sends a reply as Settings sets
 * it, linked there. Escape, a click outside, or its close button closes it, and the focus goes back where it was.
 */
export function KeysDialog() {
    const [open, setOpen] = useState(false)
    const send = sendShortcut(useSendKey(), APPLE)
    usePageKey('keys', () => {
        setOpen(true)
        return true
    })
    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent data-testid="keys-dialog">
                <DialogTitle>Keys</DialogTitle>
                <DialogDescription>From anywhere but a text field.</DialogDescription>
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-4 gap-y-2 text-sm">
                    {KEY_LINES.map((line) => (
                        <Line key={line.does} keys={line.keys}>
                            {line.does}
                        </Line>
                    ))}
                    {send !== undefined && (
                        <Line keys={send.split('+').map((key) => CAPS[key] ?? key)}>
                            Send a reply or a note, from its box, as{' '}
                            <Link
                                to="/settings"
                                className="text-accent underline-offset-4 hover:underline"
                                onClick={() => setOpen(false)}
                            >
                                Settings
                            </Link>{' '}
                            sets it
                        </Line>
                    )}
                </dl>
            </DialogContent>
        </Dialog>
    )
}

/** One key's line: its keycaps, then what it does. */
function Line({ keys, children }: { keys: readonly string[]; children: ReactNode }) {
    return (
        <>
            <dt className="flex gap-1">
                {keys.map((key) => (
                    <Kbd key={key}>{key}</Kbd>
                ))}
            </dt>
            <dd className="text-muted-foreground">{children}</dd>
        </>
    )
}
