import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { EMPTY, getGame, parseSaved, setGame, STORAGE_KEY } from '@/lib/game-2048'
import type { Saved } from '@/lib/game-2048'

import { Game2048 } from './game-2048'

// Types `text` a key at a time, at whatever has the focus, or the window when nothing does.
function type(text: string, target: Element | Window = document.activeElement ?? globalThis.window) {
    for (const key of text) {
        fireEvent.keyDown(target, { key })
    }
}

// The numbers on the board, row by row, 0 for an empty cell.
function board(): number[] {
    const cells = within(screen.getByRole('list', { name: 'Board' })).getAllByRole('listitem')
    return cells.map((cell) => Number(cell.textContent))
}

// A game on a board of two 2s side by side, scoring `score`.
function pair(score = 0): Saved {
    return { ...EMPTY, board: EMPTY.board.with(0, 2).with(1, 2), score }
}

describe('Game2048', () => {
    beforeEach(() => {
        localStorage.clear()
        act(() => setGame(EMPTY))
        // Each new tile is a 4, in the last empty cell, so a test knows the board a move leaves.
        vi.spyOn(Math, 'random').mockReturnValue(0.95)
    })
    afterEach(() => {
        cleanup()
        vi.restoreAllMocks()
    })

    it('opens when 2048 is typed away from a field, with a game started', () => {
        render(<Game2048 />)
        expect(screen.queryByRole('dialog')).toBeNull()

        type('2048', globalThis.window)
        expect(screen.getByRole('dialog', { name: '2048' })).toBeTruthy()
        expect(board().filter((value) => value !== 0)).toHaveLength(2)
        expect(screen.getByText('Finished games show up here.')).toBeTruthy()
    })

    it('stays shut when 2048 is typed in a text field', () => {
        render(
            <>
                <input aria-label="Search" />
                <Game2048 />
            </>,
        )
        type('2048', screen.getByRole('textbox', { name: 'Search' }))
        expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('slides with the arrow keys and WASD, keeping each move and the score', () => {
        act(() => setGame(pair(12)))
        render(<Game2048 />)
        type('2048', globalThis.window)

        fireEvent.keyDown(screen.getByRole('dialog'), { key: 'ArrowRight' })
        expect(board().slice(0, 4)).toEqual([0, 0, 0, 4])
        expect(within(screen.getByRole('dialog')).getAllByText('16')).toHaveLength(2)
        expect(parseSaved(localStorage.getItem(STORAGE_KEY)).score).toBe(16)

        // The 4 added in the last cell slides left with the first row's, and a new one takes its place.
        fireEvent.keyDown(screen.getByRole('dialog'), { key: 'a' })
        expect(board().slice(0, 4)).toEqual([4, 0, 0, 0])
        expect(board().slice(12)).toEqual([4, 0, 0, 4])
    })

    it('picks the game back up where it was left', () => {
        act(() => setGame(pair(40)))
        render(<Game2048 />)
        type('2048', globalThis.window)
        fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
        expect(screen.queryByRole('dialog')).toBeNull()

        type('2048', globalThis.window)
        expect(board().slice(0, 2)).toEqual([2, 2])
        expect(within(screen.getByRole('dialog')).getAllByText('40')).toHaveLength(2)
    })

    it('puts a game given up for a new one in the best games', () => {
        act(() => setGame(pair(40)))
        render(<Game2048 />)
        type('2048', globalThis.window)

        fireEvent.click(screen.getByRole('button', { name: 'New game' }))
        expect(getGame().score).toBe(0)
        const best = within(screen.getByRole('region', { name: 'Best games' })).getAllByRole('listitem')
        expect(best).toHaveLength(1)
        expect(best[0]?.textContent).toContain('40')
        expect(getGame().scores.map(({ score, tile }) => ({ score, tile }))).toEqual([{ score: 40, tile: 2 }])
    })
})
