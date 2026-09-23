import { useState, useEffect, type ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, AlertCircle, CheckCircle2, Trash2, Archive, Globe, Activity, Video, Clock, Palette, ShieldAlert } from 'lucide-react'
import { Card, CardBody, CardDescription, CardHeader, CardTitle } from '@/components/selia/card'
import { Button } from '@/components/selia/button'
import { IconBox } from '@/components/selia/icon-box'
import { Input } from '@/components/selia/input'
import { Label } from '@/components/selia/label'
import { Switch } from '@/components/selia/switch'
import { Progress, ProgressLabel, ProgressValue } from '@/components/selia/progress'
import { cn } from '@/lib/utils'
import {
  Select,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SelectPopup,
  SelectList,
} from '@/components/selia/select'
import {
  Tabs,
  TabsPanel,
  TabsList,
  TabsItem,
} from '@/components/selia/tabs'
import { api, type AutoCleanupConfig, type PreferredQuality, type Settings } from '@/lib/api'
import toast from 'react-hot-toast'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import AccentPicker from '@/components/AccentPicker'
import ThemeOptions from '@/components/ThemeOptions'

const QUALITY_OPTIONS: { value: PreferredQuality; label: string }[] = [
  { value: 'best', label: 'Best available' },
  { value: '1080', label: 'Up to 1080p' },
  { value: '720', label: 'Up to 720p' },
  { value: '540', label: 'Up to 540p' },
  { value: '360', label: 'Up to 360p' },
]

const TIMEZONES: { group: string; zones: [string, string][] }[] = [
  { group: 'UTC', zones: [['UTC', 'UTC']] },
  {
    group: 'Americas',
    zones: [
      ['America/New_York', 'Eastern Time — New York (ET)'],
      ['America/Chicago', 'Central Time — Chicago (CT)'],
      ['America/Denver', 'Mountain Time — Denver (MT)'],
      ['America/Phoenix', 'Mountain Time — Phoenix (no DST)'],
      ['America/Los_Angeles', 'Pacific Time — Los Angeles (PT)'],
      ['America/Anchorage', 'Alaska Time — Anchorage'],
      ['Pacific/Honolulu', 'Hawaii Time — Honolulu'],
      ['America/Toronto', 'Eastern Time — Toronto'],
      ['America/Vancouver', 'Pacific Time — Vancouver'],
      ['America/Sao_Paulo', 'Brasília Time — São Paulo'],
      ['America/Argentina/Buenos_Aires', 'Argentina — Buenos Aires'],
      ['America/Mexico_City', 'Central Time — Mexico City'],
      ['America/Bogota', 'Colombia Time — Bogotá'],
    ],
  },
  {
    group: 'Europe',
    zones: [
      ['Europe/London', 'GMT/BST — London'],
      ['Europe/Paris', 'CET/CEST — Paris'],
      ['Europe/Berlin', 'CET/CEST — Berlin'],
      ['Europe/Madrid', 'CET/CEST — Madrid'],
      ['Europe/Rome', 'CET/CEST — Rome'],
      ['Europe/Amsterdam', 'CET/CEST — Amsterdam'],
      ['Europe/Warsaw', 'CET/CEST — Warsaw'],
      ['Europe/Stockholm', 'CET/CEST — Stockholm'],
      ['Europe/Athens', 'EET/EEST — Athens'],
      ['Europe/Bucharest', 'EET/EEST — Bucharest'],
      ['Europe/Kiev', 'EET/EEST — Kyiv'],
      ['Europe/Moscow', 'MSK — Moscow'],
      ['Europe/Istanbul', 'TRT — Istanbul'],
    ],
  },
  {
    group: 'Asia & Pacific',
    zones: [
      ['Asia/Dubai', 'GST — Dubai'],
      ['Asia/Kolkata', 'IST — India'],
      ['Asia/Bangkok', 'ICT — Bangkok'],
      ['Asia/Singapore', 'SGT — Singapore'],
      ['Asia/Manila', 'PHT — Manila'],
      ['Asia/Shanghai', 'CST — China'],
      ['Asia/Tokyo', 'JST — Japan'],
      ['Asia/Seoul', 'KST — Seoul'],
      ['Australia/Sydney', 'AEDT/AEST — Sydney'],
      ['Australia/Perth', 'AWST — Perth'],
      ['Pacific/Auckland', 'NZDT/NZST — Auckland'],
    ],
  },
  {
    group: 'Africa',
    zones: [
      ['Africa/Cairo', 'EET — Cairo'],
      ['Africa/Johannesburg', 'SAST — Johannesburg'],
      ['Africa/Lagos', 'WAT — Lagos'],
      ['Africa/Nairobi', 'EAT — Nairobi'],
    ],
  },
]

function StatusRow({ label, ok, okText, badText, neutral }: {
  label: string
  ok: boolean
  okText: string
  badText: string
  neutral?: boolean
}) {
  return (
    <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex items-center gap-2">
        <IconBox variant={ok ? 'success-subtle' : neutral ? 'secondary-subtle' : 'warning-subtle'} size="sm">
          {ok ? <CheckCircle2 className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
        </IconBox>
        <span className={cn('text-sm', ok ? 'text-success' : neutral ? 'text-muted-foreground' : 'text-warning')}>
          {ok ? okText : badText}
        </span>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const isDesktop = useMediaQuery('(min-width: 768px)')
  const [mobileTab, setMobileTab] = useState('status')

  const { data: settings, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.settings.get(),
  })

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => api.settings.health(),
    refetchInterval: 60000,
  })

  const [formData, setFormData] = useState<Partial<Settings>>({})

  useEffect(() => {
    if (settings) {
      setFormData(settings)
    }
  }, [settings])

  const updateSettingsMutation = useMutation({
    mutationFn: (data: Partial<Settings>) => api.settings.update(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      queryClient.invalidateQueries({ queryKey: ['health'] })
      toast.success('Settings saved')
    },
    onError: (error: Error) => {
      toast.error(error.message)
    },
  })

  const handleSave = () => {
    updateSettingsMutation.mutate(formData)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12" role="status" aria-label="Loading settings">
        <svg className="h-6 w-6 animate-spin motion-reduce:animate-none text-primary-ink" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 12a9 9 0 1 1-6.219-8.56" />
        </svg>
        <span className="sr-only">Loading settings…</span>
      </div>
    )
  }

  const cleanup: AutoCleanupConfig = {
    enabled: formData.auto_cleanup?.enabled ?? false,
    days: formData.auto_cleanup?.days ?? 7,
    action: formData.auto_cleanup?.action ?? 'delete',
  }
  const setCleanup = (patch: Partial<AutoCleanupConfig>) =>
    setFormData({ ...formData, auto_cleanup: { ...cleanup, ...patch } })

  // Host CPU and RAM, shown under the status rows.
  const resourceMeters =
    health?.cpu_percent != null && health?.ram_percent != null ? (
      <div className="grid gap-4 p-3 rounded-lg bg-secondary">
        {[
          { label: 'CPU', value: health.cpu_percent },
          { label: 'RAM', value: health.ram_percent },
        ].map(({ label, value }) => (
          <Progress
            key={label}
            value={value}
            className={cn(
              value >= 60 && value < 80 && '**:data-[slot=progress-indicator]:bg-warning',
              value >= 80 && '**:data-[slot=progress-indicator]:bg-danger',
            )}
          >
            <ProgressLabel className="text-sm">{label}</ProgressLabel>
            <ProgressValue>{() => `${value.toFixed(1)}%`}</ProgressValue>
          </Progress>
        ))}
      </div>
    ) : null

  // Each card is rendered once in the desktop grid, or one per tab on mobile.
  // `p` prefixes form ids so the two layouts never share an id.
  const cards: { id: string; label: string; icon: typeof Activity; render: (p: string) => ReactNode }[] = [
    {
      id: 'status',
      label: 'Status',
      icon: Activity,
      render: () => (
        <Card id="settings-status">
          <CardHeader>
            <CardTitle>System Status</CardTitle>
            <CardDescription>Backend health and cam site reachability</CardDescription>
          </CardHeader>
          <CardBody className="space-y-4">
            <StatusRow label="API Status" ok={health?.status === 'healthy'} okText="Healthy" badText="Unknown" />
            {(health?.sites ?? []).map((site) => (
              <StatusRow
                key={site.name}
                label={site.label}
                ok={site.reachable && !site.blocked}
                okText="Reachable"
                badText={site.blocked ? 'Blocked' : 'Unreachable'}
              />
            ))}
            {health?.monitor_error && (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-warning/10 text-sm text-warning">
                <ShieldAlert className="h-4 w-4 mt-0.5 shrink-0" />
                <span>Last watchlist check failed: {health.monitor_error}</span>
              </div>
            )}
            <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
              <span className="text-sm font-medium">Output Directory</span>
              <span className="text-sm text-muted-foreground truncate max-w-[200px]">
                {health?.recordings_dir || settings?.output_dir}
              </span>
            </div>
            {resourceMeters}
          </CardBody>
        </Card>
      ),
    },
    {
      id: 'recording',
      label: 'Recording',
      icon: Video,
      render: (p) => (
        <Card id="settings-recording">
          <CardHeader>
            <CardTitle>Recording Settings</CardTitle>
            <CardDescription>How often models are checked and how shows are captured</CardDescription>
          </CardHeader>
          <CardBody className="space-y-4">
            <div className="grid gap-2">
              <Label htmlFor={`${p}interval`}>Check interval (minutes)</Label>
              <Input
                id={`${p}interval`}
                type="number"
                min="1"
                placeholder="2"
                value={formData.automatic_interval || 2}
                onChange={(e) => setFormData({ ...formData, automatic_interval: parseInt(e.target.value) || 2 })}
              />
              <p className="text-xs text-muted-foreground">
                One request covers every online model, so short intervals are cheap and catch shows sooner.
              </p>
            </div>
            <div className="grid gap-2">
              <Label>Preferred quality</Label>
              <Select
                value={formData.preferred_quality || 'best'}
                onValueChange={(v) => setFormData({ ...formData, preferred_quality: v as PreferredQuality })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectPopup>
                  <SelectList>
                    {QUALITY_OPTIONS.map((q) => (
                      <SelectItem key={q.value} value={q.value}>{q.label}</SelectItem>
                    ))}
                  </SelectList>
                </SelectPopup>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor={`${p}max-hours`}>Maximum recording length (hours)</Label>
              <Input
                id={`${p}max-hours`}
                type="number"
                min="1"
                placeholder="8"
                value={formData.max_recording_hours || 8}
                onChange={(e) => setFormData({ ...formData, max_recording_hours: parseInt(e.target.value) || 8 })}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor={`${p}proxy`}>HTTP Proxy</Label>
              <Input
                id={`${p}proxy`}
                placeholder="http://127.0.0.1:8080"
                value={formData.proxy || ''}
                onChange={(e) => setFormData({ ...formData, proxy: e.target.value || null })}
              />
              <p className="text-xs text-muted-foreground">
                Optional. Used for status checks and stream capture.
              </p>
            </div>
            <p className="text-xs text-muted-foreground border-t border-border pt-3">
              Only public (free chat) shows are recorded. When a model goes private the
              recording pauses and resumes if the show returns to public.
            </p>
          </CardBody>
        </Card>
      ),
    },
    {
      id: 'cleanup',
      label: 'Cleanup',
      icon: Trash2,
      render: (p) => (
        <Card id="settings-cleanup">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Trash2 className="h-5 w-5" />
              Auto-Cleanup
            </CardTitle>
            <CardDescription>Automatically clean up old recordings to save disk space</CardDescription>
          </CardHeader>
          <CardBody className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <Label>Enable Auto-Cleanup</Label>
                <p className="text-xs text-muted-foreground">Automatically process old recordings</p>
              </div>
              <Switch checked={cleanup.enabled} onCheckedChange={() => setCleanup({ enabled: !cleanup.enabled })} />
            </div>

            {cleanup.enabled && (
              <>
                <div className="grid gap-2">
                  <Label>Retention Period</Label>
                  <Select value={String(cleanup.days)} onValueChange={(v) => setCleanup({ days: parseInt(String(v)) })}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectPopup>
                      <SelectList>
                        <SelectItem value="1">1 day</SelectItem>
                        <SelectItem value="3">3 days</SelectItem>
                        <SelectItem value="7">7 days</SelectItem>
                        <SelectItem value="14">14 days</SelectItem>
                        <SelectItem value="30">30 days</SelectItem>
                      </SelectList>
                    </SelectPopup>
                  </Select>
                  <p className="text-xs text-muted-foreground">Recordings older than this will be processed</p>
                </div>

                <div className="grid gap-2">
                  <Label>Cleanup Action</Label>
                  <div className="flex gap-4">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name={`${p}cleanup_action`}
                        value="delete"
                        checked={cleanup.action === 'delete'}
                        onChange={() => setCleanup({ action: 'delete' })}
                        className="h-4 w-4"
                      />
                      <Trash2 className="h-4 w-4" />
                      <span className="text-sm">Delete permanently</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name={`${p}cleanup_action`}
                        value="compress"
                        checked={cleanup.action === 'compress'}
                        onChange={() => setCleanup({ action: 'compress' })}
                        className="h-4 w-4"
                      />
                      <Archive className="h-4 w-4" />
                      <span className="text-sm">Compress to backup</span>
                    </label>
                  </div>
                </div>
              </>
            )}
          </CardBody>
        </Card>
      ),
    },
    {
      id: 'timezone',
      label: 'Timezone',
      icon: Clock,
      render: (p) => (
        <Card id="settings-timezone">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Globe className="h-5 w-5" />
              Display Timezone
            </CardTitle>
            <CardDescription>All timestamps shown in the app will use this timezone</CardDescription>
          </CardHeader>
          <CardBody className="space-y-4">
            <div className="grid gap-2">
              <Label htmlFor={`${p}timezone`}>Timezone</Label>
              <select
                id={`${p}timezone`}
                className="flex h-10 w-full rounded-md border border-input-border bg-background px-3 py-2 text-sm"
                value={formData.timezone || 'UTC'}
                onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
              >
                {TIMEZONES.map(({ group, zones }) => (
                  <optgroup key={group} label={group}>
                    {zones.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <div className="p-3 rounded-lg bg-secondary text-sm">
              <span className="text-muted-foreground">Current time in selected zone: </span>
              <span className="font-medium tabular-nums">
                {new Date().toLocaleString('en-US', {
                  timeZone: formData.timezone || 'UTC',
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                  second: '2-digit',
                })}
              </span>
            </div>
          </CardBody>
        </Card>
      ),
    },
    {
      id: 'appearance',
      label: 'Appearance',
      icon: Palette,
      render: () => (
        <Card id="settings-appearance">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Palette className="h-5 w-5" />
              Appearance
            </CardTitle>
            <CardDescription>Choose your preferred theme and accent color</CardDescription>
          </CardHeader>
          <CardBody className="space-y-5">
            <ThemeOptions />
            <div className="border-t border-border pt-5">
              <AccentPicker />
            </div>
          </CardBody>
        </Card>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground tracking-tight">Settings</h1>
          <p className="text-muted-foreground mt-1">Configure how CamSuite watches and records</p>
        </div>
        <Button onClick={handleSave} disabled={updateSettingsMutation.isPending}>
          <Save className="h-4 w-4 mr-2" />
          {updateSettingsMutation.isPending ? 'Saving...' : 'Save Changes'}
        </Button>
      </div>

      {isDesktop ? (
        <div className="grid gap-6 md:grid-cols-2">
          {cards.map((card) => (
            <div key={card.id} className="contents">{card.render('')}</div>
          ))}
        </div>
      ) : (
        <Tabs value={mobileTab} onValueChange={setMobileTab}>
          <TabsList className="w-full flex-wrap h-auto">
            {cards.map((tab) => {
              const Icon = tab.icon
              return (
                <TabsItem key={tab.id} value={tab.id} className="gap-1.5">
                  <Icon className="h-3.5 w-3.5" />
                  {tab.label}
                </TabsItem>
              )
            })}
          </TabsList>
          {cards.map((tab) => (
            <TabsPanel key={tab.id} value={tab.id}>
              {tab.render('m-')}
            </TabsPanel>
          ))}
        </Tabs>
      )}
    </div>
  )
}
