/**
 * What a chip's color says (ui/DESIGN.md, "Chips"): nothing, so plain, or the state of what it marks, in that state's
 * status color: broken work, what waits on the operator, or what the loop is about to act on.
 */
export type Tone = 'plain' | 'failed' | 'blocked' | 'running'
