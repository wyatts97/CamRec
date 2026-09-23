import { Link } from 'react-router-dom'
import { FileQuestion } from 'lucide-react'
import { Button } from '@/components/selia/button'

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="rounded-xl bg-primary-subtle p-3">
        <FileQuestion className="h-6 w-6 text-primary-ink" aria-hidden="true" />
      </div>
      <div className="space-y-1">
        <h1 className="text-xl font-semibold text-foreground">Page not found</h1>
        <p className="text-sm text-muted-foreground">
          That URL doesn&apos;t match any page in TikRec.
        </p>
      </div>
      <Button variant="primary" render={<Link to="/" />}>
        Back to dashboard
      </Button>
    </div>
  )
}
