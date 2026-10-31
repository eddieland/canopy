import { describe, expect, it } from 'vitest'

import { NO_PICKS, pickCount, startRequest, withPick } from './start-picks'

describe('start picks', () => {
    it('sends nothing for a start that picks nothing', () => {
        expect(startRequest(NO_PICKS)).toEqual({ personas: [], models: [] })
        expect(pickCount(NO_PICKS)).toBe(0)
    })

    it('sends each pick once, in the order a ticket meets its agents', () => {
        let picks = withPick(NO_PICKS, 'personas', 'reviewer', 'skeptic')
        picks = withPick(picks, 'personas', 'planner', 'explainer')
        picks = withPick(picks, 'models', 'worker', 'acme/fake-model-1@high')
        picks = withPick(picks, 'personas', 'planner', 'minimalist')
        expect(startRequest(picks)).toEqual({
            personas: [
                { agent: 'planner', persona: 'minimalist' },
                { agent: 'reviewer', persona: 'skeptic' },
            ],
            models: [{ agent: 'worker', model: 'acme/fake-model-1@high' }],
        })
        expect(pickCount(picks)).toBe(3)
    })

    it('drops a pick set back to the default', () => {
        const picks = withPick(withPick(NO_PICKS, 'models', 'planner', 'acme/fake-model-1'), 'models', 'planner', null)
        expect(picks).toEqual(NO_PICKS)
    })
})
