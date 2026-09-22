
// TanStack Query (cache) keys

export const queryKeys = {
    jobs: ['jobs'], // all jobs
    job: (id) => ['job', id], // key specific job
    profile: ['profile'], // only show user their own (singular profile)
    score: (id) => ['score', id], // score against SPECIFIC job id
    agent: (id) => ['agent', id] // scope agent interactions to specific job id
}