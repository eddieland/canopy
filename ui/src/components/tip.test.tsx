import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { tipOf } from '@/test-utils'

import { Clipped, Hinted, Tip } from './tip'

afterEach(() => {
    cleanup()
})

describe('Tip', () => {
    it("opens its fact on the keyboard's focus, and makes what it wraps a stop for the keyboard", () => {
        render(
            <Tip fact="Oct 8, 10:30">
                <time>3m ago</time>
            </Tip>,
        )
        const age = screen.getByText('3m ago')
        expect(age.tabIndex).toBe(0)
        expect(tipOf(age)).toBe('Oct 8, 10:30')
        expect(age.title).toBe('')
    })

    it('closes on Escape', () => {
        render(
            <Tip fact="worker_failed">
                <span>worker failed</span>
            </Tip>,
        )
        expect(tipOf(screen.getByText('worker failed'))).toBe('worker_failed')
        fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
        expect(screen.queryByRole('tooltip')).toBeNull()
    })

    it('stays open through the scroll its focus causes in a scrolling panel', () => {
        render(
            <div data-testid="panel">
                <Tip fact="Oct 8, 10:30">
                    <time>3m ago</time>
                </Tip>
            </div>,
        )
        expect(tipOf(screen.getByText('3m ago'))).toBe('Oct 8, 10:30')
        fireEvent.scroll(screen.getByTestId('panel'))
        expect(screen.queryByRole('tooltip')?.textContent).toBe('Oct 8, 10:30')
        fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
        expect(screen.queryByRole('tooltip')).toBeNull()
    })

    it('toggles on a tap, which a touch screen has in place of hover and focus', () => {
        render(
            <Tip fact="ci_failing">
                <span>ci failing</span>
            </Tip>,
        )
        const word = screen.getByText('ci failing')
        const tap = () => {
            fireEvent.pointerDown(word, { pointerType: 'touch' })
            fireEvent.click(word)
        }
        tap()
        expect(screen.getByRole('tooltip').textContent).toBe('ci_failing')
        tap()
        expect(screen.queryByRole('tooltip')).toBeNull()
    })

    it('is its child alone when it has no fact: no stop for the keyboard', () => {
        render(
            <Tip fact={null}>
                <span>ok</span>
            </Tip>,
        )
        const word = screen.getByText('ok')
        expect(word.hasAttribute('tabindex')).toBe(false)
        act(() => word.focus())
        expect(screen.queryByRole('tooltip')).toBeNull()
    })

    it("leaves the fact on hover inside a link, which is the keyboard's stop already", () => {
        render(
            <a href="#run">
                run:41{' '}
                <Tip fact="Oct 8, 10:30">
                    <time>3m</time>
                </Tip>
            </a>,
        )
        const age = screen.getByText('3m')
        expect(age.hasAttribute('tabindex')).toBe(false)
        expect(age.title).toBe('Oct 8, 10:30')
    })
})

describe('Clipped', () => {
    it('offers its text whole while it is cut, and only then', () => {
        const cut = vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(200)
        vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(80)
        render(<Clipped text="Debounce the search box" />)
        const title = screen.getByText('Debounce the search box')
        expect(tipOf(title)).toBe('Debounce the search box')

        cleanup()
        cut.mockReturnValue(80)
        render(<Clipped text="Short" />)
        const whole = screen.getByText('Short')
        expect(whole.hasAttribute('tabindex')).toBe(false)
        act(() => whole.focus())
        expect(screen.queryByRole('tooltip')).toBeNull()
    })
})

describe('Hinted', () => {
    it('makes a name with a hint a stop for the keyboard, with the hint its tip', () => {
        render(<Hinted hint="Its red runs' share of its red and green ones">failure rate</Hinted>)
        const name = screen.getByText('failure rate')
        expect(name.tabIndex).toBe(0)
        expect(tipOf(name)).toBe("Its red runs' share of its red and green ones")
        expect(name.title).toBe('')
    })

    it('is the name alone without one', () => {
        render(<Hinted hint={undefined}>runs</Hinted>)
        expect(screen.getByText('runs').tabIndex).toBe(-1)
    })
})
