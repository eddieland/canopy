// Typed fixtures for unit tests, mirroring canopy/serve/mock.py. The sessions and leases endpoints have no real
// source yet (ROADMAP M20); the dev server and the end-to-end tests get the same shapes from `--mock`.
import type { Lease, Session } from './types'

export const mockSessions: Session[] = [
    {
        id: 'run:41',
        subject: 'ABC-101',
        kind: 'worker',
        state: 'running',
        started_at: '2026-10-08T12:00:00Z',
        updated_at: '2026-10-08T12:12:00Z',
        ended_at: null,
        cost_usd: 0.42,
        lease_id: 'lease:1',
    },
    {
        id: 'run:42',
        subject: 'ABC-102',
        kind: 'worker',
        state: 'blocked',
        started_at: '2026-10-08T11:30:00Z',
        updated_at: '2026-10-08T11:56:00Z',
        ended_at: null,
        cost_usd: 1.07,
        lease_id: 'lease:2',
    },
]

export const mockLeases: Lease[] = [
    {
        id: 'lease:1',
        repo: 'acme/web',
        path: '~/.treehouse/web-1',
        state: 'held',
        session_id: 'run:41',
        acquired_at: '2026-10-08T12:00:00Z',
        expires_at: '2026-10-08T13:00:00Z',
    },
]
