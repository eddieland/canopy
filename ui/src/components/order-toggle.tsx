import { ArrowDownUp } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { orderWords, setListOrder, useListOrder } from '@/lib/list-order'
import type { ListName } from '@/lib/list-order'

/**
 * A list's order in its panel's header: which end comes first, in words (`orderWords`), flipping to the other on a
 * click. Each list keeps its own, across reloads (src/lib/list-order.ts).
 */
export function OrderToggle({ list }: { list: ListName }) {
    const order = useListOrder(list)
    const other = order === 'oldest' ? 'newest' : 'oldest'
    const words = orderWords(list, order)
    return (
        <Button
            variant="ghost"
            size="xs"
            // The visible words lead the name, so a voice command that reads them finds the button.
            aria-label={`${words}: show ${orderWords(list, other)}`}
            title={`Show ${orderWords(list, other)}`}
            data-testid={`order-${list}`}
            data-order={order}
            onClick={() => setListOrder(list, other)}
        >
            <ArrowDownUp />
            {words}
        </Button>
    )
}
