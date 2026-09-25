import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { queryKeys } from "./queryKeys"
import { useApi } from "./useApi"
import { ApiError } from "@/api/client"

// Get the signed-in user's latest profile. No `id` param needed - GET
// /profile resolves "your latest profile" server-side from the Clerk
// auth token (see jobsentinel/api/routers/profile.py's read_profile),
// the same way get_current_user_id already scopes every profile route.
//
// A brand-new user who hasn't uploaded a resume yet gets a 404 from the
// API - that's an expected, normal state (not a real failure), so we
// catch it here and resolve to `null` instead of leaving the query in
// an error state. That lets ProfilePage tell "no profile yet, show the
// upload form" (data === null) apart from "the request actually failed"
// (isError === true) instead of treating both the same way. Any other
// failure (network down, 401, 500, ...) is re-thrown as-is so React
// Query puts the query in an error state and callers can render it via
// isError/error - see ErrorAlert.jsx, which reads error.message
// directly, which is why we re-throw the original ApiError rather than
// replacing it with a generic Error (that would lose the server's
// actual detail message).
//
// `enabled`: lets a caller defer firing this query - e.g. only run it
// once some other condition is true - instead of it always fetching on
// mount. Defaults to true so `useProfile()` with no args behaves like a
// normal query. See useQuery's own `enabled` option.
export const useProfile = ({ enabled = true } = {}) => {
    const api = useApi()

    return useQuery({
        queryKey: queryKeys.profile,
        queryFn: async () => {
            try {
                return await api('/profile')
            } catch (error) {
                if (error instanceof ApiError && error.status === 404) {
                    return null
                }
                throw error
            }
        },
        enabled,
    })
}

// Submit a resume PDF for extraction + persistence. This is a mutation,
// not a query - it's a one-shot "do a thing" call triggered by user
// action (picking a file), not data the page loads passively on mount.
//
// POST /profile/upload expects multipart/form-data (it's a FastAPI
// UploadFile param), not JSON, so the body has to be a FormData
// instance - apiFetch (api/client.js) already special-cases FormData
// bodies: it skips setting a Content-Type header so the browser can set
// `multipart/form-data; boundary=...` itself, which a manually-set
// header would clobber.
export const useUploadProfile = () => {
    const api = useApi()
    const queryClient = useQueryClient()

    return useMutation({
        mutationFn: (file) => {
            const formData = new FormData()
            formData.append('file', file)
            return api('/profile/upload', { method: 'POST', body: formData })
        },
        // POST /profile/upload's response body is the freshly-extracted
        // ExtractedProfile - the exact same shape GET /profile returns.
        // Since we already have that data in hand, we write it straight
        // into the `profile` query's cache instead of just invalidating
        // and letting useProfile refetch: same end result, one fewer
        // round trip to the API.
        onSuccess: (profile) => {
            queryClient.setQueryData(queryKeys.profile, profile)
        },
    })
}
