import { describe, expect, it } from 'vitest'

import { mockRuns } from '@/api/mocks'
import type { Run } from '@/api/types'

import { modelNames, pickerModel, ranOn, runModelIds, sameModel, unservedReason, withVariant } from './models'

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

    it('keeps whole a model a gateway and its maker both serve, short when one alone does', () => {
        const both = modelNames(['github-copilot/claude-sonnet-4.5@high', 'anthropic/claude-sonnet-4.5@high'])
        expect([...both.values()]).toEqual([
            'github-copilot/claude-sonnet-4.5@high',
            'anthropic/claude-sonnet-4.5@high',
        ])
        const alone = modelNames(['github-copilot/claude-sonnet-4.5', 'github-copilot/gpt-5'])
        expect([...alone.values()]).toEqual(['claude-sonnet-4.5', 'gpt-5'])
    })
})

describe('pickerModel', () => {
    it('sets a variant apart as canopy reads one, never a dated id', () => {
        expect(pickerModel(null)).toEqual({ model: null, variant: null })
        expect(pickerModel('acme/deep-2')).toEqual({ model: 'acme/deep-2', variant: null })
        expect(pickerModel('acme/deep-2@high')).toEqual({ model: 'acme/deep-2@high', variant: 'high' })
        expect(pickerModel('vendor/claude-x@20250101')).toEqual({ model: 'vendor/claude-x@20250101', variant: null })
        expect(pickerModel('vendor/claude-x@20250101@max')).toEqual({
            model: 'vendor/claude-x@20250101@max',
            variant: 'max',
        })
    })
})

describe('withVariant', () => {
    it('joins a model and its variant as one id, the model alone at its default', () => {
        expect(withVariant('github-copilot/gpt-5', 'high')).toBe('github-copilot/gpt-5@high')
        expect(withVariant('github-copilot/claude-sonnet-4.5', null)).toBe('github-copilot/claude-sonnet-4.5')
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

describe('ranOn', () => {
    it('keeps a run a model served, or, until its session names one, the model canopy asked for', () => {
        expect(ranOn(BLOCKED, 'anthropic/claude-sonnet-4-5')).toBe(true)
        expect(ranOn({ ...BLOCKED, model: 'anthropic/claude-opus-4-1' }, 'anthropic/claude-opus-4-1')).toBe(false)
        expect(ranOn({ ...RUNNING, model: 'anthropic/claude-opus-4-1' }, 'anthropic/claude-opus-4-1')).toBe(true)
        expect(ranOn(RUNNING, 'anthropic/claude-opus-4-1')).toBe(false)
    })
})

describe('sameModel', () => {
    it('takes a model asked for at a variant as served by the model alone, as its session names the default', () => {
        expect(sameModel('openai/gpt-5', 'openai/gpt-5')).toBe(true)
        expect(sameModel('openai/gpt-5@medium', 'openai/gpt-5')).toBe(true)
        expect(sameModel('openai/gpt-5@high', 'openai/gpt-5@high')).toBe(true)
    })

    it('tells apart another model, another variant, and a variant served when none was asked for', () => {
        expect(sameModel('openai/gpt-5', 'openai/gpt-5-mini')).toBe(false)
        expect(sameModel('openai/gpt-5@high', 'openai/gpt-5@low')).toBe(false)
        expect(sameModel('openai/gpt-5', 'openai/gpt-5@high')).toBe(false)
        // An `@` in the provider is no variant.
        expect(sameModel('me@corp/model', 'me')).toBe(false)
    })
})
