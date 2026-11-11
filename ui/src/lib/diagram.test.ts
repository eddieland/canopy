import { describe, expect, it } from 'vitest'

import { readDiagram } from './diagram'

describe('a Mermaid diagram', () => {
    it.each([
        ['a flowchart', 'flowchart LR\n  A --> B'],
        ['a sequence diagram', 'sequenceDiagram\n  A->>B: hello'],
        ['a state diagram', 'stateDiagram-v2\n  [*] --> Queued'],
        ['a class diagram', 'classDiagram\n  class Run {\n    +str status\n  }\n  Run --> Ticket'],
        ['an entity relationship diagram', 'erDiagram\n  TICKET ||--o{ RUN : has\n  RUN {\n    int id\n  }'],
    ])('is read when it is %s', async (_kind, source) => {
        expect(await readDiagram(source)).toBeUndefined()
    })

    // The planners mark what a plan adds or changes `(new)` or `(changed)`: a bare parenthesis is syntax in a
    // flowchart, a class diagram, and an ER diagram, so their prompts quote the label, which each of these reads.
    it.each([
        ['a flowchart node', 'flowchart LR\n  A["Dispatch (new)"] --> B'],
        ['a flowchart edge', 'flowchart LR\n  A -->|"calls (changed)"| B'],
        ['a sequence participant', 'sequenceDiagram\n  participant A as Dispatch (new)\n  A->>B: lease (new)'],
        ['a state', 'stateDiagram-v2\n  Q: Queued (new)\n  [*] --> Q'],
        ['a class', 'classDiagram\n  class Run["Run (changed)"]\n  Run --> Ticket'],
        ['an entity and a relationship', 'erDiagram\n  "RUN (new)" ||--o{ TICKET : "has (new)"'],
    ])('reads a marked label on %s', async (_part, source) => {
        expect(await readDiagram(source)).toBeUndefined()
    })

    it('of another kind is refused, naming the kinds that are drawn', async () => {
        expect(await readDiagram('pie\n  "a": 1')).toEqual({
            error: 'pie is not drawn here, only flowchart, sequenceDiagram, stateDiagram, classDiagram, and erDiagram',
        })
    })
})
