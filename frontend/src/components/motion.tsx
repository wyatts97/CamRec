import { motion, useReducedMotion, type Variants } from 'framer-motion'
import { cn } from '@/lib/utils'

/**
 * Motion primitives shared across pages. All animations automatically collapse
 * to instant transitions when the user has `prefers-reduced-motion` enabled.
 */

const EASE = [0.22, 1, 0.36, 1] as const

/** Fade + slide-up wrapper for page-level content. Keyed by route in Layout. */
export function PageTransition({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduce ? undefined : { opacity: 0, y: -8 }}
      transition={{ duration: 0.25, ease: EASE }}
    >
      {children}
    </motion.div>
  )
}

/**
 * Container that staggers the entrance of its {@link StaggerItem} children.
 * Renders a plain div (no animation) when reduced-motion is requested.
 */
export function StaggerContainer({
  children,
  className,
  ...props
}: React.ComponentProps<typeof motion.div>) {
  const reduce = useReducedMotion()

  const variants: Variants = {
    hidden: {},
    show: {
      transition: {
        staggerChildren: reduce ? 0 : 0.05,
        delayChildren: reduce ? 0 : 0.04,
      },
    },
  }

  return (
    <motion.div
      className={className}
      variants={variants}
      initial="hidden"
      animate="show"
      {...props}
    >
      {children}
    </motion.div>
  )
}

/** Item used inside a {@link StaggerContainer}. */
export function StaggerItem({
  children,
  className,
  ...props
}: React.ComponentProps<typeof motion.div>) {
  const reduce = useReducedMotion()

  const variants: Variants = {
    hidden: reduce ? { opacity: 1 } : { opacity: 0, y: 10 },
    show: {
      opacity: 1,
      y: 0,
      transition: { duration: 0.3, ease: EASE },
    },
  }

  return (
    <motion.div className={cn(className)} variants={variants} {...props}>
      {children}
    </motion.div>
  )
}
