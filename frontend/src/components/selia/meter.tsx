'use client';

import * as React from 'react';
import { Meter as MeterPrimitive } from '@base-ui/react/meter';
import { cn } from 'lib/utils';

export function Meter({
  className,
  children,
  ...props
}: React.ComponentProps<typeof MeterPrimitive.Root>) {
  return (
    <MeterPrimitive.Root
      data-slot="meter"
      className={cn('flex flex-col gap-1.5', className)}
      {...props}
    >
      {children}
    </MeterPrimitive.Root>
  );
}

export function MeterLabel({
  className,
  ...props
}: React.ComponentProps<'span'>) {
  return (
    <span
      data-slot="meter-label"
      className={cn('text-sm font-medium text-foreground', className)}
      {...props}
    />
  );
}

export function MeterValue({
  className,
  ...props
}: React.ComponentProps<'span'>) {
  return (
    <span
      data-slot="meter-value"
      className={cn('text-sm text-muted-foreground', className)}
      {...props}
    />
  );
}

export function MeterTrack({
  className,
  ...props
}: React.ComponentProps<typeof MeterPrimitive.Track>) {
  return (
    <MeterPrimitive.Track
      data-slot="meter-track"
      className={cn(
        'h-2 w-full rounded-full bg-secondary overflow-hidden',
        className,
      )}
      {...props}
    />
  );
}

export function MeterIndicator({
  className,
  ...props
}: React.ComponentProps<typeof MeterPrimitive.Indicator>) {
  return (
    <MeterPrimitive.Indicator
      data-slot="meter-indicator"
      className={cn(
        'h-full rounded-full bg-primary transition-all duration-300',
        className,
      )}
      {...props}
    />
  );
}
