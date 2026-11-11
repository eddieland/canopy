import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ToastContext } from '@/hooks/use-toast'
import { saveFile } from '@/lib/save-file'
import type { NewToast } from '@/lib/toasts'

import { PlanMarkdownActions } from './plan-markdown'

vi.mock(import('@/lib/save-file'), () => ({ saveFile: vi.fn<typeof saveFile>() }))

const NAME = '412-APPROVED-export-reports-as-csv.md'
const TEXT = '# Plan: ABC-1 Export reports as CSV\n\n- Add the writer.\n'

let toasts: NewToast[] = []

function renderActions(fields: { unsaved?: boolean; what?: string } = {}) {
    return render(
        <ToastContext
            value={(toast) => {
                toasts.push(toast)
            }}
        >
            <PlanMarkdownActions markdown={() => TEXT} fileName={NAME} {...fields} />
        </ToastContext>,
    )
}

// Lets the clipboard's promise settle, and React render what it did.
async function settle() {
    await act(async () => {
        await Promise.resolve()
    })
}

beforeEach(() => {
    toasts = []
    vi.stubGlobal('isSecureContext', true)
})

afterEach(() => {
    cleanup()
    vi.mocked(saveFile).mockClear()
})

describe('PlanMarkdownActions', () => {
    it('copies the Markdown whole, as the page shows it, and says so', async () => {
        const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
        renderActions()

        fireEvent.click(screen.getByRole('button', { name: 'Copy Markdown' }))
        await settle()
        expect(write).toHaveBeenCalledWith(TEXT)
        expect(toasts).toEqual([{ title: "Copied the plan's Markdown", tone: 'done' }])
    })

    it('saves the Markdown under the name canopy archive gives it', () => {
        renderActions()

        fireEvent.click(screen.getByRole('button', { name: 'Save .md' }))
        expect(saveFile).toHaveBeenCalledOnce()
        const [blob, name] = vi.mocked(saveFile).mock.calls[0] ?? []
        expect(name).toBe(NAME)
        expect(blob?.type).toBe('text/markdown')
        expect(blob?.size).toBe(new TextEncoder().encode(TEXT).length)
        expect(toasts).toEqual([{ title: "Saved the plan's Markdown", detail: NAME, tone: 'done' }])
    })

    it('says edits not yet saved went with it', async () => {
        vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
        renderActions({ unsaved: true, what: 'report' })

        fireEvent.click(screen.getByRole('button', { name: 'Copy Markdown' }))
        await settle()
        fireEvent.click(screen.getByRole('button', { name: 'Save .md' }))
        expect(toasts.map((toast) => toast.title)).toEqual([
            "Copied the report's Markdown, with your unsaved edits",
            "Saved the report's Markdown, with your unsaved edits",
        ])
    })

    it('says so when the browser refuses the clipboard', async () => {
        vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
        renderActions()

        fireEvent.click(screen.getByRole('button', { name: 'Copy Markdown' }))
        await settle()
        expect(toasts).toEqual([
            {
                title: "Could not copy the plan's Markdown",
                detail: 'The browser refused the clipboard.',
                tone: 'failed',
            },
        ])
    })

    it('offers only the save where the page cannot reach the clipboard', () => {
        vi.stubGlobal('isSecureContext', false)
        renderActions()

        expect(screen.queryByRole('button', { name: 'Copy Markdown' })).toBeNull()
        expect(screen.getByRole('button', { name: 'Save .md' })).toBeDefined()
    })
})
