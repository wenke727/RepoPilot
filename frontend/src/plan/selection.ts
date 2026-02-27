import type { Task } from '../types'

export interface NormalizedPlanOption {
  key: string
  label: string
  description: string
}

export interface NormalizedPlanQuestion {
  id: string
  title: string
  question: string
  options: NormalizedPlanOption[]
  recommendedOptionKey?: string
}

export interface NormalizedPlanResult {
  summary: string
  steps: string[]
  risks: string[]
  affectedFiles: string[]
  newDependencies: string[]
  estimatedTime: string
  validation: string
  rollback: string
  recommendedPrompt: string
  questions: NormalizedPlanQuestion[]
}

export interface SelectedOptionItem {
  questionId: string
  title: string
  optionKey: string
  optionLabel: string
  optionDescription: string
}

export interface PlanCardPayload {
  type: 'plan_card'
  plan: NormalizedPlanResult
  answers: Record<string, string>
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => asString(item))
    .filter((item) => item.length > 0)
}

function normalizeQuestion(value: unknown, index: number): NormalizedPlanQuestion | null {
  const view = asRecord(value)
  if (!view) return null

  const id = asString(view.id) || `q${index + 1}`
  const title = asString(view.title) || id
  const question = asString(view.question)
  const recommendedOptionKey = asString(view.recommended_option_key ?? view.recommendedOptionKey) || undefined

  const optionsRaw = Array.isArray(view.options) ? view.options : []
  const options: NormalizedPlanOption[] = []
  for (const [optionIndex, optionRaw] of optionsRaw.entries()) {
    const optionView = asRecord(optionRaw)
    if (!optionView) continue
    const key = asString(optionView.key) || `o${optionIndex + 1}`
    const label = asString(optionView.label) || key
    const description = asString(optionView.description)
    options.push({ key, label, description })
  }

  return { id, title, question, options, recommendedOptionKey }
}

export function normalizePlanResult(planResult: unknown): NormalizedPlanResult {
  const view = asRecord(planResult)
  if (!view) {
    return {
      summary: '',
      steps: [],
      risks: [],
      affectedFiles: [],
      newDependencies: [],
      estimatedTime: '',
      validation: '',
      rollback: '',
      recommendedPrompt: '',
      questions: [],
    }
  }

  const questionsRaw = Array.isArray(view.questions) ? view.questions : []
  const questions = questionsRaw
    .map((item, index) => normalizeQuestion(item, index))
    .filter((item): item is NormalizedPlanQuestion => !!item)

  return {
    summary: asString(view.summary),
    steps: asStringArray(view.steps),
    risks: asStringArray(view.risks),
    affectedFiles: asStringArray(view.affected_files ?? view.affectedFiles),
    newDependencies: asStringArray(view.new_dependencies ?? view.newDependencies),
    estimatedTime: asString(view.estimated_time ?? view.estimatedTime),
    validation: asString(view.validation),
    rollback: asString(view.rollback),
    recommendedPrompt: asString(view.recommended_prompt ?? view.recommendedPrompt),
    questions,
  }
}

export function deriveInitialAnswers(
  questions: NormalizedPlanQuestion[],
  existingAnswers: Record<string, string> | undefined,
): Record<string, string> {
  const prev = existingAnswers ?? {}
  const next: Record<string, string> = {}

  for (const question of questions) {
    const selected = prev[question.id]
    const selectedValid = question.options.some((option) => option.key === selected)
    if (selectedValid) {
      next[question.id] = selected
      continue
    }
    const recommended = question.recommendedOptionKey
    if (recommended && question.options.some((option) => option.key === recommended)) {
      next[question.id] = recommended
    }
  }

  return next
}

export function isPlanAnswersComplete(
  questions: NormalizedPlanQuestion[],
  answers: Record<string, string> | undefined,
): boolean {
  if (questions.length === 0) return true
  const current = answers ?? {}
  return questions.every((question) => question.options.some((option) => option.key === current[question.id]))
}

export function formatSelectedOptions(
  questions: NormalizedPlanQuestion[],
  answers: Record<string, string> | undefined,
): SelectedOptionItem[] {
  const current = answers ?? {}
  const rows: SelectedOptionItem[] = []

  for (const question of questions) {
    const selectedKey = current[question.id]
    if (!selectedKey) continue
    const option = question.options.find((item) => item.key === selectedKey)
    rows.push({
      questionId: question.id,
      title: question.title || question.id,
      optionKey: selectedKey,
      optionLabel: option?.label ?? selectedKey,
      optionDescription: option?.description ?? '',
    })
  }

  return rows
}

export function hasPlanDetails(plan: NormalizedPlanResult): boolean {
  return Boolean(
    plan.summary ||
    plan.estimatedTime ||
    plan.validation ||
    plan.rollback ||
    plan.recommendedPrompt ||
    plan.steps.length > 0 ||
    plan.risks.length > 0 ||
    plan.affectedFiles.length > 0 ||
    plan.newDependencies.length > 0
  )
}

export function detectPlanQuestionNoise(message: string): boolean {
  if (!message) return false
  const normalized = message.toLowerCase()
  if (!normalized.includes('"questions"')) return false
  if (normalized.includes('"recommended_option_key"')) return true
  if (normalized.includes('"recommendedoptionkey"')) return true
  return normalized.includes('"question":') && normalized.includes('"options"')
}

export function toPlanCardPayload(task: Task): PlanCardPayload | null {
  if (!task.plan_result) return null
  const plan = normalizePlanResult(task.plan_result)
  const answers = task.plan_answers ?? {}
  return {
    type: 'plan_card',
    plan,
    answers,
  }
}

export function parsePlanCardPayload(raw: string): PlanCardPayload | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Record<string, unknown>
    if (!value || value.type !== 'plan_card') return null
    const plan = normalizePlanResult(value.plan)
    const answersRaw = asRecord(value.answers)
    const answers: Record<string, string> = {}
    if (answersRaw) {
      for (const [key, item] of Object.entries(answersRaw)) {
        const answer = asString(item)
        if (answer) answers[key] = answer
      }
    }
    return { type: 'plan_card', plan, answers }
  } catch {
    return null
  }
}
