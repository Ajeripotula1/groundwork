// TODO: useParams() jobId -> useJob() + useScoreFit(); gated Job Agent chat

import { useParams } from "react-router-dom"
import { NotFoundPage } from "./NotFoundPage"
import { JobDetail } from "@/components/JobDetail"
// + conversation history once a score exists
export const JobDetailPage = () => {
  
  const jobId = Number(useParams().jobId)
  
  if (!jobId || !Number.isInteger(jobId)) return <NotFoundPage/>

  return (
    <div>
      <JobDetail jobId = {jobId}/>
    </div>
  )
}
