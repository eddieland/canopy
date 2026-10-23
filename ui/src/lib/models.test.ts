import { describe, expect, it } from 'vitest'

import { mockRuns } from '@/api/mocks'
import type { Run } from '@/api/types'

import { modelNames, runModelIds, unservedReason } from './models'

const [RUNNING, BLOCKED] = mockRuns as [Run, Run]

describe('modelNames', () => {
    it('drops the provider of a model no other provider names alike, its variant kept', () => {
        const names = modelNames(['anthropic/claude-opus-4-1@high', 'openai/gpt-5', 'openai/gpt-5', 'local'])
        expect([...names]).toEqual([
            ['anthropic/claude-opus-4-1@high', 'claude-opus-4-1@high'],
            ['openai/gpt-5', 'gpt-5'],
            ['local', 'local'],
        ])
    })

    it('keeps the whole id of a model two providers name alike', () => {
        const names = modelNames(['openai/gpt-5', 'azure/gpt-5', 'anthropic/claude-sonnet-4-5'])
        expect(names.get('openai/gpt-5')).toBe('openai/gpt-5')
        expect(names.get('azure/gpt-5')).toBe('azure/gpt-5')
        expect(names.get('anthropic/claude-sonnet-4-5')).toBe('claude-sonnet-4-5')
    })
})

describe('runModelIds', () => {
    it('takes what served each run and what canopy asked for', () => {
        const asked = { ...RUNNING, model: 'anthropic/claude-opus-4-1' }
        expect(runModelIds([asked, BLOCKED])).toEqual(['anthropic/claude-opus-4-1', 'anthropic/claude-sonnet-4-5'])
        expect(runModelIds([{ ...BLOCKED, models: null }])).toEqual([])
    })
})

describe('unservedReason', () => {
    it('says why no model is named until one is, a failed read with its error', () => {
        expect(unservedReason({ status: 'running', models: [], error: null })).toBe(
            'read from its session once it ends',
        )
        expect(unservedReason({ status: 'found', models: [], error: null })).toBe('its session made no model call')
        expect(unservedReason({ status: 'failed', models: [], error: 'timed out' })).toBe(
            'its session could not be read, tried again later (timed out)',
        )
        expect(unservedReason(BLOCKED.models ?? { status: 'unread', models: [], error: null })).toBeNull()
    })
})
