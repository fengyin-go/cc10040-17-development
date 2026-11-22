<template>
  <section class="batch-panel" data-testid="compare-batch-panel">
    <h3>按批次快照执行对比</h3>
    <p class="panel-desc">
      按分群批次快照查找同一观察窗已确认的名单；任一名单未就绪时，会标明当前可用的数据与等待对象。
    </p>

    <form class="analysis-form" @submit.prevent="execute">
      <label>
        <span>对比任务</span>
        <select v-model="taskId" data-testid="compare-task">
          <option :value="0">请选择</option>
          <option v-for="row in rows" :key="String(row.id)" :value="Number(row.id)">
            {{ row['对比名称'] }}（{{ row['分群A'] }} × {{ row['分群B'] }}）
          </option>
        </select>
      </label>
      <label>
        <span>分群批次快照</span>
        <select v-model="batchId" data-testid="compare-batch">
          <option value="">请选择</option>
          <option v-for="b in batches" :key="b.batch_id" :value="b.batch_id">
            {{ b.batch_id }} · 观察日 {{ b.观察日 }} · {{ b.status }}（{{ b.confirmed_count }}/{{ b.item_count }}）
          </option>
        </select>
      </label>
      <button class="btn primary" data-testid="compare-execute" type="submit" :disabled="running || !taskId || !batchId">
        {{ running ? '执行中…' : '执行对比' }}
      </button>
    </form>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <article v-if="result" class="batch-card" data-testid="compare-result">
      <header class="batch-head">
        <strong>{{ result.task_name }}</strong>
        <span>批次 {{ result.batch_id }} · 观察日 {{ result.观察日 }}</span>
      </header>

      <template v-if="result.status === '等待名单'">
        <p class="notice-text">{{ result.message }}</p>
        <p class="usability-line">
          当前可用：{{ (result.usable_now ?? []).map((u) => `${u.分群名称}（${u.member_count} 人，可独立核对）`).join('、') || '无' }}
        </p>
        <p class="usability-line">
          等待中：{{ (result.waiting_for ?? []).map((w) => `${w.分群名称}（${w.status}，${w.提示}）`).join('、') }}
        </p>
      </template>

      <template v-else-if="result.cohort_a && result.cohort_b">
        <div class="compare-grid">
          <div class="compare-side">
            <h4>{{ result.cohort_a.分群名称 }}</h4>
            <p class="muted">当时条件：{{ result.cohort_a.分群条件 }}</p>
            <p>名单人数：{{ result.cohort_a.member_count }}</p>
            <p class="muted">样本：{{ sampleText(result.cohort_a.sample_members) }}</p>
          </div>
          <div class="compare-side">
            <h4>{{ result.cohort_b.分群名称 }}</h4>
            <p class="muted">当时条件：{{ result.cohort_b.分群条件 }}</p>
            <p>名单人数：{{ result.cohort_b.member_count }}</p>
            <p class="muted">样本：{{ sampleText(result.cohort_b.sample_members) }}</p>
          </div>
        </div>
        <p class="usability-line" data-testid="compare-diff">
          按名单复核：人数差 {{ result.headcount_diff }} 人 · 交集 {{ result.overlap_count }} 人 ·
          差值 {{ result.diff_percentage }}%
        </p>
      </template>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { executeCompareByBatch, listCohortBatches } from '@/api/backend-service'
import type {
  CohortBatchSummary,
  CohortMember,
  CompareByBatchResult,
  EntryRow,
} from '@/data/types'

defineProps<{ rows: EntryRow[] }>()
const emit = defineEmits<{ refresh: [] }>()

const taskId = ref(0)
const batchId = ref('')
const running = ref(false)
const errorMessage = ref('')
const batches = ref<CohortBatchSummary[]>([])
const result = ref<CompareByBatchResult | null>(null)

function sampleText(members: CohortMember[]): string {
  return members.map((m) => `${m.name}(${m.user_id})`).join('、')
}

async function execute() {
  if (!taskId.value || !batchId.value) return
  running.value = true
  errorMessage.value = ''
  result.value = null
  try {
    const payload = await executeCompareByBatch(taskId.value, batchId.value)
    if (payload.error) throw new Error(payload.error)
    result.value = payload
    emit('refresh')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '对比执行失败'
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  try {
    const payload = await listCohortBatches()
    batches.value = payload.items
  } catch {
    batches.value = []
  }
})
</script>
