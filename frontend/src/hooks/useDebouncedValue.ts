import { useEffect, useState } from 'react'

/** Returns a debounced copy of `value` that only updates after `delayMs`
 * has elapsed without `value` changing. Used to avoid firing a network
 * request on every keystroke in search inputs. */
export function useDebouncedValue<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
