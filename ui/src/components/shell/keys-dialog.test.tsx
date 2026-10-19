import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderRouted } from '@/test-utils'

import { KeysDialog } from './keys-dialog'

afterEach(() => {
    cleanup()
    localStorage.clear()
})

describe('KeysDialog', () => {
    it('lists the keys on ?, the send key as Settings sets it, and closes on Escape', async () => {
        await renderRouted(<KeysDialog />)
        expect(screen.queryByRole('dialog')).toBeNull()
        fireEvent.keyDown(document.body, { key: '?', shiftKey: true })

        const dialog = within(screen.getByRole('dialog', { name: 'Keys' }))
        expect(dialog.getByText('Search the journal')).toBeDefined()
        expect(dialog.getByText('Write in the reply, or the note, on the page')).toBeDefined()
        expect(dialog.getByText(/Find lines in a transcript/u)).toBeDefined()
        // Enter sends until Settings says otherwise.
        expect(dialog.getByText('Enter')).toBeDefined()
        expect(dialog.getByRole('link', { name: 'Settings' })).toBeDefined()

        fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
        expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('stays shut while ? is typed into a field', async () => {
        await renderRouted(<KeysDialog />)
        const field = document.createElement('input')
        document.body.append(field)
        fireEvent.keyDown(field, { key: '?', shiftKey: true })
        expect(screen.queryByRole('dialog')).toBeNull()
        field.remove()
    })
})
