import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ToastContext } from '@/hooks/use-toast'
import { saveFile } from '@/lib/save-file'
import type { NewToast } from '@/lib/toasts'

import { PlanFileMenu } from './plan-file-menu'

vi.mock(import('@/lib/save-file'), async (importOriginal) => ({
    ...(await importOriginal()),
    saveFile: vi.fn<typeof saveFile>(),
}))

let toasts: NewToast[] = []

function renderMenu(markdown: () => string, unsaved = false) {
    return render(
        <ToastContext
            value={(toast) => {
                toasts.push(toast)
            }}
        >
            <PlanFileMenu markdown={markdown} file="412-APPROVED-export-reports-as-csv.md" unsaved={unsaved} />
        </ToastContext>,
    )
}

// Picks `item` from the menu, as a click on its button and then on the item does.
async function pick(item: string): Promise<void> {
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Copy or save the plan' }), { button: 0, ctrlKey: false })
    fireEvent.click(await screen.findByRole('menuitem', { name: item }))
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

describe("a plan's Markdown, whole", () => {
    it('is copied as the page shows it when the item is picked, not as it was first drawn', async () => {
        const write = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
        let shown = '# Plan\n'
        renderMenu(() => shown)
        shown = '# Plan\n\nEdited.\n'
        await pick('Copy as Markdown')
        expect(write).toHaveBeenCalledWith('# Plan\n\nEdited.\n')
        expect(toasts).toEqual([
            { title: 'Copied the plan as Markdown', detail: '412-APPROVED-export-reports-as-csv.md', tone: 'done' },
        ])
    })

    it("is saved under canopy archive's name, and says when it carries edits not saved", async () => {
        renderMenu(() => '# Plan\n', true)
        await pick('Save as .md')
        const [blob, name] = vi.mocked(saveFile).mock.lastCall ?? []
        expect(name).toBe('412-APPROVED-export-reports-as-csv.md')
        expect(await blob?.text()).toBe('# Plan\n')
        expect(toasts).toEqual([
            {
                title: 'Saved the plan',
                detail: '412-APPROVED-export-reports-as-csv.md, with your edits, not saved yet',
                tone: 'done',
            },
        ])
    })

    it('is offered only to save where the page cannot reach the clipboard', async () => {
        vi.stubGlobal('isSecureContext', false)
        renderMenu(() => '# Plan\n')
        fireEvent.pointerDown(screen.getByRole('button', { name: 'Copy or save the plan' }), {
            button: 0,
            ctrlKey: false,
        })
        expect(await screen.findByRole('menuitem', { name: 'Save as .md' })).toBeDefined()
        expect(screen.queryByRole('menuitem', { name: 'Copy as Markdown' })).toBeNull()
    })
})
