import { RedirectToSignIn, SignedIn, SignedOut } from '@clerk/clerk-react'

export function ProtectedRoute({ children }) {
  return (
    <>
      <SignedIn>{children}</SignedIn>
      <SignedOut>
        <RedirectToSignIn />
      </SignedOut>
    </>
  )
}
