<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, FIELD_LABELS, api } from '../api'

const rows = ref<any[]>([])
const days = ref<any[]>([])
const saving = ref<number | 'new' | null>(null)
// 错误按行/表单记录：{ target, field?, message }；field 与后端 rules.py 同 key
const error = ref<{ target: number | 'new'; field?: string; message: string } | null>(null)
const editing = ref<Record<number, { name: string; stall_width_m: string; priority: string }>>({})
const draftNew = ref({ market_day_id: 0, name: '', stall_width_m: '', priority: '1' })

async function load() {
  rows.value = await api('/vendors')
  days.value = await api('/days')
  if (!draftNew.value.market_day_id && days.value[0]) draftNew.value.market_day_id = days.value[0].id
}
onMounted(load)

function startEdit(r: any) {
  error.value = null
  editing.value[r.id] = { name: r.name, stall_width_m: String(r.stall_width_m), priority: String(r.priority) }
}
function cancelEdit(id: number) {
  delete editing.value[id]
  error.value = null
}

function errMsg(e: unknown): { field?: string; message: string } {
  if (e instanceof ApiError) {
    const label = e.field ? (FIELD_LABELS[e.field] ?? e.field) : ''
    return { field: e.field, message: (label ? label + '：' : '') + e.message }
  }
  return { message: e instanceof Error ? e.message : String(e) }
}

async function saveEdit(r: any) {
  const d = editing.value[r.id]
  if (!d) return
  saving.value = r.id
  error.value = null
  try {
    const body = {
      market_day_id: r.market_day_id,
      name: d.name,
      stall_width_m: Number(d.stall_width_m),
      priority: Number(d.priority),
    }
    // 整笔 PUT：成功才换本地行；失败服务端已回滚，下面把输入也拉回改前
    const updated = await api(`/vendors/${r.id}`, { method: 'PUT', body: JSON.stringify(body) })
    const i = rows.value.findIndex(x => x.id === r.id)
    if (i >= 0) rows.value[i] = updated
    delete editing.value[r.id]
  } catch (e) {
    error.value = { target: r.id, ...errMsg(e) }
    // 页面停在改前：输入框回滚到改前值，表格行本来就没动过
    editing.value[r.id] = { name: r.name, stall_width_m: String(r.stall_width_m), priority: String(r.priority) }
  } finally {
    saving.value = null
  }
}

async function createVendor() {
  saving.value = 'new'
  error.value = null
  try {
    const body = {
      market_day_id: draftNew.value.market_day_id,
      name: draftNew.value.name,
      stall_width_m: Number(draftNew.value.stall_width_m),
      priority: Number(draftNew.value.priority),
    }
    await api('/vendors', { method: 'POST', body: JSON.stringify(body) })
    draftNew.value.name = ''
    draftNew.value.stall_width_m = ''
    draftNew.value.priority = '1'
    await load()
  } catch (e) {
    error.value = { target: 'new', ...errMsg(e) }
  } finally {
    saving.value = null
  }
}
</script>
<template>
  <h1>摊主队列</h1>
  <p class="sub">底部排队条 · 宽度与优先级（优先1-3摊宽≤4；4-6≤6；7-9≤8）</p>

  <div v-if="error" class="card ss-rule-error" :data-field="error.field">
    <strong>保存被拒</strong>（{{ error.field ? FIELD_LABELS[error.field] || error.field : '表单' }}）：{{ error.message }}
  </div>

  <div class="ss-vendor-queue" style="border-top:none; background:transparent; margin:0; padding:0.5rem 0 1rem">
    <div v-for="r in rows" :key="r.id ?? JSON.stringify(r)" class="ss-vendor-chip">
      <strong>{{ r.name }}</strong>
      <span>需 {{ r.stall_width_m }} m · 优先 {{ r.priority }}</span>
    </div>
  </div>

  <div class="card">
    <table>
      <thead><tr><th>摊主</th><th>摊宽(stall_width_m)</th><th>优先级(priority)</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>
            <template v-if="editing[r.id]">
              <input v-model="editing[r.id].name" />
            </template>
            <template v-else>{{ r.name }}</template>
          </td>
          <td>
            <template v-if="editing[r.id]">
              <input
                v-model="editing[r.id].stall_width_m"
                :class="{ 'ss-input-bad': error?.target === r.id && error?.field === 'stall_width_m' }"
              />
            </template>
            <template v-else>{{ r.stall_width_m }}</template>
          </td>
          <td>
            <template v-if="editing[r.id]">
              <input
                v-model="editing[r.id].priority"
                :class="{ 'ss-input-bad': error?.target === r.id && error?.field === 'priority' }"
              />
            </template>
            <template v-else>{{ r.priority }}</template>
          </td>
          <td>
            <template v-if="editing[r.id]">
              <button class="btn" :disabled="saving === r.id" @click="saveEdit(r)">保存</button>
              <button class="btn ss-btn-ghost" :disabled="saving === r.id" @click="cancelEdit(r.id)">取消</button>
            </template>
            <button v-else class="btn ss-btn-ghost" @click="startEdit(r)">改写</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h3 style="margin:0 0 0.5rem">新增摊主</h3>
    <div class="ss-new-form">
      <label>集日
        <select v-model.number="draftNew.market_day_id">
          <option v-for="d in days" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <label>摊主<input v-model="draftNew.name" placeholder="姓名" /></label>
      <label>摊宽(stall_width_m)
        <input
          v-model="draftNew.stall_width_m"
          placeholder="如 4"
          :class="{ 'ss-input-bad': error?.target === 'new' && error?.field === 'stall_width_m' }"
        />
      </label>
      <label>优先级(priority)
        <input
          v-model="draftNew.priority"
          placeholder="1-9"
          :class="{ 'ss-input-bad': error?.target === 'new' && error?.field === 'priority' }"
        />
      </label>
      <button class="btn" :disabled="saving === 'new'" @click="createVendor">新增</button>
    </div>
  </div>
</template>

<style scoped>
.ss-new-form { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: flex-end; }
.ss-new-form label { display: flex; flex-direction: column; font-size: 0.75rem; color: var(--ss-muted); }
input, select { padding: 0.35rem 0.45rem; border: 1px solid var(--ss-curb); border-radius: 3px; font: inherit; width: 9rem; }
.ss-btn-ghost { background: transparent; color: var(--ss-asphalt); border: 1px solid var(--ss-curb); box-shadow: none; margin-left: 0.35rem; }
.ss-input-bad { border-color: var(--ss-bad); background: rgba(163,58,44,0.1); }
.ss-rule-error { border-color: var(--ss-bad); color: var(--ss-bad); }
</style>
