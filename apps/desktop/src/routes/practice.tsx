import { createFileRoute } from '@tanstack/react-router'

import { PracticePage } from '@/features/practice/practice-page'

export const Route = createFileRoute('/practice')({
  component: PracticePage,
})
