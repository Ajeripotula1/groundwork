import { ProfileUpload } from "@/components/profile/ProfileUpload"
import { ProfileView } from "@/components/profile/ProfileView"
import { useProfile } from "@/hooks/useProfile"
import { Skeleton } from "@/components/ui/skeleton"
import ErrorAlert from "@/components/ErrorAlert"

export function ProfilePage() {
  const { data: profile, isPending, isError, error, refetch } = useProfile()

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Your profile</h1>

      {/* Rendered unconditionally, above the fetch-state block below - it
          doesn't care whether the profile query is loading, failed, or
          empty, only whether the CURRENT data says a profile exists.
          Re-uploading doesn't touch this query directly: useUploadProfile's
          onSuccess writes the fresh result straight into the `profile`
          cache entry (see useProfile.js) rather than invalidating it, so
          whatever's rendered below - the old ProfileView - stays on screen
          unchanged until that new data actually lands. */}
      <ProfileUpload hasProfile={profile != null} />

      {isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : isError ? (
        <ErrorAlert error={error} title="Couldn't load your profile" onRetry={refetch} />
      ) : profile === null ? (
        <p className="text-muted-foreground">No resume yet — upload one above.</p>
      ) : (
        <ProfileView profile={profile} />
      )}
    </div>
  )
}
