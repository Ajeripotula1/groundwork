// Fetch Jobs from API

import { useQuery } from "@tanstack/react-query"
import { useApi } from "./useApi"
import { queryKeys } from "./queryKeys"

export const useJobs = () => {
    const api = useApi()
    return useQuery({
        queryKey: queryKeys.jobs,
        queryFn: () => api('/jobs'),
        staleTime: 5 * 60_000 
    })
}