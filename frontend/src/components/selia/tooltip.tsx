'use client';

import * as React from 'react';
import { Tooltip as BaseTooltip } from '@base-ui/react/tooltip';
import { cn } from 'lib/utils';

export function Tooltip({
  children,
  ...props
}: React.ComponentProps<typeof BaseTooltip.Root>) {
  return (
    <BaseTooltip.Root data-slot="tooltip" {...props}>
      {children}
    </BaseTooltip.Root>
  );
}

export function TooltipTrigger({
  children,
  ...props
}: React.ComponentProps<typeof BaseTooltip.Trigger>) {
  return (
    <BaseTooltip.Trigger data-slot="tooltip-trigger" {...props}>
      {children}
    </BaseTooltip.Trigger>
  );
}

export function TooltipContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof BaseTooltip.Popup>) {
  return (
    <BaseTooltip.Portal>
      <BaseTooltip.Positioner sideOffset={6}>
        <BaseTooltip.Popup
          data-slot="tooltip-popup"
          {...props}
          className={cn(
            'z-50 max-w-xs rounded-lg px-3 py-1.5 text-sm',
            'bg-popover text-popover-foreground shadow-md',
            'border border-border',
            'data-[starting-style]:opacity-0 data-[ending-style]:opacity-0',
            'transition-opacity duration-100',
            className,
          )}
        >
          {children}
          <BaseTooltip.Arrow className="fill-popover stroke-border" />
        </BaseTooltip.Popup>
      </BaseTooltip.Positioner>
    </BaseTooltip.Portal>
  );
}
