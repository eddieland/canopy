// One-click labels for a comment on a plan (docs/design/PLANNING.md §25, Commenting on a plan): each fills the comment
// with a fixed instruction to the planner, and the operator may write more after it. The wording is firm on purpose:
// a planner reads a soft remark ("maybe check this?") as one it may pass over, and Plannotator found Claude ignored its
// labels until they were worded as instructions. Each says what to do, in the imperative, and leaves no way out of it.

/** A label the operator puts on a comment with one click, and the instruction it writes there. */
export interface CommentLabel {
    /** What its button says, and how its instruction starts. */
    name: string
    /** The instruction to the planner it writes at the comment's start, whole. */
    instruction: string
}

/** The labels, in the order their buttons show. */
export const COMMENT_LABELS: readonly CommentLabel[] = [
    {
        name: 'Verify this',
        instruction:
            'Verify this: check the claim against the code and cite the file and line that confirm it. ' +
            'If you cannot confirm it, take it out of the plan.',
    },
    {
        name: 'Out of scope',
        instruction:
            'Out of scope: remove this from the plan. The ticket does not ask for it, so this change must not do it.',
    },
    {
        name: 'Match existing patterns',
        instruction:
            'Match existing patterns: find where the code already does this and do it the same way, naming the file ' +
            'you follow. Do not invent a new approach.',
    },
    {
        name: 'Needs tests',
        instruction:
            'Needs tests: add the tests this step needs to the plan, naming each test file and what each test ' +
            'checks. Do not leave this step untested.',
    },
]

/**
 * `body` led by `label`'s instruction, as a paragraph of its own, with the operator's words after it. An instruction
 * another label wrote at its start is replaced, not kept beside it, so a second click changes the label rather than
 * stacks two. With no words of the operator's yet, it ends on an empty paragraph, where theirs go.
 */
export function withLabel(body: string, label: CommentLabel): string {
    return `${label.instruction}\n\n${withoutLabel(body).trimStart()}`
}

// `body` without the instruction a label wrote at its start, if one did.
function withoutLabel(body: string): string {
    const lead = COMMENT_LABELS.find((label) => body.startsWith(label.instruction))
    return lead === undefined ? body : body.slice(lead.instruction.length)
}
