/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** 成员样本批量重算：分群批次快照相关类型 */
export type CohortMember = {
  user_id: string
  name: string
  cohort: string
  condition: string
  observation_date: string
  join_time: string
}

export type CohortBatchItem = {
  cohort_id: number
  分群名称: string
  分群条件: string
  观察日: string
  status: string
  member_count: number
  确认时间: string | null
  失败原因: string | null
  sample_members: CohortMember[]
}

export type CohortBatchUsability = {
  usable_cohorts: { cohort_id: number; 分群名称: string; member_count: number }[]
  waiting_cohorts: { cohort_id: number; 分群名称: string; status: string; 失败原因: string | null }[]
  usable_compare_pairs: { 分群A: string; 分群B: string }[]
}

export type CohortBatchSnapshot = {
  batch_id: string
  观察日: string
  创建时间?: string
  status: string
  items: CohortBatchItem[]
  usability: CohortBatchUsability
  message?: string
  error?: string
}

export type CohortBatchSummary = {
  batch_id: string
  观察日: string
  创建时间: string
  status: string
  item_count: number
  confirmed_count: number
}

export type BatchCohortMembers = {
  batch_id: string
  观察日?: string
  cohort_id: number
  分群名称?: string
  分群条件?: string
  status: string
  member_count?: number
  members?: CohortMember[]
  失败原因?: string | null
  error?: string
}

export type CompareByBatchResult = {
  task_name?: string
  batch_id?: string
  观察日?: string
  status?: string
  usable_now?: { cohort_id: number; 分群名称: string; member_count: number; 提示: string }[]
  waiting_for?: { cohort_id: number; 分群名称: string; status: string; 失败原因: string | null; 提示: string }[]
  cohort_a?: { cohort_id: number; 分群名称: string; 分群条件: string; member_count: number; sample_members: CohortMember[] }
  cohort_b?: { cohort_id: number; 分群名称: string; 分群条件: string; member_count: number; sample_members: CohortMember[] }
  headcount_diff?: number
  overlap_count?: number
  diff_percentage?: number
  message?: string
  error?: string
}
