import { useRef } from 'react'
import { Loader2 } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import ErrorAlert from '@/components/ErrorAlert'
import { useUploadProfile } from '@/hooks/useProfile'

// Resume upload card. `hasProfile` (from the page's useProfile() call)
// tells us whether the signed-in user already has a profile on file, so
// the button can say "new version" instead of implying this is
// necessarily their first upload. Every submission is a new row
// server-side either way - profiles are append-only history, never
// overwritten in place (see jobsentinel/db/profile.py) - so "new
// version" is accurate regardless of what hasProfile says; it's purely
// wording, not a different code path.
export function ProfileUpload({ hasProfile }) {
  // The real <input type="file"> is rendered but visually hidden - we
  // trigger it programmatically (inputRef.current.click()) from the
  // Button below. That gets us shadcn's button styling instead of the
  // browser's default file-input chrome, while the native file picker,
  // keyboard access, etc. all still come from a real <input> underneath.
  const inputRef = useRef(null)
  const upload = useUploadProfile()

  const handleFileChange = (e) => {
    const file = e.target.files?.[0]
    if (file) {
      upload.mutate(file)
    }
    // Clear the input's value after reading it. Without this, picking
    // the exact same file twice in a row fires onChange the first time
    // but not the second - the browser sees the <input>'s value as
    // unchanged and no-ops. Resetting it makes every pick "new" again.
    e.target.value = ''
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Resume</CardTitle>
        <CardDescription>
          Upload a PDF. Text-based PDFs only — scanned images aren't supported.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={handleFileChange}
        />

        <Button onClick={() => inputRef.current.click()} disabled={upload.isPending}>
          {upload.isPending ? (
            <>
              <Loader2 className="animate-spin" />
              Extracting your profile…
            </>
          ) : hasProfile ? (
            'Upload a new version'
          ) : (
            'Upload resume'
          )}
        </Button>

        {/* No client-side PDF validation here on purpose - `accept`
            steers the OS file picker, and the server's 415 (wrong
            content-type) / 422 (unreadable or textless PDF) responses
            already carry user-readable detail strings (see
            extract_text_from_pdf's ValueError messages and the 415
            check in POST /profile/upload), so upload.error is safe to
            render as-is with no re-wording on our end. */}
        <ErrorAlert error={upload.error} title="Upload failed" />
      </CardContent>
    </Card>
  )
}
