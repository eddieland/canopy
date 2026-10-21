import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Megaphone } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { setNotice, showLoop } from '@/api/mutations'
import type { NoticeChanged } from '@/api/types'
import { Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useClock } from '@/lib/clock'
import { minutesUntil } from '@/lib/notice-time'
import { noticeSetText } from '@/lib/outcomes'
import { useSendKeys } from '@/lib/send-key'
import { stamp } from '@/lib/time'

// How long a notice set here lasts; `canopy notice --for` takes any duration up to a week.
const LASTS: { value: string; label: string; minutes: number }[] = [
    { value: '1h', label: '1 hour', minutes: 60 },
    { value: '4h', label: '4 hours', minutes: 240 },
    { value: '1d', label: '1 day', minutes: 1440 },
]
// The toggle's value for keeping the time the edited notice lapses.
const KEEP = 'keep'

/** What the notice form starts from, and what it is called on the page. */
export interface NoticeFormProps {
    /** The words it starts with: the notice it edits, or none for a new one. */
    initial?: string
    /** When the notice it edits lapses: offered first, and picked, so an edit keeps the time it ends. */
    until?: string
    /** The words on its send button. */
    submit: string
    /** The field's accessible name. */
    label: string
    /** The prefix of its test ids: `-text`, `-lasts-1h`, `-set`. */
    testId: string
    /** Called once the notice is set, with what setting it did. */
    onSet?: (changed: NoticeChanged) => void
    /** Shows a ghost Cancel that calls it. */
    onCancel?: () => void
    /** What the form says above its field. */
    children?: ReactNode
}

/**
 * Sets a notice to workers, as `canopy notice TEXT --for DURATION` does (docs/design §8), replacing the one in force:
 * its words, how long it lasts as a toggle group, and its send button. Settings sets a new one with it, and the banner
 * edits the one in force, its time kept unless the operator picks another. Its words empty once it is set.
 */
export function NoticeForm({ initial = '', until, submit, label, testId, onSet, onCancel, children }: NoticeFormProps) {
    const client = useQueryClient()
    const clock = useClock()
    const sendKeys = useSendKeys()
    const [text, setText] = useState(initial)
    const [lasts, setLasts] = useState(until === undefined ? '4h' : KEEP)
    const mutation = useMutation({
        mutationFn: () => setNotice(text, minutesFor(lasts, until)),
        onSuccess: (changed) => {
            showLoop(client, changed.loop)
            setText('')
            onSet?.(changed)
        },
    })
    // An edit that changes neither the words nor the time would only set the same notice again.
    const unchanged = until !== undefined && lasts === KEEP && text.trim() === initial.trim()
    const ready = !mutation.isPending && text.trim() !== '' && !unchanged
    return (
        <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
                event.preventDefault()
                if (ready) {
                    mutation.mutate()
                }
            }}
        >
            {children}
            <Textarea
                value={text}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={sendKeys.onKeyDown}
                placeholder="Artifactory is down: CI builds that fetch dependencies will likely fail."
                aria-label={label}
                data-testid={`${testId}-text`}
                className="min-h-16"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <ToggleGroup
                    type="single"
                    value={lasts}
                    aria-label="Lasts for"
                    onValueChange={(value) => {
                        if (value !== '') {
                            setLasts(value)
                        }
                    }}
                >
                    {until === undefined ? null : (
                        <ToggleGroupItem value={KEEP} data-testid={`${testId}-lasts-${KEEP}`}>
                            Until {stamp(until, clock)}
                        </ToggleGroupItem>
                    )}
                    {LASTS.map(({ value, label: words }) => (
                        <ToggleGroupItem key={value} value={value} data-testid={`${testId}-lasts-${value}`}>
                            {words}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
                <div className="flex items-center gap-2">
                    {onCancel === undefined ? null : (
                        <Button type="button" variant="ghost" onClick={onCancel}>
                            Cancel
                        </Button>
                    )}
                    <Button
                        type="submit"
                        variant="outline"
                        disabled={!ready}
                        aria-keyshortcuts={sendKeys.shortcut}
                        data-testid={`${testId}-set`}
                    >
                        <Megaphone />
                        {submit}
                        <SendKeycap keys={sendKeys.shortcut} />
                    </Button>
                </div>
            </div>
            <Notice error={mutation.error}>{mutation.data ? noticeSetText(mutation.data) : null}</Notice>
        </form>
    )
}

function minutesFor(lasts: string, until: string | undefined): number {
    if (lasts === KEEP && until !== undefined) {
        return minutesUntil(until, Date.now())
    }
    return LASTS.find((l) => l.value === lasts)?.minutes ?? 240
}
