import { describe, expect, it } from 'vitest'

import { wholePath } from './whole-path'

describe('wholePath', () => {
    it('joins a path shown from the workspace root to it', () => {
        expect(wholePath('.treehouse/web-3f9c2a1b/1/web', '/home/op/work')).toBe(
            '/home/op/work/.treehouse/web-3f9c2a1b/1/web',
        )
        expect(wholePath('desks/ABC-1', '/home/op/work/')).toBe('/home/op/work/desks/ABC-1')
    })

    it('gives the root itself for the root', () => {
        expect(wholePath('.', '/home/op/work')).toBe('/home/op/work')
        expect(wholePath('.', '/')).toBe('/')
    })

    it('leaves a path outside the workspace as the server sent it', () => {
        expect(wholePath('/home/op/.canopy/runs/41.log', '/home/op/work')).toBe('/home/op/.canopy/runs/41.log')
    })
})
