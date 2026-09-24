// Fetch Jobs from API

import { useQuery } from "@tanstack/react-query"
import { useApi } from "./useApi"
import { queryKeys } from "./queryKeys"

// Fetch all jobs
export const useJobs = () => {
    const api = useApi()
    return useQuery({
        queryKey: queryKeys.jobs,
        queryFn: () => api('/jobs'),
        staleTime: 5 * 60_000 
    })
}

// Fetch Single job
export const useJob = (jobId) =>{
    const api = useApi()
    return useQuery({
        queryKey: queryKeys.job(jobId),
        queryFn: () => api(`/jobs/${jobId}`),
        staleTime: 5 * 60_000 
    })
}