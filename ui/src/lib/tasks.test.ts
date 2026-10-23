import { describe, expect, it } from 'vitest'

import { mockTasks } from '@/api/mocks'
import type { TaskSummary } from '@/api/types'

import { TASK_LOOK, taskTitle, tasksShown } from './tasks'

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

describe('TASK_LOOK', () => {
    it('reads a question waiting on you as the blocked state, in your words, and a queued task as muted', () => {
        expect(TASK_LOOK.awaiting_reply).toEqual({ state: 'blocked', word: 'waiting on you' })
        expect(TASK_LOOK.queued.state).toBe('stopped')
        expect(TASK_LOOK.crashed).toEqual({ state: 'failed', word: 'crashed' })
    })
})
