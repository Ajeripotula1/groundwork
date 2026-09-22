import { useCallback } from "react";
import { apiFetch } from "@/api/client";
import { useAuth } from "@clerk/clerk-react";

// Memoization: cache results of expensive computations 
// useCallback(fn, [dependencies]): memoize function (api fetch)
export const useApi = () => {
    /* Return SAME function reference across re-renders (only change when Clerk Token Changes) */ 
    
    // get clerk auth for get JWT
    const {getToken} = useAuth()
    // memoize apiFetch call and pass token
    return useCallback(
        (path, options) => apiFetch(path, { ...options, getToken }),
        [getToken]
    )

}