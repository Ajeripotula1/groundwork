import { Link } from 'react-router-dom'
import { buttonVariants } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4">
      <p className="text-lg text-muted-foreground">Page not found</p>
      <Link to="/" className={buttonVariants({ variant: 'outline' })}>
        Back home
      </Link>
    </div>
  )
}