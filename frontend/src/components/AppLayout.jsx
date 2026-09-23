import { Link, NavLink, Outlet } from 'react-router-dom'
import { SignedIn, SignedOut, UserButton } from '@clerk/clerk-react'
import { buttonVariants } from '@/components/ui/button'

// Layout Wrapper for all pages (Navbar and centred content)
export function AppLayout() {
  return (
    <>
      <header className="sticky top-0 z-10 border-b bg-background">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4">
          <Link to="/" className="font-semibold">
            JobSentinel
          </Link>

          <NavLink
            to="/jobs"
            className={({ isActive }) =>
              isActive ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'
            }
          >
            Jobs
          </NavLink>

          <NavLink
            to="/profile"
            className={({ isActive }) =>
              isActive ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'
            }
          >
            Profile
          </NavLink>

          <div className="ml-auto flex items-center gap-2">
            <SignedIn>
              <UserButton />
            </SignedIn>
            <SignedOut>
              <Link to="/sign-in" className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
                Sign in
              </Link>
              <Link to="/sign-up" className={buttonVariants({ size: 'sm' })}>
                Sign up
              </Link>
            </SignedOut>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </>
  )
}