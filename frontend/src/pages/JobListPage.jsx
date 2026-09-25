import { JobsTable } from "@/components/JobsTable"
import { Alert, AlertTitle, AlertAction } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { useProfile } from "@/hooks/useProfile"
import { useAuth } from "@clerk/clerk-react"
import { Link } from "react-router-dom"
import { Loader2 } from "lucide-react"
export function JobListPage() {
  const { isSignedIn } = useAuth()
  // Skip the profile fetch entirely while signed out - there's no auth
  // token to fetch with yet, and nothing to show a "no profile" banner
  // for until we actually know who's signed in.
  const { data: profile, isPending } = useProfile({ enabled: isSignedIn })

  return (
    <div className="space-y-4">
      {/* Gated on isSignedIn too, not just isPending: useProfile is
          `enabled: isSignedIn`, and a disabled query never leaves React
          Query's "pending" status since it never actually runs - without
          this guard, a signed-out visitor would see this spinner forever
          for a fetch that's never going to happen. */}
      {isSignedIn && isPending && (
        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading your profile…
        </div>
      )}
      {!isSignedIn && (
        <Alert>
          <AlertTitle>Sign in to score jobs against your resume</AlertTitle>
          <AlertAction>
            <Button size="sm" render={<Link to="/sign-in" />}>Sign In</Button>
          </AlertAction>
        </Alert>
      )}

      {/* Signed in, and their profile query has resolved to "no profile
          submitted yet" (data === null - see useProfile.js). Guarded on
          !isPending so this doesn't flash on screen for the brief window
          before the fetch resolves (profile is `undefined`, not `null`,
          while loading). */}
      {isSignedIn && !isPending && profile === null && (
        <Alert>
          <AlertTitle>Upload your resume to score jobs</AlertTitle>
          <AlertAction>
            <Button size="sm" render={<Link to="/profile" />}>Upload resume</Button>
          </AlertAction>
        </Alert>
      )}

      <JobsTable />
    </div>
  )
}
