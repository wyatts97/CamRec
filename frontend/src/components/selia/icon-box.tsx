'use client';

import * as React from 'react';
import { cn } from 'lib/utils';
import { cva, type VariantProps } from 'class-variance-authority';

const iconBoxVariants = cva(
  'relative inline-flex items-center justify-center rounded-lg overflow-hidden',
  {
    variants: {
      variant: {
        primary:
          'bg-primary text-primary-foreground before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/[0.12] before:to-transparent',
        secondary:
          'bg-secondary text-secondary-foreground before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/[0.12] before:to-transparent',
        tertiary:
          'bg-tertiary text-tertiary-foreground before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/[0.12] before:to-transparent',
        success:
          'bg-success text-success-foreground before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/[0.12] before:to-transparent',
        info: 'bg-info text-info-foreground before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/[0.12] before:to-transparent',
        warning:
          'bg-warning text-warning-foreground before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/[0.12] before:to-transparent',
        danger:
          'bg-danger text-danger-foreground before:absolute before:inset-0 before:bg-gradient-to-b before:from-white/[0.12] before:to-transparent',
        'primary-subtle':
          'bg-primary/10 text-primary-ink before:hidden',
        'secondary-subtle':
          'bg-secondary/10 text-secondary-foreground before:hidden',
        'tertiary-subtle':
          'bg-tertiary/10 text-tertiary-foreground before:hidden',
        'success-subtle':
          'bg-success/10 text-success before:hidden',
        'info-subtle': 'bg-info/10 text-info before:hidden',
        'warning-subtle':
          'bg-warning/10 text-warning before:hidden',
        'danger-subtle':
          'bg-danger/10 text-danger before:hidden',
      },
      size: {
        sm: 'size-7 [&>svg]:size-3.5',
        md: 'size-8 [&>svg]:size-4',
        lg: 'size-10 [&>svg]:size-5',
      },
      circle: {
        true: 'rounded-full',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
      circle: false,
    },
  },
);

export { iconBoxVariants };

export function IconBox({
  variant,
  size,
  circle,
  className,
  children,
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof iconBoxVariants>) {
  return (
    <span
      data-slot="icon-box"
      className={cn(iconBoxVariants({ variant, size, circle, className }))}
      {...props}
    >
      {children}
    </span>
  );
}
