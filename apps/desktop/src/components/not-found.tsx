import { Link } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'

export function NotFound() {
  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-3xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">This page does not exist (yet).</p>
      <Button asChild>
        <Link to="/">Back home</Link>
      </Button>
    </div>
  )
}
