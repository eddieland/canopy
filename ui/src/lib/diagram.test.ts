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

    it('of another kind is refused, naming the kinds that are drawn', async () => {
        expect(await readDiagram('pie\n  "a": 1')).toEqual({
            error:
                'a pie diagram is not drawn here, only flowchart, sequenceDiagram, stateDiagram, classDiagram, ' +
                'and erDiagram',
        })
    })
})
