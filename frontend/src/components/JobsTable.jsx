import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useJobs } from '@/hooks/useJobs'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
// import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert'
import ErrorAlert from './ErrorAlert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { formatDate } from '@/lib/format'

export const JobsTable = () => {
  const { data: jobs, isPending, isError, error } = useJobs()
  const [filter, setFilter] = useState('')
  // Client-side only - per BUILD_PLAN.md's Slice 7 design exercise, ~600
  // rows from the one loaded board is small enough to filter in-browser;
  // no backend pagination/filtering exists yet (that's deferred until real
  // multi-company following makes the row count actually large). useMemo
  // just avoids re-filtering on renders that touch neither `jobs` nor
  // `filter` (e.g. once there's sort state too).
  const filteredJobs = useMemo(() => {
    if (!jobs) return []
    const needle = filter.trim().toLowerCase()
    if (!needle) return jobs
    return jobs.filter((job) => job.title.toLowerCase().includes(needle))
  }, [jobs, filter])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Jobs</h1>
        {jobs && (
          <p className="text-sm text-muted-foreground">
            Showing {filteredJobs.length} of {jobs.length} jobs
          </p>
        )}
      </div>

      <Input
        type="text"
        placeholder="Search jobs by title..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />

      {isError && ( <ErrorAlert error={error} title="Couldn't load jobs"/>)}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Title</TableHead>
            <TableHead>Company</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Last synced</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isPending &&
            Array.from({ length: 10 }).map((_, i) => (
              <TableRow key={i}>
                <TableCell colSpan={4}>
                  <Skeleton className="h-5 w-full" />
                </TableCell>
              </TableRow>
            ))}

          {!isPending && !isError && filteredJobs.length === 0 && (
            <TableRow>
              <TableCell colSpan={4} className="text-center text-muted-foreground">
                {jobs && jobs.length === 0 ? 'No jobs loaded yet.' : `No jobs match "${filter}".`}
              </TableCell>
            </TableRow>
          )}

          {filteredJobs.map((job) => (
            <TableRow key={job.id}>
              <TableCell className="font-medium">
                <Link to={`/jobs/${job.id}`} className="hover:underline">
                  {job.title}
                </Link>
              </TableCell>
              <TableCell>{job.board_token}</TableCell>
              <TableCell>
                <Badge variant="outline">{job.source}</Badge>
              </TableCell>
              <TableCell className="text-muted-foreground">{formatDate(job.fetched_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
