import type { ReactNode } from 'react'
import { Button, Progress, Tag, Tooltip } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import type { Stage, StageKey } from './types'

const STATUS_META: Record<Stage['status'], { color: string; text: string }> = {
  done: { color: 'green', text: '已完成' },
  running: { color: 'blue', text: '进行中' },
  partial: { color: 'orange', text: '部分完成' },
  not_started: { color: 'default', text: '未开始' },
  blocked: { color: 'red', text: '阻塞' },
  failed: { color: 'red', text: '失败' },
}

export type StageCardProps = {
  stage: Stage
  index: number
  canRun: boolean
  busy: boolean
  externalLink?: ReactNode
  onRun: (key: StageKey) => void
}

export function StageCard({ stage, index, canRun, busy, externalLink, onRun }: StageCardProps) {
  const meta = STATUS_META[stage.status] || STATUS_META.not_started
  const isRunning = stage.status === 'running'
  const isDone = stage.status === 'done'
  const isFailed = stage.status === 'failed'
  const showProgress = isRunning || (stage.progress > 0 && stage.progress < 100 && !isFailed) || isDone
  const output = stage.output
  const outputText = output
    ? output.total
      ? `产出 ${output.count ?? 0}/${output.total} ${output.label || ''}`.trim()
      : `产出 ${output.count ?? 0} ${output.label || ''}`.trim()
    : null

  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-gray-200">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3">
          <div className="text-lg">
            {isDone ? (
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
            ) : isFailed ? (
              <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
            ) : isRunning ? (
              <ClockCircleOutlined spin style={{ color: '#1677ff' }} />
            ) : (
              <ClockCircleOutlined style={{ color: '#d9d9d9' }} />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm">{index + 1}. {stage.title}</span>
              <Tag color={meta.color}>{meta.text}</Tag>
              {outputText && <span className="text-xs text-gray-500">{outputText}</span>}
              {output?.extra && <span className="text-xs text-orange-500">{output.extra}</span>}
              {output?.url && (
                <a href={output.url} target="_blank" rel="noreferrer" className="text-xs text-blue-500">
                  查看成片
                </a>
              )}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">{stage.desc}</div>
            {stage.error && isFailed && (
              <div className="text-xs text-red-500 mt-0.5 truncate" title={stage.error}>
                {stage.error}
              </div>
            )}
            {showProgress && (
              <Progress
                percent={Math.max(0, Math.min(100, Math.round(stage.progress)))}
                size="small"
                status={isFailed ? 'exception' : isDone ? 'success' : 'active'}
                className="mt-2"
               style={{ maxWidth: 320 }}
             />
           )}
            {stage.agentInfo && (stage.agentInfo.output || stage.agentInfo.toolCalls.length > 0) && (
              <div className="mt-1 p-2 bg-gray-50 rounded text-xs space-y-1">
                {stage.agentInfo.toolCalls.length > 0 && (
                  <div className="flex items-center gap-1 flex-wrap">
                    <span className="text-gray-400">工具:</span>
                    {stage.agentInfo.toolCalls.map((tc, i) => (
                      <Tooltip key={i} title={tc.args ? JSON.stringify(tc.args) : undefined}>
                        <Tag className="m-0" style={{ fontSize: 11 }}>{tc.tool}</Tag>
                      </Tooltip>
                    ))}
                  </div>
                )}
                {stage.agentInfo.output && (
                  <div className="text-gray-500">{stage.agentInfo.output}</div>
                )}
              </div>
            )}
         </div>
        </div>
      </div>
      <div className="flex items-center gap-2 ml-2">
        {externalLink}
        {isFailed ? (
          <Button
            size="small"
            icon={<ReloadOutlined />}
            disabled={busy}
            onClick={() => onRun(stage.key)}
          >
            重试
          </Button>
        ) : !isDone && !isRunning ? (
          <Button
            size="small"
            type="primary"
            icon={<PlayCircleOutlined />}
            disabled={busy || !canRun}
            onClick={() => onRun(stage.key)}
          >
            {stage.actionLabel || '执行'}
          </Button>
        ) : null}
      </div>
    </div>
  )
}
