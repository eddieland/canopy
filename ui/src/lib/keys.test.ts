import { describe, expect, it } from 'vitest'

import { KEY_LINES, pageKeyOf, stepped, typing } from '@/lib/keys'

const PRESS = { key: 'j', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, isComposing: false }

describe('pageKeyOf', () => {
    it('names what each page key asks for, pressed alone', () => {
        const asked = ['j', 'k', 'r', 'f'].map((key) => pageKeyOf({ ...PRESS, key }, document.body))
        expect(asked).toEqual(['next', 'previous', 'reply', 'find'])
        // `?` is a shifted key on most keyboards.
        expect(pageKeyOf({ ...PRESS, key: '?', shiftKey: true }, document.body)).toBe('keys')
        expect(pageKeyOf({ ...PRESS, key: 'x' }, document.body)).toBeNull()
        expect(pageKeyOf(PRESS, null)).toBe('next')
    })

    it('leaves a key with a modifier, a capital, or a composition to the browser', () => {
        for (const held of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey', 'isComposing'] as const) {
            expect(pageKeyOf({ ...PRESS, [held]: true }, document.body)).toBeNull()
        }
        expect(pageKeyOf({ ...PRESS, key: '?', shiftKey: true, ctrlKey: true }, document.body)).toBeNull()
    })

    it('never takes a key typed into a field, or one a dialog or a menu reads', () => {
        for (const tag of ['input', 'textarea', 'select']) {
            expect(pageKeyOf(PRESS, document.createElement(tag))).toBeNull()
        }
        const editable = document.createElement('div')
        editable.contentEditable = 'true'
        document.body.append(editable)
        expect(pageKeyOf(PRESS, editable)).toBeNull()
        for (const role of ['dialog', 'alertdialog', 'menu', 'listbox']) {
            const holder = document.createElement('div')
            holder.setAttribute('role', role)
            const button = document.createElement('button')
            holder.append(button)
            expect(pageKeyOf(PRESS, button)).toBeNull()
        }
        expect(pageKeyOf(PRESS, document.createElement('button'))).toBe('next')
        editable.remove()
    })
})

describe('typing', () => {
    it('is true of what takes text alone', () => {
        expect(typing(document.createElement('textarea'))).toBe(true)
        expect(typing(document.createElement('a'))).toBe(false)
        expect(typing(null)).toBe(false)
    })
})

describe('stepped', () => {
    const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

    it('goes to the next or the previous item, held at either end', () => {
        expect(stepped(items, 'b', 1)?.id).toBe('c')
        expect(stepped(items, 'b', -1)?.id).toBe('a')
        expect(stepped(items, 'c', 1)).toBeNull()
        expect(stepped(items, 'a', -1)).toBeNull()
    })

    it('starts at the first item when none is current, and goes nowhere in an empty list', () => {
        expect(stepped(items, undefined, -1)?.id).toBe('a')
        expect(stepped(items, 'gone', 1)?.id).toBe('a')
        expect(stepped([], undefined, 1)).toBeNull()
    })
})

describe('KEY_LINES', () => {
    it('lists every key a page answers to, and the search box’s', () => {
        expect(KEY_LINES.flatMap((line) => line.keys)).toEqual(['/', 'j', 'k', 'r', 'f', '?'])
    })
})
