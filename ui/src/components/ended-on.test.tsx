import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Transcript, TranscriptEntry } from '@/api/types'
import { useTranscriptView } from '@/hooks/use-transcript-view'

import { EndedOnField } from './ended-on'
import { Fields } from './fields'
import { TranscriptPanel } from './transcript'

afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
})

// A failed fix-ci run's session, as run:40's: it read the job's log, then the runtime gave up on a rate limit.
const FAILED: TranscriptEntry[] = [
    {
        kind: 'text',
        call: 1,
        at: '2026-10-08T10:46:00Z',
        text: "Reading the failing job's log first.",
        reasoning: false,
        cut: false,
    },
    {
        kind: 'tool',
        call: 1,
        at: '2026-10-08T10:47:00Z',
        tool: 'bash',
        title: 'Find the failing job',
        input: '{"command": "gh run list --branch agent/ABC-100-flaky-test"}',
        output: 'gh: not found',
        status: 'error',
        duration_ms: 2000,
        cut: false,
    },
    { kind: 'error', call: 2, at: '2026-10-08T10:49:54Z', name: 'APIError', message: 'Rate limited: retry after 60s' },
]

function transcript(entries: TranscriptEntry[] = FAILED, fields: Partial<Transcript> = {}): Transcript {
    return {
        session_id: 'ses_40',
        status: 'read',
        entries,
        prompt: null,
        truncated: false,
        unreadable: 0,
        removed_after_days: null,
        ...fields,
    }
}

// A run's page, as far as this field goes: the Run panel's field over the transcript, sharing how it is shown.
function Page({ status, shown }: { status: string; shown: Transcript | undefined }) {
    const view = useTranscriptView()
    return (
        <>
            <Fields>
                <EndedOnField status={status} transcript={shown} onShow={view.show} />
            </Fields>
            <TranscriptPanel transcript={shown} running={false} page="run" view={view} />
        </>
    )
}

function field(): HTMLElement | null {
    return screen.queryByText('ended on')
}

describe('EndedOnField', () => {
    it.each(['failed', 'crashed', 'unknown'])(
        'names the runtime error a %s run ended on: its time, name, and first line',
        (status) => {
            render(<Page status={status} shown={transcript()} />)
            expect(field()).not.toBeNull()
            const button = screen.getByRole('button', { name: '+3:54 APIError Rate limited: retry after 60s' })
            expect(button.title).toBe('Show it in the transcript')
        },
    )

    it('names the last failed tool call when the runtime reported no error', () => {
        render(<Page status="failed" shown={transcript(FAILED.slice(0, 2))} />)
        expect(screen.getByRole('button', { name: '+1:00 bash gh: not found' })).toBeDefined()
    })

    it.each(['done', 'blocked', 'ok', 'running', 'stopped', 'timeout', 'unpushed'])(
        'shows nothing for a run that ended %s',
        (status) => {
            render(<Page status={status} shown={transcript()} />)
            expect(field()).toBeNull()
        },
    )

    it('holds its place while the transcript is read, and says when it holds nothing to name', () => {
        const { rerender } = render(<Page status="failed" shown={undefined} />)
        expect(field()).not.toBeNull()
        rerender(<Page status="failed" shown={transcript([])} />)
        expect(screen.getByText('none: no runtime error or failed call in its transcript')).toBeDefined()
    })

    it('says on hover that a cut transcript may not hold the log’s end', () => {
        render(<Page status="failed" shown={transcript(FAILED, { truncated: true })} />)
        expect(screen.getByRole('button', { name: /APIError/u }).title).toBe(
            'Show it in the transcript, which is cut: the log may end on a later one',
        )
    })

    it('shows its row as the context chart does: in order, unsearched, scrolled to, and focused', () => {
        const scrolled = vi.spyOn(HTMLElement.prototype, 'scrollIntoView')
        render(<Page status="failed" shown={transcript()} />)
        fireEvent.change(screen.getByRole('searchbox', { name: 'Find lines in the transcript' }), {
            target: { value: 'gh run' },
        })
        expect(within(screen.getByTestId('transcript-entries')).queryByText('APIError')).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: /APIError/u }))

        const rows = within(screen.getByTestId('transcript-entries'))
        expect(rows.getByText('Rate limited: retry after 60s')).toBeDefined()
        expect(scrolled).toHaveBeenCalledWith({ block: 'center' })
        expect(document.activeElement?.textContent).toContain('Rate limited: retry after 60s')
    })
})
