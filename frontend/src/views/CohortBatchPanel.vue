<template>
  <section class="batch-panel" data-testid="cohort-batch-panel">
    <h3>成员样本批量重算</h3>
    <p class="panel-desc">
      一次多选分群提交，按同一观察窗生成分群批次快照；名单同时受观察日和当时的分群条件约束。
    </p>

    <form class="analysis-form" @submit.prevent="submitBatch">
      <label>
        <span>观察日</span>
        <input v-model="observationDate" data-testid="batch-observation-date" type="date" />
      </label>
      <label>
        <span>演练中断（可选）</span>
        <select v-model="interruptId" data-testid="batch-interrupt">
          <option :value="0">不中断</option>
          <option v-for="id in selectedIds" :key="id" :value="id">
            让 {{ cohortName(id) }} 算到一半中断
          </option>
        </select>
      </label>
      <button class="btn primary" data-testid="batch-submit" type="submit" :disabled="submitting || !selectedIds.length">
        {{ submitting ? '提交中…' : `批量重算（已选 ${selectedIds.length} 条）` }}
      </button>
    </form>

    <div class="cohort-check-list">
      <label v-for="row in rows" :key="String(row.id)" class="cohort-check">
        <input v-model="selectedIds" type="checkbox" :value="Number(row.id)" :data-testid="`batch-check-${row.id}`" />
        <span>{{ row['分群名称'] }}</span>
        <span class="muted">（{{ row['分群条件'] }}）</span>
      </label>
      <p v-if="!rows.length" class="muted">暂无分群可提交</p>
    </div>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
    <p v-if="notice" class="notice-text" data-testid="batch-notice">{{ notice }}</p>

    <article v-for="batch in batches" :key="batch.batch_id" class="batch-card" :data-testid="`batch-${batch.batch_id}`">
      <header class="batch-head">
        <strong>{{ batch.batch_id }}</strong>
        <span>观察日 {{ batch.观察日 }}</span>
        <span class="batch-status" :data-status="batch.status">{{ batch.status }}</span>
        <button
          v-if="batch.status !== '全部完成'"
          class="btn"
          type="button"
          :data-testid="`batch-rerun-${batch.batch_id}`"
          @click="rerun(batch.batch_id)"
        >
          补跑未完成项
        </button>
      </header>

      <table class="data-table">
        <thead>
          <tr>
            <th>分群</th>
            <th>当时分群条件</th>
            <th>名单状态</th>
            <th>人数</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in batch.items" :key="item.cohort_id">
            <td>{{ item.分群名称 }}</td>
            <td>{{ item.分群条件 }}</td>
            <td>
              <span class="item-status" :data-status="item.status">{{ item.status }}</span>
              <span v-if="item.失败原因" class="muted">（{{ item.失败原因 }}）</span>
            </td>
            <td>{{ item.status === '已确认' ? item.member_count : '—' }}</td>
            <td>
              <button
                v-if="item.status === '已确认'"
                class="link"
                type="button"
                :data-testid="`batch-members-${batch.batch_id}-${item.cohort_id}`"
                @click="toggleMembers(batch.batch_id, item.cohort_id)"
              >
                核对名单
              </button>
              <span v-else class="muted">需补跑后核对</span>
            </td>
          </tr>
        </tbody>
      </table>

      <p class="usability-line">
        当前可用：{{ usabilityText(batch) }}
      </p>

      <div v-if="membersOf(batch.batch_id)" class="members-box">
        <template v-if="membersOf(batch.batch_id)?.members?.length">
          <p class="muted">
            {{ membersOf(batch.batch_id)?.分群名称 }} · 观察日 {{ membersOf(batch.batch_id)?.观察日 }} ·
            条件 {{ membersOf(batch.batch_id)?.分群条件 }} · 共 {{ membersOf(batch.batch_id)?.member_count }} 人
          </p>
          <table class="data-table">
            <thead>
              <tr><th>用户ID</th><th>姓名</th><th>观察日</th><th>当时条件</th></tr>
            </thead>
            <tbody>
              <tr v-for="m in membersOf(batch.batch_id)?.members" :key="m.user_id">
                <td>{{ m.user_id }}</td>
                <td>{{ m.name }}</td>
                <td>{{ m.observation_date }}</td>
                <td>{{ m.condition }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <p v-else class="error-text">{{ membersOf(batch.batch_id)?.error }}</p>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  batchRecomputeCohorts,
  getBatchCohortMembers,
  getCohortBatch,
  listCohortBatches,
  rerunCohortBatch,
} from '@/api/backend-service'
import type {
  BatchCohortMembers,
  CohortBatchSnapshot,
  EntryRow,
} from '@/data/types'

const props = defineProps<{ rows: EntryRow[] }>()
const emit = defineEmits<{ refresh: [] }>()

const selectedIds = ref<number[]>([])
const observationDate = ref(new Date().toISOString().slice(0, 10))
const interruptId = ref(0)
const submitting = ref(false)
const errorMessage = ref('')
const notice = ref('')
const batches = ref<CohortBatchSnapshot[]>([])
const membersMap = ref<Record<string, BatchCohortMembers>>({})

function cohortName(id: number): string {
  const row = props.rows.find((r) => Number(r.id) === id)
  return String(row?.['分群名称'] ?? id)
}

function membersOf(batchId: string): BatchCohortMembers | undefined {
  return membersMap.value[batchId]
}

function usabilityText(batch: CohortBatchSnapshot): string {
  const usable = batch.usability.usable_cohorts.map((u) => u.分群名称)
  const waiting = batch.usability.waiting_cohorts.map((w) => `${w.分群名称}（${w.status}）`)
  const parts: string[] = []
  parts.push(usable.length ? `${usable.join('、')} 名单可独立核对` : '暂无可用名单')
  if (waiting.length) parts.push(`等待 ${waiting.join('、')}`)
  if (batch.usability.usable_compare_pairs.length) {
    parts.push(
      `可对比组合：${batch.usability.usable_compare_pairs
        .map((p) => `${p.分群A}×${p.分群B}`)
        .join('、')}`,
    )
  }
  return parts.join('；')
}

async function refreshBatches() {
  const summaries = await listCohortBatches()
  const details = await Promise.all(summaries.items.map((s) => getCohortBatch(s.batch_id)))
  batches.value = details.filter((d) => !d.error)
}

async function submitBatch() {
  if (!selectedIds.value.length) return
  submitting.value = true
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await batchRecomputeCohorts(
      [...selectedIds.value],
      observationDate.value,
      interruptId.value || undefined,
    )
    if (result.error) throw new Error(result.error)
    notice.value = result.message ?? `批次 ${result.batch_id} 已生成`
    interruptId.value = 0
    await refreshBatches()
    emit('refresh')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量重算失败'
  } finally {
    submitting.value = false
  }
}

async function rerun(batchId: string) {
  errorMessage.value = ''
  notice.value = ''
  try {
    const result = await rerunCohortBatch(batchId)
    if (result.error) throw new Error(result.error)
    notice.value = result.message ?? `批次 ${batchId} 补跑完成`
    await refreshBatches()
    emit('refresh')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补跑失败'
  }
}

async function toggleMembers(batchId: string, cohortId: number) {
  const key = batchId
  if (membersMap.value[key]) {
    const rest = { ...membersMap.value }
    delete rest[key]
    membersMap.value = rest
    return
  }
  const detail = await getBatchCohortMembers(batchId, cohortId)
  membersMap.value = { ...membersMap.value, [key]: detail }
}

onMounted(() => {
  void refreshBatches().catch(() => {})
})
</script>
