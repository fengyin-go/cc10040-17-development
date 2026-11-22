import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  BatchCohortMembers,
  CohortBatchSnapshot,
  CohortBatchSummary,
  CompareByBatchResult,
  EntryRow,
  OverviewResult,
  PageResult,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

/* ── 成员样本批量重算 / 分群批次快照 ── */

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  return (await response.json()) as T
}

export async function batchRecomputeCohorts(
  cohortIds: number[],
  observationDate?: string,
  interruptCohortId?: number,
): Promise<CohortBatchSnapshot> {
  return await postJson<CohortBatchSnapshot>('/api/cross/user-cohort/batch-recompute', {
    cohort_ids: cohortIds,
    observation_date: observationDate || undefined,
    interrupt_cohort_id: interruptCohortId,
  })
}

export async function listCohortBatches(): Promise<{ items: CohortBatchSummary[] }> {
  const response = await request('/api/cross/user-cohort/batches')
  return await response.json()
}

export async function getCohortBatch(batchId: string): Promise<CohortBatchSnapshot> {
  const response = await request(`/api/cross/user-cohort/batches/${batchId}`)
  return await response.json()
}

export async function rerunCohortBatch(batchId: string): Promise<CohortBatchSnapshot> {
  return await postJson<CohortBatchSnapshot>(`/api/cross/user-cohort/batches/${batchId}/rerun`, {})
}

export async function getBatchCohortMembers(
  batchId: string,
  cohortId: number,
): Promise<BatchCohortMembers> {
  const response = await request(`/api/cross/user-cohort/batches/${batchId}/cohorts/${cohortId}`)
  return await response.json()
}

export async function executeCompareByBatch(
  taskId: number,
  batchId: string,
): Promise<CompareByBatchResult> {
  return await postJson<CompareByBatchResult>(
    `/api/cross/segment-compare/${taskId}/execute-by-batch`,
    { batch_id: batchId },
  )
}
