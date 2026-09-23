import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Circle, Ellipsis, Play, RefreshCw, Trash2, Tv } from 'lucide-react'
import { Card, CardBody } from '@/components/selia/card'
import { Badge } from '@/components/selia/badge'
import { Button } from '@/components/selia/button'
import { Checkbox } from '@/components/selia/checkbox'
import { Switch } from '@/components/selia/switch'
import { Heading } from '@/components/selia/heading'
import { Text } from '@/components/selia/text'
import { Menu, MenuItem, MenuPopup, MenuSeparator, MenuTrigger } from '@/components/selia/menu'
import { api, type ActiveRecording, type User } from '@/lib/api'
import { timeAgo } from '@/lib/notifications'
import { cn } from '@/lib/utils'

function compactNumber(n: number): string {
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}

/**
 * A watchlist creator as a photo card: a quieter take on the dashboard's
 * live card, with the watchlist controls (select, monitoring, menu).
 */
export default function WatchlistProfileCard({
  user,
  recording,
  selected,
  onSelectedChange,
  onOpen,
  onToggleMonitoring,
  onRefresh,
  onRecord,
  onRemove,
  onAvatarError,
}: {
  user: User
  recording?: ActiveRecording
  selected: boolean
  onSelectedChange: (selected: boolean) => void
  onOpen: () => void
  onToggleMonitoring: (monitoring: boolean) => void
  onRefresh: () => void
  onRecord: () => void
  onRemove: () => void
  onAvatarError: () => void
}) {
  const [imageFailed, setImageFailed] = useState(false)
  const name = user.display_name && user.display_name !== user.username ? user.display_name : user.username
  const live = user.is_live || !!recording

  return (
    <Card
      className={cn(
        'relative h-80 p-1 overflow-hidden group isolate transition-shadow hover:shadow-md',
        selected && 'ring-2 ring-primary',
      )}
    >
      {/* Whole-card click target for the detail drawer. Controls sit above it. */}
      <button
        type="button"
        onClick={onOpen}
        className="absolute inset-0 z-[1] rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        aria-label={`View details for @${user.username}`}
      />

      {imageFailed ? (
        <div className="absolute inset-0 rounded-xl bg-linear-to-br from-primary/30 via-avatar to-card flex items-start justify-center pt-12" aria-hidden="true">
          <span className="text-6xl font-semibold text-foreground/60 select-none">{user.username[0]?.toUpperCase()}</span>
        </div>
      ) : (
        <img
          src={api.users.getAvatarUrl(user.id)}
          alt=""
          className={cn(
            'absolute inset-0 size-full object-cover rounded-xl transition-[transform,filter] duration-700 group-hover:scale-[1.03] motion-reduce:transition-none',
            !live && 'saturate-[.85]',
          )}
          loading="lazy"
          decoding="async"
          onError={() => {
            setImageFailed(true)
            onAvatarError()
          }}
        />
      )}
      <div className="bg-linear-to-b from-card/0 via-card/70 to-card absolute inset-x-0 bottom-0 h-4/5 rounded-[calc(var(--radius-xl)-3px)] pointer-events-none" />

      {/* Top row: live state + selection */}
      <div className="absolute top-3.5 inset-x-3.5 z-10 flex items-center justify-between pointer-events-none">
        {live ? (
          // On the photo: fixed scrim, legible over any image in every theme.
          <Badge pill size="sm" className="font-semibold tracking-wide bg-black/60 text-white backdrop-blur-sm">
            <Circle className="fill-red-500 text-red-500" aria-hidden="true" />
            {recording ? 'REC' : 'LIVE'}
          </Badge>
        ) : (
          <span />
        )}
        <Checkbox
          checked={selected}
          onCheckedChange={(checked) => onSelectedChange(checked)}
          aria-label={`Select @${user.username}`}
          className={cn(
            'pointer-events-auto bg-card/80 backdrop-blur transition-opacity',
            !selected && 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100',
          )}
        />
      </div>

      <CardBody className="absolute bottom-0 inset-x-0 p-5 z-10 pointer-events-none">
        <Heading size="sm" className="truncate">{name}</Heading>
        <Text className="text-sm text-muted truncate">@{user.username}</Text>
        {user.bio && <Text className="text-sm text-dimmed line-clamp-2 mt-1.5">{user.bio}</Text>}
        <p className="text-xs text-dimmed mt-2 flex flex-wrap gap-x-2">
          {user.follower_count != null && <span>{compactNumber(user.follower_count)} followers</span>}
          {user.last_checked && <span>· checked {timeAgo(user.last_checked)}</span>}
        </p>

        <div className="flex items-center gap-2 mt-3 pointer-events-auto">
          <label className="flex items-center gap-2 text-sm text-foreground cursor-pointer">
            <Switch
              checked={user.is_monitoring}
              onCheckedChange={(checked) => onToggleMonitoring(checked)}
              aria-label={`Monitor @${user.username}`}
            />
            {user.is_monitoring ? 'Monitoring' : 'Not monitored'}
          </label>

          <div className="ml-auto flex items-center gap-1">
            {recording && (
              <Button
                variant="tertiary"
                size="sm"
                pill
                nativeButton={false}
                render={<Link to={`/live/${recording.id}`} />}
              >
                <Tv />
                Watch
              </Button>
            )}
            <Menu>
              <MenuTrigger
                render={<Button variant="plain" size="sm-icon" pill aria-label={`More actions for @${user.username}`} />}
              >
                <Ellipsis />
              </MenuTrigger>
              <MenuPopup align="end" size="compact">
                {live && !recording && (
                  <MenuItem onClick={onRecord}>
                    <Play />
                    Record now
                  </MenuItem>
                )}
                <MenuItem onClick={onRefresh}>
                  <RefreshCw />
                  Refresh profile
                </MenuItem>
                <MenuSeparator />
                <MenuItem onClick={onRemove} className="text-danger [&_svg]:text-danger">
                  <Trash2 />
                  Remove from watchlist
                </MenuItem>
              </MenuPopup>
            </Menu>
          </div>
        </div>
      </CardBody>
    </Card>
  )
}
