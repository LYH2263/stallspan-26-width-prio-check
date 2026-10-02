<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, ApiError } from '../api'

const rows = ref<any[]>([])
const load = async () => { rows.value = await api('/vendors') }
onMounted(load)

function errText(e: unknown, fallbackField: string): string {
  // 接口点名字段与本页提示同一叫法（摊宽 / 优先级 / 街宽）
  if (e instanceof ApiError) {
    const label = e.fieldLabel || fallbackField
    return `【${label}】${e.message}`
  }
  return e instanceof Error ? e.message : String(e)
}

// ---- 新建摊主 ----
const creating = ref(false)
const form = ref({ name: '', stall_width_m: '', priority: '1' })
const formError = ref('')

function parseWidth(raw: string): number | null {
  const s = raw.trim()
  if (!s) return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

function parsePriority(raw: string): number | null {
  const s = raw.trim()
  if (!/^-?\d+$/.test(s)) return null  // 2.5 / 3.0 / 空 都不算整数
  const n = Number(s)
  return Number.isSafeInteger(n) ? n : null
}

async function createVendor() {
  formError.value = ''
  const width = parseWidth(form.value.stall_width_m)
  const priority = parsePriority(form.value.priority)
  if (!form.value.name.trim()) { formError.value = '【名称】摊主名不能为空'; return }
  if (width === null || width <= 0) { formError.value = '【摊宽】摊宽须为大于 0 的数（米）'; return }
  if (priority === null || priority < 1 || priority > 9) {
    formError.value = '【优先级】优先级须为 1 到 9 的整数'; return
  }
  try {
    const row = await api('/vendors', {
      method: 'POST',
      body: JSON.stringify({
        name: form.value.name.trim(), stall_width_m: width, priority,
      }),
    })
    rows.value.push(row)
    rows.value.sort((a, b) => a.priority - b.priority || a.id - b.id)
    form.value = { name: '', stall_width_m: '', priority: '1' }
    creating.value = false
  } catch (e) {
    // 被拒：列表停在改前，不新增半成品行；输入保留便于修改
    formError.value = errText(e, '摊宽')
  }
}

// ---- 行内改写 ----
const editingId = ref<number | null>(null)
const draft = ref({ name: '', stall_width_m: '', priority: '' })
const snapshot = ref({ name: '', stall_width_m: '', priority: '' })
const editError = ref('')

function startEdit(r: any) {
  editingId.value = r.id
  editError.value = ''
  const s = { name: r.name, stall_width_m: String(r.stall_width_m), priority: String(r.priority) }
  snapshot.value = { ...s }
  draft.value = { ...s }
}

function cancelEdit() {
  editingId.value = null
  editError.value = ''
}

async function saveEdit(r: any) {
  editError.value = ''
  const width = parseWidth(draft.value.stall_width_m)
  const priority = parsePriority(draft.value.priority)
  if (!draft.value.name.trim()) { editError.value = '【名称】摊主名不能为空'; return }
  if (width === null || width <= 0) { editError.value = '【摊宽】摊宽须为大于 0 的数（米）'; return }
  if (priority === null || priority < 1 || priority > 9) {
    editError.value = '【优先级】优先级须为 1 到 9 的整数'; return
  }
  try {
    // 提交瞬间由后端按新 摊宽×优先级 交叉重检，不吃改前优先缓存
    const updated = await api(`/vendors/${r.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        name: draft.value.name.trim(), stall_width_m: width, priority,
      }),
    })
    Object.assign(r, updated)
    rows.value.sort((a, b) => a.priority - b.priority || a.id - b.id)
    editingId.value = null
  } catch (e) {
    editError.value = errText(e, '摊宽')
    // 被拒时页面停在改前：输入框回滚到改前值，表格行从未变更
    draft.value = { ...snapshot.value }
  }
}
</script>
<template>
  <h1>摊主队列</h1>
  <p class="sub">底部排队条 · 宽度与优先级</p>
  <p class="sub" style="margin-top:-0.4rem">
    交叉规则：优先级 1 到 3 摊宽不得超过 4 m；4 到 6 不得超过 6 m；7 到 9 不得超过 8 m
  </p>
  <div class="ss-vendor-queue" style="border-top:none; background:transparent; margin:0; padding:0.5rem 0 1rem">
    <div v-for="r in rows" :key="r.id ?? JSON.stringify(r)" class="ss-vendor-chip">
      <strong>{{ r.name }}</strong>
      <span>需 {{ r.stall_width_m }} m · 优先 {{ r.priority }}</span>
    </div>
  </div>

  <p v-if="formError" class="ss-reject">{{ formError }}</p>
  <p v-if="editError" class="ss-reject">{{ editError }}</p>

  <div class="card">
    <button class="btn" style="margin-bottom:0.6rem" @click="creating = !creating">
      {{ creating ? '收起新建' : '新建摊主' }}
    </button>
    <table v-if="creating" style="margin-bottom:0.6rem">
      <tbody>
        <tr>
          <td><input v-model="form.name" placeholder="摊主名" /></td>
          <td><input v-model="form.stall_width_m" type="number" min="0" step="0.1" placeholder="摊宽(m)" style="width:7rem" /></td>
          <td><input v-model="form.priority" type="number" min="1" max="9" step="1" placeholder="优先级" style="width:5.5rem" /></td>
          <td><button class="btn" @click="createVendor">保存新建</button></td>
        </tr>
      </tbody>
    </table>
    <table>
      <thead><tr><th>摊主</th><th>摊宽(m)</th><th>优先级</th><th>操作</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)">
          <template v-if="editingId === r.id">
            <td><input v-model="draft.name" placeholder="摊主名" /></td>
            <td><input v-model="draft.stall_width_m" type="number" min="0" step="0.1" style="width:7rem" /></td>
            <td><input v-model="draft.priority" type="number" min="1" max="9" step="1" style="width:5.5rem" /></td>
            <td>
              <button class="btn" @click="saveEdit(r)">保存</button>
              <button class="btn" style="margin-left:0.3rem" @click="cancelEdit">取消</button>
            </td>
          </template>
          <template v-else>
            <td>{{ r.name }}</td><td>{{ r.stall_width_m }}</td><td>{{ r.priority }}</td>
            <td><button class="btn" @click="startEdit(r)">改</button></td>
          </template>
        </tr>
      </tbody>
    </table>
  </div>
</template>
