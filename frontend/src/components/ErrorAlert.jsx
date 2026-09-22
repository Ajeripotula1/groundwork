import React from 'react'
import { Alert, AlertTitle, AlertDescription } from './ui/alert'
import { Button } from './ui/button'

const ErrorAlert = ({ error = null, title = "Something went wrong", onRetry = null }) => {
    if (!error) return null

    return (
        <Alert variant="destructive">
            <AlertTitle>{title}</AlertTitle>
            <AlertDescription>{error.message}</AlertDescription>
            {onRetry && (
                <Button variant="outline" size="sm" onClick={onRetry}>
                    Try again
                </Button>
            )}
        </Alert>
    )

}

export default ErrorAlert