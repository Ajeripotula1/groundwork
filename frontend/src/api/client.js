const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

// Every request needs the Clerk session token attached as a Bearer header.
// Token retrieval is async and only available inside a component/hook
// context (Clerk's `useAuth().getToken`), so callers - the React Query hooks
// you write in src/hooks - pass it in rather than this module importing Clerk
// itself.

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

const extractDetail = (body, fallback) => {
  if (body == null) return fallback
  const { detail } = body
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => item?.msg).filter(Boolean).join('; ') || fallback
  }
  return fallback
}

export const apiFetch = async (path, { method = 'GET', body, getToken, headers, ...rest } = {}) => {
  const token = await getToken?.()
  const isFormData = body instanceof FormData
  const hasBody = body !== undefined

  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      method,
      headers: {
        ...(hasBody && !isFormData ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: hasBody ? (isFormData ? body : JSON.stringify(body)) : undefined,
    })
  } catch {
    throw new ApiError(0, "Can't reach the server. Check that the API is running.")
  }

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null)
    const detail = extractDetail(errorBody, response.statusText)
    throw new ApiError(response.status, detail)
  }

  if (response.status === 204) {
    return null
  }

  return response.json()
}