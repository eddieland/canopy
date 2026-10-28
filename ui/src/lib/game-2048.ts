import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * 2048, an Easter egg (src/components/shell/game-2048.tsx): typed as 2-0-4-8 anywhere but a text field, it opens over
 * the page. Slide the tiles; two of a number that meet become their sum, and the sum is scored. The game in play and
 * the best games' scores are kept in localStorage, so a reload, or another tab, picks up where the last move left off.
 * Nothing here is journal text, and nothing reads or writes the journal.
 */

/** How many cells a side of the board has. */
export const SIZE = 4
/** The tile that wins: once made, the game says so once and plays on. */
export const GOAL = 2048
/** How many finished games the scores keep, the best first. */
export const SCORES_KEPT = 10
/** Where localStorage keeps the game. */
export const STORAGE_KEY = 'canopy-2048'

/** A way the tiles slide. */
export type Direction = 'up' | 'down' | 'left' | 'right'

/** A finished game, as the scores keep it. */
export interface Score {
    /** What the game scored. */
    score: number
    /** The largest tile it made. */
    tile: number
    /** When it ended, as an ISO time. */
    at: string
}

/** The game in play and the scores, as kept in this browser. */
export interface Saved {
    /** The board's cells, row by row from the top left; 0 is an empty cell. All empty before the first game. */
    board: readonly number[]
    /** What the game in play has scored. */
    score: number
    /** Whether the game in play has made the goal, so that it says so only once. */
    won: boolean
    /** Whether the game in play is already in the scores, as it is once it has no move left. */
    recorded: boolean
    /** The best finished games, the best first, at most `SCORES_KEPT`. */
    scores: readonly Score[]
}

/** What a slide did. */
export interface Slid {
    /** The board after it, before a new tile is added. */
    board: number[]
    /** What its merges scored. */
    gained: number
    /** The cells a merge made, by index. */
    merged: number[]
    /** Whether any tile moved; a slide that moves none is no move. */
    moved: boolean
}

/** Nothing saved: no game yet, no scores. */
export const EMPTY: Saved = {
    board: Array.from({ length: SIZE * SIZE }, () => 0),
    score: 0,
    won: false,
    recorded: false,
    scores: [],
}

/**
 * Slides every tile on `board` as far as it goes toward `direction`. Two equal tiles that meet merge into one of their
 * sum, which scores the sum; a tile merges once a slide, so 2 2 2 2 slides left to 4 4, not 8.
 */
export function slide(board: readonly number[], direction: Direction): Slid {
    const next = Array.from({ length: SIZE * SIZE }, () => 0)
    const merged: number[] = []
    let gained = 0
    for (let line = 0; line < SIZE; line++) {
        // The line's cells, from the edge the tiles slide toward.
        const cells = Array.from({ length: SIZE }, (_, i) => cellOf(direction, line, i))
        const tiles = cells.map((cell) => board[cell] ?? 0).filter((value) => value !== 0)
        let to = 0
        for (let i = 0; i < tiles.length; i++) {
            const value = tiles[i] ?? 0
            const cell = cells[to] ?? 0
            if (value === tiles[i + 1]) {
                next[cell] = value * 2
                gained += value * 2
                merged.push(cell)
                i++
            } else {
                next[cell] = value
            }
            to++
        }
    }
    return { board: next, gained, merged, moved: next.some((value, i) => value !== board[i]) }
}

/** Whether any slide would move a tile. */
export function canMove(board: readonly number[]): boolean {
    return DIRECTIONS.some((direction) => slide(board, direction).moved)
}

/**
 * `board` with a new tile in one of its empty cells: a 2 nine times in ten, else a 4, both picked by `random` (in
 * [0, 1), as `Math.random`). Returns the board and the cell, or the board as it was and null when no cell is empty.
 */
export function addTile(
    board: readonly number[],
    random: () => number = Math.random,
): { board: number[]; cell: number | null } {
    const empty = board.flatMap((value, i) => (value === 0 ? [i] : []))
    const cell = empty[Math.floor(random() * empty.length)]
    if (cell === undefined) {
        return { board: [...board], cell: null }
    }
    const next = [...board]
    next[cell] = random() < 0.9 ? 2 : 4
    return { board: next, cell }
}

/** A new game's board: two tiles on an empty one. */
export function newBoard(random: () => number = Math.random): number[] {
    return addTile(addTile(EMPTY.board, random).board, random).board
}

/** Whether `saved` holds a game: before the first, its board is empty. */
export function hasGame(saved: Saved): boolean {
    return saved.board.some((value) => value !== 0)
}

/** The largest tile on `board`. */
export function topTile(board: readonly number[]): number {
    return Math.max(0, ...board)
}

/** The best score: the best finished game's, or the game in play's if that is more. */
export function bestScore(saved: Saved): number {
    return Math.max(saved.score, ...saved.scores.map((s) => s.score))
}

/** `scores` with `score` among them, the best first, at most `SCORES_KEPT`. */
export function withScore(scores: readonly Score[], score: Score): Score[] {
    return [...scores, score].toSorted((a, b) => b.score - a.score).slice(0, SCORES_KEPT)
}

/**
 * The game after a slide toward `direction`: the merged tiles and their score, a new tile, and, once no move is left,
 * the game in the scores, ended `at`. A slide that moves no tile changes nothing, and neither does one on a game over.
 * Returns the game and the cells to show as new: the tile added and the merges.
 */
export function play(
    saved: Saved,
    direction: Direction,
    at: string,
    random: () => number = Math.random,
): { saved: Saved; added: number | null; merged: number[] } {
    const slid = slide(saved.board, direction)
    if (!slid.moved || saved.recorded) {
        return { saved, added: null, merged: [] }
    }
    const { board, cell } = addTile(slid.board, random)
    const score = saved.score + slid.gained
    const over = !canMove(board)
    const next: Saved = {
        board,
        score,
        won: saved.won || board.some((value) => value >= GOAL),
        recorded: over,
        scores: over ? withScore(saved.scores, { score, tile: topTile(board), at }) : saved.scores,
    }
    return { saved: next, added: cell, merged: slid.merged }
}

/**
 * A new game, the one in play put in the scores first, ended `at`, unless it is there already or scored nothing:
 * a game given up is still a game played.
 */
export function restart(saved: Saved, at: string, random: () => number = Math.random): Saved {
    const keep = !saved.recorded && saved.score > 0
    return {
        board: newBoard(random),
        score: 0,
        won: false,
        recorded: false,
        scores: keep ? withScore(saved.scores, { score: saved.score, tile: topTile(saved.board), at }) : saved.scores,
    }
}

/** The game as stored, or `EMPTY` for anything that is not a whole one. */
export function parseSaved(raw: string | null): Saved {
    if (raw === null) {
        return EMPTY
    }
    let value: unknown
    try {
        value = JSON.parse(raw)
    } catch {
        return EMPTY
    }
    if (typeof value !== 'object' || value === null) {
        return EMPTY
    }
    const { board, score, won, recorded, scores } = value as Record<string, unknown>
    if (
        !Array.isArray(board) ||
        board.length !== SIZE * SIZE ||
        !board.every((cell) => isTile(cell)) ||
        !isCount(score) ||
        typeof won !== 'boolean' ||
        typeof recorded !== 'boolean' ||
        !Array.isArray(scores)
    ) {
        return EMPTY
    }
    return { board, score, won, recorded, scores: scores.filter((s) => isScore(s)).slice(0, SCORES_KEPT) }
}

/** The game and scores, in a component. Re-renders on a move from this tab or another. */
export function useGame(): Saved {
    return useStoredSetting(setting)
}

/** The game and scores now, outside a component. */
export function getGame(): Saved {
    return setting.get()
}

/** Keeps `next` as the game and scores, and shows it now. */
export function setGame(next: Saved): void {
    setting.set(next)
}

const DIRECTIONS: readonly Direction[] = ['up', 'down', 'left', 'right']

const setting = storedSetting({
    key: STORAGE_KEY,
    parse: parseSaved,
    serialize: (value: Saved) => JSON.stringify(value),
})

// The board index of the `i`th cell of `line`, counted from the edge the tiles slide toward: a row for left and right,
// a column for up and down.
function cellOf(direction: Direction, line: number, i: number): number {
    switch (direction) {
        case 'left': {
            return line * SIZE + i
        }
        case 'right': {
            return line * SIZE + (SIZE - 1 - i)
        }
        case 'up': {
            return i * SIZE + line
        }
        case 'down': {
            return (SIZE - 1 - i) * SIZE + line
        }
    }
}

function isCount(value: unknown): value is number {
    return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

// An empty cell, or a power of two from 2 up.
function isTile(value: unknown): value is number {
    // Not by bits: they are 32, and a stored number may be larger.
    return isCount(value) && (value === 0 || (value >= 2 && Number.isInteger(Math.log2(value))))
}

function isScore(value: unknown): value is Score {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const { score, tile, at } = value as Record<string, unknown>
    return isCount(score) && isTile(tile) && typeof at === 'string' && !Number.isNaN(Date.parse(at))
}
