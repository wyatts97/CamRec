'use client';

import { Checkbox as BaseCheckbox } from '@base-ui/react/checkbox';
import { cn } from 'lib/utils';
import { Check } from 'lucide-react';

export function Checkbox({
  className,
  ...props
}: React.ComponentProps<typeof BaseCheckbox.Root>) {
  return (
    <BaseCheckbox.Root
      data-slot="checkbox"
      className={cn(
        'flex size-4 shrink-0 items-center justify-center rounded-sm border border-input-border bg-background cursor-pointer',
        'data-checked:bg-primary data-checked:border-primary data-checked:text-primary-foreground',
        'data-indeterminate:bg-primary data-indeterminate:border-primary data-indeterminate:text-primary-foreground',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
        'data-disabled:cursor-not-allowed data-disabled:opacity-70',
        className,
      )}
      {...props}
    >
      <BaseCheckbox.Indicator className="flex items-center justify-center">
        <Check className="size-3" />
      </BaseCheckbox.Indicator>
    </BaseCheckbox.Root>
  );
}
