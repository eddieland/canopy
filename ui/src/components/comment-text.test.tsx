import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { CommentText } from './comment-text'

afterEach(cleanup)

const BODY = 'Missing guard.\n\n<details>\n<summary>Prompt for AI agents</summary>\n\nCheck `user` first.\n</details>'

describe('CommentText', () => {
    it('folds a <details> block under its summary until it is opened, its text plain', () => {
        render(<CommentText text={BODY} />)
        expect(screen.getByText('Missing guard.')).toBeTruthy()
        const toggle = screen.getByRole('button', { name: 'Prompt for AI agents' })
        expect(toggle.getAttribute('aria-expanded')).toBe('false')
        expect(screen.queryByText('Check `user` first.')).toBeNull()
        fireEvent.click(toggle)
        expect(toggle.getAttribute('aria-expanded')).toBe('true')
        // Never Markdown: the backticks stay characters.
        expect(screen.getByText('Check `user` first.')).toBeTruthy()
        expect(document.body.textContent).not.toContain('<details>')
    })

    it('opens a block written open', () => {
        render(<CommentText text={'<details open><summary>Why</summary>\nBecause.\n</details>'} />)
        expect(screen.getByRole('button', { name: 'Why' }).getAttribute('aria-expanded')).toBe('true')
        expect(screen.getByText('Because.')).toBeTruthy()
    })

    it('says a closed block hides a character, and names it once opened', () => {
        render(<CommentText text={'<details><summary>Notes</summary>\nok​now\n</details>'} />)
        const toggle = screen.getByRole('button', { name: /^Notes/u })
        expect(screen.getByText('hides a character')).toBeTruthy()
        fireEvent.click(toggle)
        expect(screen.getByText('<U+200B>')).toBeTruthy()
    })
})
