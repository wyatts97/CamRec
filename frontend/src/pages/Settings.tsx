import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, AlertCircle, CheckCircle2, ExternalLink, Trash2, Archive, Globe, Activity, Cookie, Send, Video, Clock, Palette } from 'lucide-react'
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
import { api, type Settings } from '@/lib/api'
import toast from 'react-hot-toast'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import AccentPicker from '@/components/AccentPicker'
import ThemeOptions from '@/components/ThemeOptions'

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

  // Host CPU and RAM (moved here from the dashboard). Shared by the desktop
  // and mobile status cards.
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

  // Rendered in both the desktop card list and the mobile cookies tab.
  const chatAuthToggle = (id: string) => (
    <div className="flex items-start justify-between gap-4 pt-2 border-t border-border">
      <div>
        <Label htmlFor={id}>Use session for live chat capture</Label>
        <p className="text-xs text-muted-foreground mt-1">
          Chat connects anonymously by default. Turning this on sends your session ID to the
          Euler Stream sign server, which TikTok refuses less often from a VPS. A session ID
          grants full access to your TikTok account, so only enable it if you accept that risk.
        </p>
      </div>
      <Switch
        id={id}
        checked={formData.chat_authenticated || false}
        onCheckedChange={() =>
          setFormData({ ...formData, chat_authenticated: !formData.chat_authenticated })
        }
      />
    </div>
  )

  const tabs = [
    { id: 'status', label: 'Status', icon: Activity },
    { id: 'cookies', label: 'Cookies', icon: Cookie },
    { id: 'telegram', label: 'Telegram', icon: Send },
    { id: 'recording', label: 'Recording', icon: Video },
    { id: 'cleanup', label: 'Cleanup', icon: Trash2 },
    { id: 'timezone', label: 'Timezone', icon: Clock },
    { id: 'appearance', label: 'Appearance', icon: Palette },
  ]

  const sectionContent = (
    <>
      <Card id="settings-status">
        <CardHeader>
          <CardTitle>System Status</CardTitle>
          <CardDescription>Current system health and configuration status</CardDescription>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
            <span className="text-sm font-medium">API Status</span>
            <div className="flex items-center gap-2">
              {health?.status === 'healthy' ? (
                <>
                  <IconBox variant="success-subtle" size="sm">
                    <CheckCircle2 className="h-4 w-4" />
                  </IconBox>
                  <span className="text-sm text-success">Healthy</span>
                </>
              ) : (
                <>
                  <IconBox variant="warning-subtle" size="sm">
                    <AlertCircle className="h-4 w-4" />
                  </IconBox>
                  <span className="text-sm text-warning">Unknown</span>
                </>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
            <span className="text-sm font-medium">Recorder</span>
            <div className="flex items-center gap-2">
              {health?.recorder_available ? (
                <>
                  <IconBox variant="success-subtle" size="sm">
                    <CheckCircle2 className="h-4 w-4" />
                  </IconBox>
                  <span className="text-sm text-success">Ready</span>
                </>
              ) : (
                <>
                  <IconBox variant="warning-subtle" size="sm">
                    <AlertCircle className="h-4 w-4" />
                  </IconBox>
                  <span className="text-sm text-warning">Unavailable</span>
                </>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
            <span className="text-sm font-medium">Region Status</span>
            <div className="flex items-center gap-2">
              {health?.country_blacklisted ? (
                <>
                  <IconBox variant="warning-subtle" size="sm">
                    <AlertCircle className="h-4 w-4" />
                  </IconBox>
                  <span className="text-sm text-warning">Restricted</span>
                </>
              ) : (
                <>
                  <IconBox variant="success-subtle" size="sm">
                    <CheckCircle2 className="h-4 w-4" />
                  </IconBox>
                  <span className="text-sm text-success">OK</span>
                </>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
            <span className="text-sm font-medium">Cookies</span>
            <div className="flex items-center gap-2">
              {health?.cookies_configured ? (
                <>
                  <IconBox variant="success-subtle" size="sm">
                    <CheckCircle2 className="h-4 w-4" />
                  </IconBox>
                  <span className="text-sm text-success">Configured</span>
                </>
              ) : (
                <>
                  <IconBox variant="secondary-subtle" size="sm">
                    <AlertCircle className="h-4 w-4" />
                  </IconBox>
                  <span className="text-sm text-muted-foreground">Not Set</span>
                </>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
            <span className="text-sm font-medium">Output Directory</span>
            <span className="text-sm text-muted-foreground truncate max-w-[200px]">
              {health?.recordings_dir || settings?.output_dir}
            </span>
          </div>
          {resourceMeters}
        </CardBody>
      </Card>

      <Card id="settings-cookies">
        <CardHeader>
          <CardTitle>TikTok Cookies</CardTitle>
          <CardDescription>
            Required for accessing restricted content.{' '}
            <a
              href="https://github.com/Michele0303/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-set-cookies"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-ink hover:underline inline-flex items-center gap-1"
            >
              Learn how <ExternalLink className="h-3 w-3" />
            </a>
          </CardDescription>
        </CardHeader>
        <CardBody className="space-y-4">
          <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
            <div className="grid gap-2">
              <Label htmlFor="sessionid_ss">Session ID (sessionid_ss)</Label>
              <Input
                id="sessionid_ss"
                name="sessionid_ss"
                type="password"
                autoComplete="off"
                placeholder="Enter your TikTok session ID"
                value={formData.cookies?.sessionid_ss || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    cookies: {
                      ...formData.cookies,
                      sessionid_ss: e.target.value,
                      tt_target_idc: formData.cookies?.tt_target_idc || 'useast2a',
                    },
                  })
                }
              />
            </div>
          </form>
          <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
            <div className="grid gap-2">
              <Label htmlFor="tt_target_idc">Target IDC (tt-target-idc)</Label>
              <Input
                id="tt_target_idc"
                name="tt_target_idc"
                placeholder="useast2a"
                autoComplete="off"
                value={formData.cookies?.tt_target_idc || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    cookies: {
                      ...formData.cookies,
                      sessionid_ss: formData.cookies?.sessionid_ss || '',
                      tt_target_idc: e.target.value,
                    },
                  })
                }
              />
            </div>
          </form>
          {chatAuthToggle('chat_authenticated')}
        </CardBody>
      </Card>

      <Card id="settings-telegram">
        <CardHeader>
          <CardTitle>Telegram Integration</CardTitle>
          <CardDescription>
            Upload recordings to Telegram automatically.{' '}
            <a
              href="https://github.com/Michele0303/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-enable-upload-to-telegram"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary-ink hover:underline inline-flex items-center gap-1"
            >
              Learn how <ExternalLink className="h-3 w-3" />
            </a>
          </CardDescription>
        </CardHeader>
        <CardBody className="space-y-4">
          <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
            <div className="grid gap-2">
              <Label htmlFor="api_id">API ID</Label>
              <Input
                id="api_id"
                name="api_id"
                placeholder="Enter your Telegram API ID"
                autoComplete="off"
                value={formData.telegram?.api_id || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    telegram: {
                      ...formData.telegram,
                      api_id: e.target.value,
                      api_hash: formData.telegram?.api_hash || '',
                      chat_id: formData.telegram?.chat_id || 'me',
                    },
                  })
                }
              />
            </div>
          </form>
          <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
            <div className="grid gap-2">
              <Label htmlFor="api_hash">API Hash</Label>
              <Input
                id="api_hash"
                name="api_hash"
                type="password"
                autoComplete="off"
                placeholder="Enter your Telegram API Hash"
                value={formData.telegram?.api_hash || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    telegram: {
                      ...formData.telegram,
                      api_id: formData.telegram?.api_id || '',
                      api_hash: e.target.value,
                      chat_id: formData.telegram?.chat_id || 'me',
                    },
                  })
                }
              />
            </div>
          </form>
          <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
            <div className="grid gap-2">
              <Label htmlFor="chat_id">Chat ID</Label>
              <Input
                id="chat_id"
                name="chat_id"
                placeholder="me"
                autoComplete="off"
                value={formData.telegram?.chat_id || ''}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    telegram: {
                      ...formData.telegram,
                      api_id: formData.telegram?.api_id || '',
                      api_hash: formData.telegram?.api_hash || '',
                      chat_id: e.target.value,
                    },
                  })
                }
              />
            </div>
          </form>
        </CardBody>
      </Card>

      <Card id="settings-recording">
        <CardHeader>
          <CardTitle>Recording Settings</CardTitle>
          <CardDescription>Configure default recording behavior</CardDescription>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="grid gap-2">
            <Label htmlFor="proxy">HTTP Proxy</Label>
            <Input
              id="proxy"
              placeholder="http://127.0.0.1:8080"
              value={formData.proxy || ''}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  proxy: e.target.value || null,
                })
              }
            />
            <p className="text-xs text-muted-foreground">
              Use a proxy to bypass regional restrictions
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="bitrate">Default Bitrate</Label>
            <Input
              id="bitrate"
              placeholder="e.g., 1M, 1000k (leave empty for original)"
              value={formData.default_bitrate || ''}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  default_bitrate: e.target.value || null,
                })
              }
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="interval">Automatic Check Interval (minutes)</Label>
            <Input
              id="interval"
              type="number"
              min="1"
              placeholder="5"
              value={formData.automatic_interval || 5}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  automatic_interval: parseInt(e.target.value) || 5,
                })
              }
            />
          </div>
        </CardBody>
      </Card>

      <Card id="settings-cleanup">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Trash2 className="h-5 w-5" />
            Auto-Cleanup
          </CardTitle>
          <CardDescription>
            Automatically clean up old recordings to save disk space
          </CardDescription>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <Label>Enable Auto-Cleanup</Label>
              <p className="text-xs text-muted-foreground">
                Automatically process old recordings
              </p>
            </div>
            <Switch
              checked={formData.auto_cleanup?.enabled || false}
              onCheckedChange={() =>
                setFormData({
                  ...formData,
                  auto_cleanup: {
                    ...formData.auto_cleanup,
                    enabled: !formData.auto_cleanup?.enabled,
                    days: formData.auto_cleanup?.days || 7,
                    action: formData.auto_cleanup?.action || 'delete',
                  },
                })
              }
            />
          </div>

          {formData.auto_cleanup?.enabled && (
            <>
              <div className="grid gap-2">
                <Label>Retention Period</Label>
                <Select
                  value={String(formData.auto_cleanup?.days || 7)}
                  onValueChange={(v) =>
                    setFormData({
                      ...formData,
                      auto_cleanup: {
                        ...formData.auto_cleanup,
                        enabled: formData.auto_cleanup?.enabled || false,
                        days: parseInt(String(v)),
                        action: formData.auto_cleanup?.action || 'delete',
                      },
                    })
                  }
                >
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
                <p className="text-xs text-muted-foreground">
                  Recordings older than this will be processed
                </p>
              </div>

              <div className="grid gap-2">
                <Label>Cleanup Action</Label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="cleanup_action"
                      value="delete"
                      checked={formData.auto_cleanup?.action === 'delete'}
                      onChange={() =>
                        setFormData({
                          ...formData,
                          auto_cleanup: {
                            ...formData.auto_cleanup,
                            enabled: formData.auto_cleanup?.enabled || false,
                            days: formData.auto_cleanup?.days || 7,
                            action: 'delete',
                          },
                        })
                      }
                      className="h-4 w-4"
                    />
                    <Trash2 className="h-4 w-4" />
                    <span className="text-sm">Delete permanently</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="cleanup_action"
                      value="compress"
                      checked={formData.auto_cleanup?.action === 'compress'}
                      onChange={() =>
                        setFormData({
                          ...formData,
                          auto_cleanup: {
                            ...formData.auto_cleanup,
                            enabled: formData.auto_cleanup?.enabled || false,
                            days: formData.auto_cleanup?.days || 7,
                            action: 'compress',
                          },
                        })
                      }
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
      <Card id="settings-timezone">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Globe className="h-5 w-5" />
            Display Timezone
          </CardTitle>
          <CardDescription>
            All timestamps shown in the app will use this timezone
          </CardDescription>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="grid gap-2">
            <Label htmlFor="timezone">Timezone</Label>
            <select
              id="timezone"
              className="flex h-10 w-full rounded-md border border-input-border bg-background px-3 py-2 text-sm"
              value={formData.timezone || 'UTC'}
              onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
            >
              <optgroup label="UTC">
                <option value="UTC">UTC</option>
              </optgroup>
              <optgroup label="Americas">
                <option value="America/New_York">Eastern Time — New York (ET)</option>
                <option value="America/Chicago">Central Time — Chicago (CT)</option>
                <option value="America/Denver">Mountain Time — Denver (MT)</option>
                <option value="America/Phoenix">Mountain Time — Phoenix (no DST)</option>
                <option value="America/Los_Angeles">Pacific Time — Los Angeles (PT)</option>
                <option value="America/Anchorage">Alaska Time — Anchorage</option>
                <option value="Pacific/Honolulu">Hawaii Time — Honolulu</option>
                <option value="America/Toronto">Eastern Time — Toronto</option>
                <option value="America/Vancouver">Pacific Time — Vancouver</option>
                <option value="America/Sao_Paulo">Brasília Time — São Paulo</option>
                <option value="America/Argentina/Buenos_Aires">Argentina — Buenos Aires</option>
                <option value="America/Mexico_City">Central Time — Mexico City</option>
              </optgroup>
              <optgroup label="Europe">
                <option value="Europe/London">GMT/BST — London</option>
                <option value="Europe/Paris">CET/CEST — Paris</option>
                <option value="Europe/Berlin">CET/CEST — Berlin</option>
                <option value="Europe/Madrid">CET/CEST — Madrid</option>
                <option value="Europe/Rome">CET/CEST — Rome</option>
                <option value="Europe/Amsterdam">CET/CEST — Amsterdam</option>
                <option value="Europe/Brussels">CET/CEST — Brussels</option>
                <option value="Europe/Vienna">CET/CEST — Vienna</option>
                <option value="Europe/Warsaw">CET/CEST — Warsaw</option>
                <option value="Europe/Stockholm">CET/CEST — Stockholm</option>
                <option value="Europe/Helsinki">EET/EEST — Helsinki</option>
                <option value="Europe/Athens">EET/EEST — Athens</option>
                <option value="Europe/Bucharest">EET/EEST — Bucharest</option>
                <option value="Europe/Kiev">EET/EEST — Kyiv</option>
                <option value="Europe/Moscow">MSK — Moscow</option>
                <option value="Europe/Istanbul">TRT — Istanbul</option>
              </optgroup>
              <optgroup label="Asia &amp; Pacific">
                <option value="Asia/Dubai">GST — Dubai</option>
                <option value="Asia/Kolkata">IST — India</option>
                <option value="Asia/Dhaka">BST — Dhaka</option>
                <option value="Asia/Bangkok">ICT — Bangkok</option>
                <option value="Asia/Singapore">SGT — Singapore</option>
                <option value="Asia/Shanghai">CST — China</option>
                <option value="Asia/Tokyo">JST — Japan</option>
                <option value="Asia/Seoul">KST — Seoul</option>
                <option value="Asia/Jakarta">WIB — Jakarta</option>
                <option value="Asia/Karachi">PKT — Karachi</option>
                <option value="Asia/Riyadh">AST — Riyadh</option>
                <option value="Australia/Sydney">AEDT/AEST — Sydney</option>
                <option value="Australia/Melbourne">AEDT/AEST — Melbourne</option>
                <option value="Australia/Perth">AWST — Perth</option>
                <option value="Pacific/Auckland">NZDT/NZST — Auckland</option>
              </optgroup>
              <optgroup label="Africa">
                <option value="Africa/Cairo">EET — Cairo</option>
                <option value="Africa/Johannesburg">SAST — Johannesburg</option>
                <option value="Africa/Lagos">WAT — Lagos</option>
                <option value="Africa/Nairobi">EAT — Nairobi</option>
              </optgroup>
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
    </>
  )

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground tracking-tight">Settings</h1>
          <p className="text-muted-foreground mt-1">
            Configure your TikTok recorder settings
          </p>
        </div>
        <Button onClick={handleSave} disabled={updateSettingsMutation.isPending}>
          <Save className="h-4 w-4 mr-2" />
          {updateSettingsMutation.isPending ? 'Saving...' : 'Save Changes'}
        </Button>
      </div>

      {isDesktop ? (
        <>
          <div className="grid gap-6 md:grid-cols-2">
            {sectionContent}
          </div>
        </>
      ) : (
        <Tabs value={mobileTab} onValueChange={setMobileTab}>
          <TabsList className="w-full flex-wrap h-auto">
            {tabs.map((tab) => {
              const Icon = tab.icon
              return (
                <TabsItem key={tab.id} value={tab.id} className="gap-1.5">
                  <Icon className="h-3.5 w-3.5" />
                  {tab.label}
                </TabsItem>
              )
            })}
          </TabsList>
          {tabs.map((tab) => (
            <TabsPanel key={tab.id} value={tab.id}>
              {tab.id === 'status' && (
                <Card id="settings-status">
                  <CardHeader>
                    <CardTitle>System Status</CardTitle>
                    <CardDescription>Current system health and configuration status</CardDescription>
                  </CardHeader>
                  <CardBody className="space-y-4">
                    <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
                      <span className="text-sm font-medium">API Status</span>
                      <div className="flex items-center gap-2">
                        {health?.status === 'healthy' ? (
                          <>
                            <CheckCircle2 className="h-4 w-4 text-success" />
                            <span className="text-sm text-success">Healthy</span>
                          </>
                        ) : (
                          <>
                            <AlertCircle className="h-4 w-4 text-warning" />
                            <span className="text-sm text-warning">Unknown</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
                      <span className="text-sm font-medium">Recorder</span>
                      <div className="flex items-center gap-2">
                        {health?.recorder_available ? (
                          <>
                            <CheckCircle2 className="h-4 w-4 text-success" />
                            <span className="text-sm text-success">Ready</span>
                          </>
                        ) : (
                          <>
                            <AlertCircle className="h-4 w-4 text-warning" />
                            <span className="text-sm text-warning">Unavailable</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
                      <span className="text-sm font-medium">Region Status</span>
                      <div className="flex items-center gap-2">
                        {health?.country_blacklisted ? (
                          <>
                            <AlertCircle className="h-4 w-4 text-warning" />
                            <span className="text-sm text-warning">Restricted</span>
                          </>
                        ) : (
                          <>
                            <CheckCircle2 className="h-4 w-4 text-success" />
                            <span className="text-sm text-success">OK</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
                      <span className="text-sm font-medium">Cookies</span>
                      <div className="flex items-center gap-2">
                        {health?.cookies_configured ? (
                          <>
                            <CheckCircle2 className="h-4 w-4 text-success" />
                            <span className="text-sm text-success">Configured</span>
                          </>
                        ) : (
                          <>
                            <AlertCircle className="h-4 w-4 text-muted-foreground" />
                            <span className="text-sm text-muted-foreground">Not Set</span>
                          </>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center justify-between p-3 rounded-lg bg-secondary">
                      <span className="text-sm font-medium">Output Directory</span>
                      <span className="text-sm text-muted-foreground truncate max-w-[200px]">
                        {health?.recordings_dir || settings?.output_dir}
                      </span>
                    </div>
                    {resourceMeters}
                  </CardBody>
                </Card>
              )}
              {tab.id === 'cookies' && (
                <Card id="settings-cookies">
                  <CardHeader>
                    <CardTitle>TikTok Cookies</CardTitle>
                    <CardDescription>
                      Required for accessing restricted content.{' '}
                      <a href="https://github.com/Michele0303/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-set-cookies" target="_blank" rel="noopener noreferrer" className="text-primary-ink hover:underline inline-flex items-center gap-1">
                        Learn how <ExternalLink className="h-3 w-3" />
                      </a>
                    </CardDescription>
                  </CardHeader>
                  <CardBody className="space-y-4">
                    <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
                      <div className="grid gap-2">
                        <Label htmlFor="m-sessionid_ss">Session ID (sessionid_ss)</Label>
                        <Input id="m-sessionid_ss" name="sessionid_ss" type="password" autoComplete="off" placeholder="Enter your TikTok session ID" value={formData.cookies?.sessionid_ss || ''} onChange={(e) => setFormData({ ...formData, cookies: { ...formData.cookies, sessionid_ss: e.target.value, tt_target_idc: formData.cookies?.tt_target_idc || 'useast2a' } })} />
                      </div>
                    </form>
                    <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
                      <div className="grid gap-2">
                        <Label htmlFor="m-tt_target_idc">Target IDC (tt-target-idc)</Label>
                        <Input id="m-tt_target_idc" name="tt_target_idc" placeholder="useast2a" autoComplete="off" value={formData.cookies?.tt_target_idc || ''} onChange={(e) => setFormData({ ...formData, cookies: { ...formData.cookies, sessionid_ss: formData.cookies?.sessionid_ss || '', tt_target_idc: e.target.value } })} />
                      </div>
                    </form>
                    {chatAuthToggle('m-chat_authenticated')}
                  </CardBody>
                </Card>
              )}
              {tab.id === 'telegram' && (
                <Card id="settings-telegram">
                  <CardHeader>
                    <CardTitle>Telegram Integration</CardTitle>
                    <CardDescription>
                      Upload recordings to Telegram automatically.{' '}
                      <a href="https://github.com/Michele0303/tiktok-live-recorder/blob/main/docs/GUIDE.md#how-to-enable-upload-to-telegram" target="_blank" rel="noopener noreferrer" className="text-primary-ink hover:underline inline-flex items-center gap-1">
                        Learn how <ExternalLink className="h-3 w-3" />
                      </a>
                    </CardDescription>
                  </CardHeader>
                  <CardBody className="space-y-4">
                    <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
                      <div className="grid gap-2">
                        <Label htmlFor="m-api_id">API ID</Label>
                        <Input id="m-api_id" placeholder="Enter your Telegram API ID" autoComplete="off" value={formData.telegram?.api_id || ''} onChange={(e) => setFormData({ ...formData, telegram: { ...formData.telegram, api_id: e.target.value, api_hash: formData.telegram?.api_hash || '', chat_id: formData.telegram?.chat_id || 'me' } })} />
                      </div>
                    </form>
                    <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
                      <div className="grid gap-2">
                        <Label htmlFor="m-api_hash">API Hash</Label>
                        <Input id="m-api_hash" name="api_hash" type="password" autoComplete="off" placeholder="Enter your Telegram API Hash" value={formData.telegram?.api_hash || ''} onChange={(e) => setFormData({ ...formData, telegram: { ...formData.telegram, api_id: formData.telegram?.api_id || '', api_hash: e.target.value, chat_id: formData.telegram?.chat_id || 'me' } })} />
                      </div>
                    </form>
                    <form autoComplete="off" onSubmit={(e) => e.preventDefault()}>
                      <div className="grid gap-2">
                        <Label htmlFor="m-chat_id">Chat ID</Label>
                        <Input id="m-chat_id" placeholder="me" autoComplete="off" value={formData.telegram?.chat_id || ''} onChange={(e) => setFormData({ ...formData, telegram: { ...formData.telegram, api_id: formData.telegram?.api_id || '', api_hash: formData.telegram?.api_hash || '', chat_id: e.target.value } })} />
                      </div>
                    </form>
                  </CardBody>
                </Card>
              )}
              {tab.id === 'recording' && (
                <Card id="settings-recording">
                  <CardHeader>
                    <CardTitle>Recording Settings</CardTitle>
                    <CardDescription>Configure default recording behavior</CardDescription>
                  </CardHeader>
                  <CardBody className="space-y-4">
                    <div className="grid gap-2">
                      <Label htmlFor="m-proxy">HTTP Proxy</Label>
                      <Input id="m-proxy" placeholder="http://127.0.0.1:8080" value={formData.proxy || ''} onChange={(e) => setFormData({ ...formData, proxy: e.target.value || null })} />
                      <p className="text-xs text-muted-foreground">Use a proxy to bypass regional restrictions</p>
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="m-bitrate">Default Bitrate</Label>
                      <Input id="m-bitrate" placeholder="e.g., 1M, 1000k (leave empty for original)" value={formData.default_bitrate || ''} onChange={(e) => setFormData({ ...formData, default_bitrate: e.target.value || null })} />
                    </div>
                    <div className="grid gap-2">
                      <Label htmlFor="m-interval">Automatic Check Interval (minutes)</Label>
                      <Input id="m-interval" type="number" min="1" placeholder="5" value={formData.automatic_interval || 5} onChange={(e) => setFormData({ ...formData, automatic_interval: parseInt(e.target.value) || 5 })} />
                    </div>
                  </CardBody>
                </Card>
              )}
              {tab.id === 'cleanup' && (
                <Card id="settings-cleanup">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2"><Trash2 className="h-5 w-5" /> Auto-Cleanup</CardTitle>
                    <CardDescription>Automatically clean up old recordings to save disk space</CardDescription>
                  </CardHeader>
                  <CardBody className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <Label>Enable Auto-Cleanup</Label>
                        <p className="text-xs text-muted-foreground">Automatically process old recordings</p>
                      </div>
                      <Switch checked={formData.auto_cleanup?.enabled || false} onCheckedChange={() => setFormData({ ...formData, auto_cleanup: { ...formData.auto_cleanup, enabled: !formData.auto_cleanup?.enabled, days: formData.auto_cleanup?.days || 7, action: formData.auto_cleanup?.action || 'delete' } })} />
                    </div>
                    {formData.auto_cleanup?.enabled && (
                      <>
                        <div className="grid gap-2">
                          <Label>Retention Period</Label>
                          <Select value={String(formData.auto_cleanup?.days || 7)} onValueChange={(v) => setFormData({ ...formData, auto_cleanup: { ...formData.auto_cleanup, enabled: formData.auto_cleanup?.enabled || false, days: parseInt(String(v)), action: formData.auto_cleanup?.action || 'delete' } })}>
                            <SelectTrigger><SelectValue /></SelectTrigger>
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
                        </div>
                        <div className="grid gap-2">
                          <Label>Cleanup Action</Label>
                          <div className="flex gap-4">
                            <label className="flex items-center gap-2 cursor-pointer">
                              <input type="radio" name="m-cleanup_action" value="delete" checked={formData.auto_cleanup?.action === 'delete'} onChange={() => setFormData({ ...formData, auto_cleanup: { ...formData.auto_cleanup, enabled: formData.auto_cleanup?.enabled || false, days: formData.auto_cleanup?.days || 7, action: 'delete' } })} className="h-4 w-4" />
                              <Trash2 className="h-4 w-4" />
                              <span className="text-sm">Delete permanently</span>
                            </label>
                            <label className="flex items-center gap-2 cursor-pointer">
                              <input type="radio" name="m-cleanup_action" value="compress" checked={formData.auto_cleanup?.action === 'compress'} onChange={() => setFormData({ ...formData, auto_cleanup: { ...formData.auto_cleanup, enabled: formData.auto_cleanup?.enabled || false, days: formData.auto_cleanup?.days || 7, action: 'compress' } })} className="h-4 w-4" />
                              <Archive className="h-4 w-4" />
                              <span className="text-sm">Compress to backup</span>
                            </label>
                          </div>
                        </div>
                      </>
                    )}
                  </CardBody>
                </Card>
              )}
              {tab.id === 'timezone' && (
                <Card id="settings-timezone">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2"><Globe className="h-5 w-5" /> Display Timezone</CardTitle>
                    <CardDescription>All timestamps shown in the app will use this timezone</CardDescription>
                  </CardHeader>
                  <CardBody className="space-y-4">
                    <div className="grid gap-2">
                      <Label htmlFor="m-timezone">Timezone</Label>
                      <select id="m-timezone" className="flex h-10 w-full rounded-md border border-input-border bg-background px-3 py-2 text-sm" value={formData.timezone || 'UTC'} onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}>
                        <optgroup label="UTC"><option value="UTC">UTC</option></optgroup>
                        <optgroup label="Americas">
                          <option value="America/New_York">Eastern Time — New York (ET)</option>
                          <option value="America/Chicago">Central Time — Chicago (CT)</option>
                          <option value="America/Denver">Mountain Time — Denver (MT)</option>
                          <option value="America/Phoenix">Mountain Time — Phoenix (no DST)</option>
                          <option value="America/Los_Angeles">Pacific Time — Los Angeles (PT)</option>
                          <option value="America/Anchorage">Alaska Time — Anchorage</option>
                          <option value="Pacific/Honolulu">Hawaii Time — Honolulu</option>
                          <option value="America/Toronto">Eastern Time — Toronto</option>
                          <option value="America/Vancouver">Pacific Time — Vancouver</option>
                          <option value="America/Sao_Paulo">Brasília Time — São Paulo</option>
                          <option value="America/Argentina/Buenos_Aires">Argentina — Buenos Aires</option>
                          <option value="America/Mexico_City">Central Time — Mexico City</option>
                        </optgroup>
                        <optgroup label="Europe">
                          <option value="Europe/London">GMT/BST — London</option>
                          <option value="Europe/Paris">CET/CEST — Paris</option>
                          <option value="Europe/Berlin">CET/CEST — Berlin</option>
                          <option value="Europe/Madrid">CET/CEST — Madrid</option>
                          <option value="Europe/Rome">CET/CEST — Rome</option>
                          <option value="Europe/Amsterdam">CET/CEST — Amsterdam</option>
                          <option value="Europe/Brussels">CET/CEST — Brussels</option>
                          <option value="Europe/Vienna">CET/CEST — Vienna</option>
                          <option value="Europe/Warsaw">CET/CEST — Warsaw</option>
                          <option value="Europe/Stockholm">CET/CEST — Stockholm</option>
                          <option value="Europe/Helsinki">EET/EEST — Helsinki</option>
                          <option value="Europe/Athens">EET/EEST — Athens</option>
                          <option value="Europe/Bucharest">EET/EEST — Bucharest</option>
                          <option value="Europe/Kiev">EET/EEST — Kyiv</option>
                          <option value="Europe/Moscow">MSK — Moscow</option>
                          <option value="Europe/Istanbul">TRT — Istanbul</option>
                        </optgroup>
                        <optgroup label="Asia &amp; Pacific">
                          <option value="Asia/Dubai">GST — Dubai</option>
                          <option value="Asia/Kolkata">IST — India</option>
                          <option value="Asia/Dhaka">BST — Dhaka</option>
                          <option value="Asia/Bangkok">ICT — Bangkok</option>
                          <option value="Asia/Singapore">SGT — Singapore</option>
                          <option value="Asia/Shanghai">CST — China</option>
                          <option value="Asia/Tokyo">JST — Japan</option>
                          <option value="Asia/Seoul">KST — Seoul</option>
                          <option value="Asia/Jakarta">WIB — Jakarta</option>
                          <option value="Asia/Karachi">PKT — Karachi</option>
                          <option value="Asia/Riyadh">AST — Riyadh</option>
                          <option value="Australia/Sydney">AEDT/AEST — Sydney</option>
                          <option value="Australia/Melbourne">AEDT/AEST — Melbourne</option>
                          <option value="Australia/Perth">AWST — Perth</option>
                          <option value="Pacific/Auckland">NZDT/NZST — Auckland</option>
                        </optgroup>
                        <optgroup label="Africa">
                          <option value="Africa/Cairo">EET — Cairo</option>
                          <option value="Africa/Johannesburg">SAST — Johannesburg</option>
                          <option value="Africa/Lagos">WAT — Lagos</option>
                          <option value="Africa/Nairobi">EAT — Nairobi</option>
                        </optgroup>
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
              )}
              {tab.id === 'appearance' && (
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
              )}
            </TabsPanel>
          ))}
        </Tabs>
      )}
    </div>
  )
}
