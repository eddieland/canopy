import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab } from '@/test-utils'

import {
    addTile,
    bestScore,
    canMove,
    EMPTY,
    hasGame,
    newBoard,
    parseSaved,
    play,
    restart,
    SCORES_KEPT,
    slide,
    withScore,
} from './game-2048'
import type { Saved } from './game-2048'

// The setting is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./game-2048')
}

// A board from its rows, top first.
function rows(...lines: number[][]): number[] {
    return lines.flat()
}

// Always the first empty cell, and always a 2.
const FIRST_TWO = () => 0

// A game on `board`, scoring `score`, with no scores yet.
function game(board: number[], score = 0): Saved {
    return { ...EMPTY, board, score }
}

const AT = '2026-10-08T12:00:00Z'

describe('slide', () => {
    it('slides tiles to the edge and merges equal ones, scoring the sum', () => {
        const slid = slide(rows([2, 2, 0, 4], [0, 0, 0, 2], [4, 4, 4, 4], [2, 4, 8, 16]), 'left')
        expect(slid.board).toEqual(rows([4, 4, 0, 0], [2, 0, 0, 0], [8, 8, 0, 0], [2, 4, 8, 16]))
        expect(slid.gained).toBe(4 + 8 + 8)
        expect(slid.merged).toEqual([0, 8, 9])
        expect(slid.moved).toBe(true)
    })

    it('merges a tile once a slide, the pair nearest the edge first', () => {
        expect(slide(rows([2, 2, 2, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]), 'right').board.slice(0, 4)).toEqual([
            0, 0, 2, 4,
        ])
        expect(slide(rows([4, 4, 8, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]), 'left').board.slice(0, 4)).toEqual([
            8, 8, 0, 0,
        ])
    })

    it('slides columns up and down', () => {
        const board = rows([2, 0, 0, 0], [2, 0, 0, 0], [0, 0, 0, 0], [4, 0, 0, 2])
        expect(slide(board, 'up').board).toEqual(rows([4, 0, 0, 2], [4, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]))
        expect(slide(board, 'down').board).toEqual(rows([0, 0, 0, 0], [0, 0, 0, 0], [4, 0, 0, 0], [4, 0, 0, 2]))
    })

    it('is no move when nothing can slide that way', () => {
        const slid = slide(rows([2, 4, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]), 'left')
        expect(slid.moved).toBe(false)
        expect(slid.gained).toBe(0)
    })
})

describe('canMove', () => {
    it('is true with an empty cell or two equal neighbours, false on a locked board', () => {
        const locked = rows([2, 4, 2, 4], [4, 2, 4, 2], [2, 4, 2, 4], [4, 2, 4, 2])
        expect(canMove(locked)).toBe(false)
        expect(canMove(locked.with(15, 4))).toBe(true)
        expect(canMove(locked.with(15, 0))).toBe(true)
    })
})

describe('addTile', () => {
    it('puts a 2, or a 4 one time in ten, in an empty cell', () => {
        const board = rows([2, 0, 2, 0], [2, 2, 2, 2], [2, 2, 2, 2], [2, 2, 2, 2])
        expect(addTile(board, () => 0)).toEqual({ board: board.with(1, 2), cell: 1 })
        expect(addTile(board, () => 0.95)).toEqual({ board: board.with(3, 4), cell: 3 })
    })

    it('adds nothing to a full board', () => {
        const full = Array.from({ length: 16 }, () => 2)
        expect(addTile(full)).toEqual({ board: full, cell: null })
    })

    it('starts a game with two tiles', () => {
        expect(newBoard().filter((value) => value !== 0)).toHaveLength(2)
        expect(hasGame(EMPTY)).toBe(false)
    })
})

describe('play', () => {
    it('slides, scores, and adds a tile', () => {
        const before = game(rows([2, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]), 10)
        const { saved, added, merged } = play(before, 'left', AT, FIRST_TWO)
        expect(saved.board).toEqual(rows([4, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]))
        expect(saved.score).toBe(14)
        expect(added).toBe(1)
        expect(merged).toEqual([0])
    })

    it('changes nothing on a slide that moves no tile', () => {
        const before = game(rows([2, 4, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]))
        expect(play(before, 'left', AT).saved).toBe(before)
    })

    it('puts the game in the scores once no move is left, and plays no further', () => {
        // Sliding left merges the two 2s, and the 4 added on the right locks the board.
        const before = game(rows([2, 2, 8, 16], [2, 4, 8, 32], [8, 16, 32, 64], [16, 32, 64, 128]), 100)
        const { saved } = play(before, 'left', AT, () => 0.95)
        expect(saved.board.slice(0, 4)).toEqual([4, 8, 16, 4])
        expect(saved.recorded).toBe(true)
        expect(saved.scores).toEqual([{ score: 104, tile: 128, at: AT }])
        expect(play(saved, 'right', AT).saved).toBe(saved)
    })

    it('marks the goal made', () => {
        const before = game(rows([1024, 1024, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]))
        expect(play(before, 'left', AT, FIRST_TWO).saved.won).toBe(true)
    })
})

describe('restart', () => {
    it('keeps a game given up in the scores, and starts afresh', () => {
        const before = game(rows([2, 64, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]), 300)
        const after = restart(before, AT)
        expect(after.score).toBe(0)
        expect(after.board.filter((value) => value !== 0)).toHaveLength(2)
        expect(after.scores).toEqual([{ score: 300, tile: 64, at: AT }])
    })

    it('keeps no game twice, nor one that scored nothing', () => {
        const over = { ...game(newBoard(), 50), recorded: true, scores: [{ score: 50, tile: 8, at: AT }] }
        expect(restart(over, AT).scores).toEqual(over.scores)
        expect(restart(game(newBoard()), AT).scores).toEqual([])
    })
})

describe('withScore and bestScore', () => {
    it('keeps the best games, best first', () => {
        let scores = withScore([], { score: 1, tile: 2, at: AT })
        for (let i = 2; i <= SCORES_KEPT + 3; i++) {
            scores = withScore(scores, { score: i * 10, tile: 2, at: AT })
        }
        expect(scores).toHaveLength(SCORES_KEPT)
        expect(scores[0]?.score).toBe((SCORES_KEPT + 3) * 10)
        expect(scores.at(-1)?.score).toBe(40)
        expect(bestScore({ ...EMPTY, score: 5, scores })).toBe(130)
        expect(bestScore({ ...EMPTY, score: 500, scores })).toBe(500)
    })
})

describe('parseSaved', () => {
    it('reads a whole game back', () => {
        const saved = restart(game(newBoard(), 20), AT)
        expect(parseSaved(JSON.stringify(saved))).toEqual(saved)
    })

    it('is empty for nothing stored and anything that is not a whole game', () => {
        expect(parseSaved(null)).toBe(EMPTY)
        expect(parseSaved('not json')).toBe(EMPTY)
        expect(parseSaved('[]')).toBe(EMPTY)
        expect(parseSaved(JSON.stringify({ ...EMPTY, board: [2, 4] }))).toBe(EMPTY)
        expect(parseSaved(JSON.stringify({ ...EMPTY, board: EMPTY.board.with(0, 3) }))).toBe(EMPTY)
        expect(parseSaved(JSON.stringify({ ...EMPTY, score: -1 }))).toBe(EMPTY)
        expect(parseSaved(JSON.stringify({ ...EMPTY, board: EMPTY.board.with(0, 2 ** 32 + 2) }))).toBe(EMPTY)
    })

    it('drops a score that is not one', () => {
        const scores = [{ score: 10, tile: 8, at: AT }, { score: 'lots' }, { score: 5, tile: 4, at: 'yesterday' }]
        expect(parseSaved(JSON.stringify({ ...EMPTY, scores })).scores).toEqual([scores[0]])
    })
})

describe('useGame', () => {
    beforeEach(() => localStorage.clear())

    it('keeps each move in this browser, and follows another tab', async () => {
        const store = await load()
        const { result } = renderHook(() => store.useGame())
        expect(result.current).toEqual(EMPTY)

        const started = restart(EMPTY, AT)
        act(() => store.setGame(started))
        expect(result.current).toEqual(started)
        expect(parseSaved(localStorage.getItem(store.STORAGE_KEY))).toEqual(started)

        const elsewhere = { ...started, score: 64 }
        act(() => otherTab(store.STORAGE_KEY, JSON.stringify(elsewhere)))
        expect(result.current.score).toBe(64)
    })

    it('still plays where storage is unavailable', async () => {
        breakStorage()
        try {
            const store = await load()
            const { result } = renderHook(() => store.useGame())
            const started = restart(EMPTY, AT)
            act(() => store.setGame(started))
            expect(result.current).toEqual(started)
        } finally {
            vi.unstubAllGlobals()
        }
    })
})
