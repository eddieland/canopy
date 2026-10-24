/**
 * What a chip's color says (ui/DESIGN.md, "Chips"): nothing, so plain, or the state of what it marks, in that state's
 * status color: broken work, what waits on the operator, or what the loop is about to act on.
 */
export type Tone = 'plain' | 'failed' | 'blocked' | 'running'

/**
 * A feedback plan's proposal for an item, as a chip's color (ui/DESIGN.md, "Chips"): what the plan would do with it,
 * never a state, each in a quiet hue of its own, `change`, the one that edits code, the loudest, and `leave` plain.
 */
export type ProposalTone = 'change' | 'decline' | 'ask' | 'leave'
