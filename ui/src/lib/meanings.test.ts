import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { PHASE_MEANINGS, phaseMeaning, reasonMeaning } from './meanings'

// The phases canopy records, read from the Python vocabulary they are written through (`core/vocab.py`).
const vocab = readFileSync(resolve(import.meta.dirname, '../../../src/canopy/core/vocab.py'), 'utf8')
const phaseClass = /class Phase\(StrEnum\):(?<body>[\s\S]*?)\n\n\n/u.exec(vocab)?.groups?.body ?? ''
const phases = [...phaseClass.matchAll(/^ {4}[A-Z_]+ = "(?<value>[a-z_]+)"$/gmu)].map((m) => m.groups?.value)

describe('meanings', () => {
    it('says what every phase canopy records means', () => {
        expect(phases.length).toBeGreaterThan(10)
        expect(new Set(phases)).toEqual(new Set(Object.keys(PHASE_MEANINGS)))
    })

    it('has none for a reason or a phase it does not know, nor for no phase', () => {
        expect(reasonMeaning('review_late')).toMatch(/unchanged since the PR’s first review/u)
        expect(reasonMeaning('unobserved_pr')).toMatch(/no source reads it/u)
        expect(reasonMeaning('the_overseers_own')).toBeNull()
        expect(phaseMeaning('ci_red')).toBe('Its PR’s checks failed.')
        expect(phaseMeaning('not_a_phase')).toBeNull()
        expect(phaseMeaning(null)).toBeNull()
        // A word an object inherits a property by is no meaning of canopy's.
        expect(reasonMeaning('constructor')).toBeNull()
        expect(phaseMeaning('toString')).toBeNull()
    })
})
