import { useCallback, useRef, useState, type ReactNode } from 'react'
import {
  Dialog,
  DialogPopup,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogBody,
  DialogFooter,
} from 'components/selia/dialog'
import { Button } from 'components/selia/button'

export interface ConfirmOptions {
  title: string
  /** One line under the title explaining the consequence. */
  description?: string
  /** Optional extra detail in the body — e.g. a deletion preview. */
  body?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** Red confirm button. Defaults to true; pass false for merely-disruptive actions. */
  destructive?: boolean
}

/**
 * Promise-based confirmation for destructive actions.
 *
 *   const { confirm, confirmDialog } = useConfirm()
 *   ...
 *   if (!(await confirm({ title: 'Delete 3 recordings?' }))) return
 *   ...
 *   return <div>{content}{confirmDialog}</div>
 *
 * A hook rather than a component because the alternative — open-state plus a
 * pending-action ref at every call site — is what led to most destructive
 * actions here shipping with no confirmation at all.
 */
export function useConfirm() {
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<ConfirmOptions | null>(null)
  // Held across the await so the buttons can settle the caller's promise.
  const resolverRef = useRef<((ok: boolean) => void) | null>(null)

  const settle = useCallback((ok: boolean) => {
    setOpen(false)
    resolverRef.current?.(ok)
    resolverRef.current = null
  }, [])

  const confirm = useCallback((opts: ConfirmOptions) => {
    setOptions(opts)
    setOpen(true)
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve
    })
  }, [])

  const destructive = options?.destructive !== false

  const confirmDialog = (
    <Dialog
      open={open}
      onOpenChange={(next: boolean) => {
        // Escape / overlay click must resolve too, or the caller awaits forever.
        if (!next) settle(false)
      }}
    >
      <DialogPopup>
        <DialogHeader>
          <DialogTitle>{options?.title}</DialogTitle>
          <DialogDescription>
            {options?.description ??
              (destructive ? 'This action cannot be undone.' : 'Please confirm you want to continue.')}
          </DialogDescription>
        </DialogHeader>
        {options?.body && <DialogBody>{options.body}</DialogBody>}
        <DialogFooter>
          <Button variant="outline" onClick={() => settle(false)}>
            {options?.cancelLabel ?? 'Cancel'}
          </Button>
          <Button variant={destructive ? 'danger' : 'primary'} onClick={() => settle(true)}>
            {options?.confirmLabel ?? (destructive ? 'Delete' : 'Continue')}
          </Button>
        </DialogFooter>
      </DialogPopup>
    </Dialog>
  )

  return { confirm, confirmDialog }
}
