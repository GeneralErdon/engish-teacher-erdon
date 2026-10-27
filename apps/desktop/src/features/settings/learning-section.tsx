import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Loader2 } from 'lucide-react'

import { SegmentedControl } from '@/components/segmented-control'
import { Skeleton } from '@/components/ui/skeleton'
import { api, type Schemas } from '@/lib/api/client'
import { errorMessage } from '@/lib/api/errors'

import { LoadError } from './load-error'
import { languageName, learnerQuery } from './use-learner'

type Profile = Schemas['LearnerProfile']

const LEVELS = (['A1', 'A2', 'B1', 'B2', 'C1', 'C2'] as const).map((level) => ({
  value: level,
  label: level,
}))

/** Level and explanation language. Every change is saved at once. */
export function LearningSection() {
  const queryClient = useQueryClient()
  const learner = useQuery(learnerQuery)
  const save = api.useMutation('put', '/v1/learner', {
    onSuccess: (saved) => {
      queryClient.setQueryData(learnerQuery.queryKey, saved)
    },
  })

  if (!learner.data) {
    return learner.isError ? (
      <LoadError error={learner.error} onRetry={() => void learner.refetch()} />
    ) : (
      <Skeleton aria-label="Loading" className="h-24 rounded-xl" />
    )
  }

  const profile = learner.data
  const update = (change: Partial<Profile>) => {
    save.mutate({ body: { level: profile.level, explanations: profile.explanations, ...change } })
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">Your level (CEFR)</span>
        <SegmentedControl
          label="Level"
          options={LEVELS}
          value={profile.level}
          disabled={save.isPending}
          onChange={(level) => {
            update({ level })
          }}
        />
        <p className="text-muted-foreground text-xs">
          The tutor adapts its vocabulary and the corrections it points out to this level.
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">Explain my mistakes in</span>
        <SegmentedControl
          label="Explanations"
          options={[
            { value: 'english', label: 'English' },
            { value: 'native', label: languageName(profile.native_language) },
          ]}
          value={profile.explanations}
          disabled={save.isPending}
          onChange={(explanations) => {
            update({ explanations })
          }}
        />
      </div>

      <p role="status" className="text-muted-foreground flex min-h-5 items-center gap-1.5 text-xs">
        {save.isPending && (
          <>
            <Loader2 className="size-3 animate-spin" aria-hidden="true" /> Saving…
          </>
        )}
        {save.isSuccess && (
          <>
            <Check className="text-success size-3" aria-hidden="true" /> Saved
          </>
        )}
        {save.isError && <span className="text-destructive">{errorMessage(save.error)}</span>}
      </p>
    </div>
  )
}
