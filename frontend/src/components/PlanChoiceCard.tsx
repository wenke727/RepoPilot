import { formatSelectedOptions, isPlanAnswersComplete } from '../plan/selection'
import type { NormalizedPlanQuestion } from '../plan/selection'

interface Props {
  title: string
  questions: NormalizedPlanQuestion[]
  answers: Record<string, string>
  onSelect?: (questionId: string, optionKey: string) => void
  showConfirmHint?: boolean
  selectedOnly?: boolean
  className?: string
}

export default function PlanChoiceCard({
  title,
  questions,
  answers,
  onSelect,
  showConfirmHint = false,
  selectedOnly = false,
  className = '',
}: Props) {
  const interactive = typeof onSelect === 'function'
  const allAnswered = isPlanAnswersComplete(questions, answers)
  const selectedRows = formatSelectedOptions(questions, answers)

  return (
    <section className={`plan-choice-card ${interactive ? 'plan-choice-card-interactive' : 'plan-choice-card-readonly'} ${className}`.trim()}>
      <div className="plan-choice-title">{title}</div>
      {selectedOnly ? (
        selectedRows.length === 0 ? (
          <div className="plan-choice-empty">暂无已确认选项</div>
        ) : (
          selectedRows.map((row) => (
            <div className="plan-choice-question" key={row.questionId}>
              <div className="plan-choice-question-title">{row.title}</div>
              <div className="plan-choice-options">
                <button type="button" className="plan-choice-pill plan-choice-pill-active plan-choice-pill-readonly" disabled>
                  <span className="plan-choice-pill-label">{row.optionLabel}</span>
                  {row.optionDescription && <span className="plan-choice-pill-desc">（{row.optionDescription}）</span>}
                </button>
              </div>
            </div>
          ))
        )
      ) : (
        questions.map((question) => (
          <div className="plan-choice-question" key={question.id}>
            <div className="plan-choice-question-title">{question.title}</div>
            {question.question && <div className="plan-choice-question-text">{question.question}</div>}
            <div className="plan-choice-options">
              {question.options.map((option) => {
                const active = answers[question.id] === option.key
                return (
                  <button
                    key={option.key}
                    type="button"
                    className={`plan-choice-pill ${active ? 'plan-choice-pill-active' : ''} ${interactive ? '' : 'plan-choice-pill-readonly'}`.trim()}
                    onClick={() => onSelect?.(question.id, option.key)}
                    disabled={!interactive}
                  >
                    <span className="plan-choice-pill-label">{option.label}</span>
                    {option.description && <span className="plan-choice-pill-desc">（{option.description}）</span>}
                  </button>
                )
              })}
            </div>
          </div>
        ))
      )}
      {showConfirmHint && !allAnswered && questions.length > 0 && (
        <div className="plan-choice-hint">请先完成所有选项后再确认执行。</div>
      )}
    </section>
  )
}

