// Names for the generated API types. Import from here, not from schema.gen.ts, so call sites read as the domain.
import type { components } from './schema.gen'

type Schemas = components['schemas']

export type Meta = Schemas['Meta']
export type Session = Schemas['Session']
export type AttentionItem = Schemas['AttentionItem']
export type Run = Schemas['Run']
export type RunState = Schemas['RunState']
export type TicketSummary = Schemas['TicketSummary']
export type TicketDetail = Schemas['TicketDetail']
export type Message = Schemas['Message']
export type Unit = Schemas['Unit']
export type Refusal = Schemas['Refusal']
export type Started = Schemas['Started']
export type Stopped = Schemas['Stopped']
export type Replied = Schemas['Replied']
export type Forgot = Schemas['Forgot']
export type StreamEvent = Schemas['StreamEvent']
export type Pool = Schemas['Pool']
export type Spend = Schemas['Spend']
export type Tick = Schemas['Tick']
export type LastTick = Schemas['LastTick']
export type TickDetail = Schemas['TickDetail']
export type Decision = Schemas['Decision']
export type Worktree = Schemas['Worktree']
export type WorktreeState = Schemas['WorktreeState']
export type ChoreSummary = Schemas['ChoreSummary']
export type ChoreDetail = Schemas['ChoreDetail']
export type ChoreRun = Schemas['ChoreRun']
export type ChoreFinding = Schemas['ChoreFinding']
export type Transcript = Schemas['Transcript']
export type TranscriptEntry = Transcript['entries'][number]
export type TranscriptTool = Schemas['TranscriptTool']

// Every state, in display order. `satisfies` fails the typecheck if the schema gains a state these miss.
export const RUN_STATES = ['running', 'blocked', 'failed', 'stopped', 'done'] as const satisfies readonly RunState[]

// Every worktree state, in display order.
export const WORKTREE_STATES = [
    'working',
    'held',
    'dirty',
    'idle',
    'broken',
] as const satisfies readonly WorktreeState[]
