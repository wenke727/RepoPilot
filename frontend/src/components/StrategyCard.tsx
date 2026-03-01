import { useState } from 'react'
import type { ExecStrategy, StrategyStep, StrategyStepStatus } from '../types'

interface Props {
  strategy: ExecStrategy
  className?: string
}

const STATUS_LABELS: Record<StrategyStepStatus, string> = {
  pending: '待执行',
  running: '执行中',
  done: '已完成',
  failed: '失败',
  skipped: '已跳过',
}

function StepIcon({ status }: { status: StrategyStepStatus }) {
  const base = 'strategy-step-icon'
  if (status === 'done') return <span className={`${base} ${base}-done`} title="已完成">✓</span>
  if (status === 'failed') return <span className={`${base} ${base}-failed`} title="失败">✕</span>
  if (status === 'skipped') return <span className={`${base} ${base}-skipped`} title="已跳过">−</span>
  if (status === 'running') return <span className={`${base} ${base}-running`} title="执行中">⋯</span>
  return <span className={`${base} ${base}-pending`} title="待执行">○</span>
}

export default function StrategyCard({ strategy, className = '' }: Props) {
  const [decisionsOpen, setDecisionsOpen] = useState(false)
  const hasDecisions = strategy.decisions && strategy.decisions.length > 0

  return (
    <section className={`strategy-card ${className}`.trim()}>
      <div className="strategy-card-header">
        <span className="strategy-card-template">{strategy.template || 'AGENTIC'}</span>
        <span className="strategy-card-title">执行策略</span>
      </div>

      {strategy.rationale && (
        <div className="strategy-rationale">{strategy.rationale}</div>
      )}

      <div className="strategy-steps">
        <div className="strategy-steps-title">步骤</div>
        <ul className="strategy-step-list">
          {strategy.steps.map((step: StrategyStep, idx: number) => (
            <li
              key={`${step.type}-${idx}`}
              className={`strategy-step strategy-step-${step.status}`}
            >
              <StepIcon status={step.status} />
              <div className="strategy-step-body">
                <span className="strategy-step-label">{step.label || step.type}</span>
                <span className="strategy-step-status">{STATUS_LABELS[step.status]}</span>
                {step.reason && (
                  <div className="strategy-step-reason">{step.reason}</div>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>

      {hasDecisions && (
        <div className="strategy-decisions">
          <button
            type="button"
            className="strategy-decisions-toggle"
            onClick={() => setDecisionsOpen(!decisionsOpen)}
            aria-expanded={decisionsOpen}
          >
            关键决策 ({strategy.decisions.length})
          </button>
          {decisionsOpen && (
            <ul className="strategy-decision-list">
              {strategy.decisions.map((d) => (
                <li key={d.key} className="strategy-decision">
                  <div className="strategy-decision-question">{d.question}</div>
                  <div className="strategy-decision-choice">{d.choice}</div>
                  {d.reason && (
                    <div className="strategy-decision-reason">{d.reason}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
