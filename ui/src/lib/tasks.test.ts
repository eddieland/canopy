import { describe, expect, it } from 'vitest'

import { mockTaskRun, mockTasks } from '@/api/mocks'
import type { TaskSummary } from '@/api/types'

import { noReport, replyCommand, reportRun, TASK_LOOK, taskPrs, taskTitle, tasksShown } from './tasks'

/** The ids of `tasks`, in order. */
function ids(tasks: readonly TaskSummary[]) {
    return tasks.map((task) => task.id)
}

describe('taskTitle', () => {
    it("names a task by its text's first line that holds anything", () => {
        expect(taskTitle('Cut the bundle.\n\nWhat I know so far:')).toBe('Cut the bundle.')
        expect(taskTitle('\n  \n  Profile the dashboard.  \nThen say why.')).toBe('Profile the dashboard.')
        expect(taskTitle('   ')).toBe('   ')
    })
})

describe('tasksShown', () => {
    it('puts the tasks waiting on your reply first, then the rest newest first, as the server sends them', () => {
        // The server's order is the newest first: 7, 6, 4, 1; task 4 waits on a reply.
        expect(ids(mockTasks)).toEqual([7, 6, 4, 1])
        expect(ids(tasksShown(mockTasks, undefined))).toEqual([4, 7, 6, 1])
    })

    it('keeps the tasks in the repositories chosen', () => {
        expect(ids(tasksShown(mockTasks, 'web'))).toEqual([4, 1])
        expect(ids(tasksShown(mockTasks, 'api,mobile'))).toEqual([7, 6])
        expect(ids(tasksShown(mockTasks, 'docs'))).toEqual([])
    })
})

describe('reportRun', () => {
    it("shows the newest run's report that left one, though a later run left none", () => {
        const runs = [
            mockTaskRun({ id: 1, reported: true }),
            mockTaskRun({ id: 2, reported: true }),
            mockTaskRun({ id: 3, reported: false, status: 'running', state: 'running' }),
        ]
        expect(reportRun(runs)?.id).toBe(2)
        expect(reportRun([mockTaskRun({ reported: false })])).toBeUndefined()
    })
})

describe('noReport', () => {
    it('says what comes next, or that no run left one', () => {
        expect(noReport({ standing: 'queued' }, [])).toBe('no report yet: the next tick starts its first run')
        expect(noReport({ standing: 'stopped' }, [])).toBe('no report: it was stopped before its first run')
        const running = mockTaskRun({ status: 'running', state: 'running', reported: false })
        expect(noReport({ standing: 'running' }, [running])).toBe('no report yet: its run is working')
        const failed = mockTaskRun({ status: 'failed', state: 'failed', reported: false })
        expect(noReport({ standing: 'failed' }, [failed])).toBe('no report: its run left none')
        expect(noReport({ standing: 'failed' }, [failed, failed])).toBe('no report: none of its runs left one')
    })
})

describe('taskPrs', () => {
    it('names each PR once, in the order the runs first named it', () => {
        const a = 'https://github.com/acme/web/pull/97'
        const b = 'https://github.com/acme/web/pull/98'
        expect(taskPrs([mockTaskRun({ prs: [a] }), mockTaskRun({ prs: [b, a] })])).toEqual([a, b])
        expect(taskPrs([])).toEqual([])
    })
})

describe('replyCommand', () => {
    it('names the task as the CLI reads it', () => {
        expect(replyCommand(4)).toBe('canopy reply task:4')
    })
})

describe('TASK_LOOK', () => {
    it('reads a question waiting on you as the blocked state, in your words, and a queued task as muted', () => {
        expect(TASK_LOOK.awaiting_reply).toEqual({ state: 'blocked', word: 'waiting on you' })
        expect(TASK_LOOK.queued.state).toBe('stopped')
        expect(TASK_LOOK.crashed).toEqual({ state: 'failed', word: 'crashed' })
    })
})
