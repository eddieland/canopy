import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { MAX_DRAFT_CHARS } from '@/lib/drafts'
import { renderRouted } from '@/test-utils'

import { DraftCardFrame, DraftForm, DraftVerbs, DropVerb, EditVerb } from './draft-card'

afterEach(cleanup)

// A form over its own text, as a card holds it, saving through `save`.
function Form({ save, onSaved }: { save: () => Promise<string>; onSaved: (saved: string) => void }) {
    const [text, setText] = useState('')
    return (
        <DraftForm
            label="Edit the draft"
            text={text}
            onText={setText}
            fits={text.trim() !== ''}
            save={save}
            onSaved={onSaved}
            onCancel={vi.fn<() => void>()}
        />
    )
}

describe('DraftCardFrame', () => {
    it('gives its verbs the same names on every card', async () => {
        const edit = vi.fn<() => void>()
        const drop = vi.fn<() => void>()
        await renderRouted(
            <DraftCardFrame waiting testId="draft" header={<span>Draft</span>}>
                <DraftVerbs>
                    <EditVerb onClick={edit} disabled={false} title="canopy draft edit" />
                    <DropVerb onClick={drop} disabled={false} title="canopy draft drop" />
                </DraftVerbs>
            </DraftCardFrame>,
        )
        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        fireEvent.click(screen.getByRole('button', { name: 'Drop' }))
        expect(edit).toHaveBeenCalledOnce()
        expect(drop).toHaveBeenCalledOnce()
        expect(screen.getByRole('button', { name: 'Edit' }).title).toBe('canopy draft edit')
    })
})

describe('DraftForm', () => {
    it('holds Save until the text fits, and saves what it holds', async () => {
        const save = vi.fn<() => Promise<string>>(() => Promise.resolve('saved'))
        const onSaved = vi.fn<(saved: string) => void>()
        await renderRouted(<Form save={save} onSaved={onSaved} />)
        const box = screen.getByRole('textbox', { name: 'In your words' })
        const button = screen.getByRole<HTMLButtonElement>('button', { name: /Save/u })
        expect(button.disabled).toBe(true)
        fireEvent.change(box, { target: { value: 'x'.repeat(MAX_DRAFT_CHARS + 1) } })
        expect(screen.getByText(`${MAX_DRAFT_CHARS + 1} of ${MAX_DRAFT_CHARS}`)).toBeTruthy()
        expect(button.disabled).toBe(true)
        fireEvent.change(box, { target: { value: 'Fine.' } })
        expect(button.disabled).toBe(false)
        fireEvent.click(button)
        await waitFor(() => {
            expect(onSaved).toHaveBeenCalledWith('saved')
        })
        expect(save).toHaveBeenCalledOnce()
    })
})
