import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { MarkdownField } from './markdown-field'
import type { MarkdownPreview } from './markdown-field'

afterEach(cleanup)

// The field as a form holds it, starting from `initial`.
function Holder({
    initial,
    preview,
    onKeyDown,
}: {
    initial: string
    preview?: MarkdownPreview
    onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void
}) {
    const [value, setValue] = useState(initial)
    return (
        <MarkdownField
            aria-label="Reply"
            value={value}
            onValueChange={setValue}
            preview={preview}
            onKeyDown={onKeyDown}
        />
    )
}

function field(): HTMLTextAreaElement {
    return screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' })
}

function select(start: number, end = start) {
    field().setSelectionRange(start, end)
}

describe('MarkdownField', () => {
    it('offers only what the conversation draws, each with its shortcut', () => {
        render(<Holder initial="" />)
        const toolbar = screen.getByRole('toolbar', { name: 'Formatting' })
        const names = ['Bold', 'Code', 'Heading', 'Bulleted list', 'Numbered list', 'Code block']
        for (const name of names) {
            expect(screen.getByRole('button', { name })).toBeDefined()
        }
        expect(toolbar.textContent).toContain('Preview')
        expect(screen.getByRole('button', { name: 'Bold' }).getAttribute('aria-keyshortcuts')).toMatch(/\+B$/u)
    })

    it('formats the selection from the toolbar and keeps it selected', () => {
        render(<Holder initial="use the v2 API" />)
        select(4, 14)
        fireEvent.click(screen.getByRole('button', { name: 'Bold' }))
        expect(field().value).toBe('use **the v2 API**')
        expect([field().selectionStart, field().selectionEnd]).toEqual([6, 16])

        fireEvent.click(screen.getByRole('button', { name: 'Bulleted list' }))
        expect(field().value).toBe('- use **the v2 API**')
    })

    it('formats from the keyboard, and continues a list on Enter', () => {
        render(<Holder initial="- first" />)
        select(7)
        fireEvent.keyDown(field(), { key: 'Enter' })
        expect(field().value).toBe('- first\n- ')
        fireEvent.keyDown(field(), { key: 'Enter' })
        expect(field().value).toBe('- first\n')

        fireEvent.keyDown(field(), { key: 'e', ctrlKey: true })
        expect(field().value).toBe('- first\n``')
    })

    it('leaves Enter to a key handler that took it, such as the send key', () => {
        render(<Holder initial="- first" onKeyDown={(event) => event.preventDefault()} />)
        select(7)
        fireEvent.keyDown(field(), { key: 'Enter' })
        expect(field().value).toBe('- first')
    })

    it('gives a ref the caller passes the textarea, and still formats through its own', () => {
        const caller = createRef<HTMLTextAreaElement>()
        function WithRef() {
            const [value, setValue] = useState('word')
            return <MarkdownField aria-label="Reply" ref={caller} value={value} onValueChange={setValue} />
        }
        render(<WithRef />)
        expect(caller.current).toBe(field())
        select(0, 4)
        fireEvent.click(screen.getByRole('button', { name: 'Code' }))
        expect(field().value).toBe('`word`')
    })

    it('previews the text as it will read, and goes back to it', () => {
        render(<Holder initial="**Use** the `v2` API" />)
        fireEvent.click(screen.getByRole('radio', { name: 'Preview' }))
        const preview = screen.getByRole('region', { name: 'Preview' })
        expect(preview.textContent).toBe('Use the v2 API')
        expect(screen.getByText('Use').tagName).toBe('STRONG')
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Bold' }).disabled).toBe(true)

        fireEvent.click(screen.getByRole('radio', { name: 'Write' }))
        expect(screen.queryByRole('region', { name: 'Preview' })).toBeNull()
        expect(field().value).toBe('**Use** the `v2` API')
    })

    it('says when there is nothing to preview', () => {
        render(<Holder initial="  " />)
        fireEvent.click(screen.getByRole('radio', { name: 'Preview' }))
        expect(screen.getByRole('region', { name: 'Preview' }).textContent).toBe('nothing to preview yet')
    })

    it('previews live beside the text, with no toggle', () => {
        render(<Holder initial="- one" preview="live" />)
        expect(screen.queryByRole('radio', { name: 'Preview' })).toBeNull()
        expect(screen.getByRole('region', { name: 'Preview' }).textContent).toBe('one')
        fireEvent.change(field(), { target: { value: '- one\n- two' } })
        expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['one', 'two'])
    })
})
