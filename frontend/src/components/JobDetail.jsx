import { Link } from 'react-router-dom'
import { useJob } from '@/hooks/useJobs'
import { Skeleton } from './ui/skeleton'
import { Button, buttonVariants } from './ui/button'
import { Badge } from './ui/badge'
import { Card, CardHeader, CardTitle, CardContent } from './ui/card'
import { formatDate } from '@/lib/format'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import ErrorAlert from './ErrorAlert'
import ReactMarkdown from 'react-markdown'

export const JobDetail = ({ jobId }) => {
    const { data: job, isPending, isError, error } = useJob(jobId)

    if (isPending) {
        // Shaped like the real content below (back link / title / badges /
        // posting card) so the page doesn't jump once data arrives.
        return (
            <div className="mx-auto max-w-3xl space-y-6">
                <Skeleton className="h-8 w-24" />
                <div className="space-y-3">
                    <Skeleton className="h-8 w-2/3" />
                    <div className="flex gap-2">
                        <Skeleton className="h-5 w-20" />
                        <Skeleton className="h-5 w-32" />
                    </div>
                </div>
                <Card>
                    <CardContent className="space-y-3 pt-6">
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-5/6" />
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-3/4" />
                    </CardContent>
                </Card>
            </div>
        )
    }

    if (isError) {
        return (
            <div className="mx-auto max-w-3xl">
                <ErrorAlert error={error} title="Couldn't load this job" />
            </div>
        )
    }

    return (
        <div className="mx-auto max-w-3xl space-y-6">
            <Link to="/jobs" className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
                <ArrowLeft />
                All jobs
            </Link>

            <header className="space-y-3">
                <h1 className="text-2xl font-semibold tracking-tight">{job.title}</h1>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-muted-foreground">
                    <Badge variant="secondary">{job.board_token}</Badge>
                    <span>Fetched {formatDate(job.fetched_at)}</span>
                    {job.url && (
                        <Button
                            variant="link"
                            size="sm"
                            render={<a href={job.url} target="_blank" rel="noreferrer" />}
                        >
                            Original posting
                            <ExternalLink />
                        </Button>
                    )}
                </div>
            </header>

            <Card>
                <CardHeader>
                    <CardTitle>Posting</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-heading prose-headings:font-medium">
                        <ReactMarkdown>{job.description}</ReactMarkdown>
                    </div>
                </CardContent>
            </Card>
        </div>
    )
}
