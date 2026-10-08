// Names for the generated API types. Import from here, not from schema.gen.ts, so call sites read as the domain.
import type { components } from './schema.gen'

type Schemas = components['schemas']

export type Meta = Schemas['Meta']
export type Session = Schemas['Session']
export type SessionState = Schemas['SessionState']
export type Lease = Schemas['Lease']
export type LeaseState = Schemas['LeaseState']
export type StreamEvent = Schemas['StreamEvent']

// Every state, in display order. `satisfies` fails the typecheck if the schema gains a state these miss.
export const SESSION_STATES = [
    'running',
    'blocked',
    'idle',
    'done',
    'failed',
] as const satisfies readonly SessionState[]
export const LEASE_STATES = ['held', 'expiring', 'released'] as const satisfies readonly LeaseState[]
