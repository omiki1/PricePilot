<script setup>
// 左侧会话栏（omiki 2026-09-29）：新建对话 / 按今天·昨天·7 天内·更早分组 / 行内重命名 / 删除确认。
// 只负责展示和收集操作，真正的请求在 App.vue 里发（那里还要同步当前线程和 localStorage）。
import { computed, nextTick, ref } from 'vue'
import { ERRORS, SIDEBAR } from './ui_copy.js'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },      // 正在回答时不允许切会话
  open: { type: Boolean, default: true },
})
const emit = defineEmits(['new', 'select', 'rename', 'remove', 'retry', 'close'])

const menuFor = ref('')
const editingId = ref('')
const draft = ref('')
const renameError = ref('')
const confirming = ref(null)
const editInput = ref(null)

const DAY = 24 * 60 * 60 * 1000

function groupKey(value, todayStart) {
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return 'earlier'
  const dayStart = new Date(time)
  dayStart.setHours(0, 0, 0, 0)
  const diff = Math.round((todayStart - dayStart.getTime()) / DAY)
  if (diff <= 0) return 'today'
  if (diff === 1) return 'yesterday'
  if (diff < 7) return 'week'
  return 'earlier'
}

const groups = computed(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const buckets = { today: [], yesterday: [], week: [], earlier: [] }
  for (const session of props.sessions) {
    buckets[groupKey(session.updated_at, today.getTime())].push(session)
  }
  return Object.entries(buckets)
    .filter(([, items]) => items.length)
    .map(([key, items]) => ({ key, label: SIDEBAR.groups[key], items }))
})

function titleOf(session) {
  return session.title || SIDEBAR.untitled
}

function toggleMenu(id) {
  menuFor.value = menuFor.value === id ? '' : id
}

async function startRename(session) {
  menuFor.value = ''
  editingId.value = session.session_id
  draft.value = session.title || ''
  renameError.value = ''
  await nextTick()
  const input = Array.isArray(editInput.value) ? editInput.value[0] : editInput.value
  input?.focus()
  input?.select()
}

function commitRename(session) {
  if (editingId.value !== session.session_id) return
  const title = draft.value.replace(/\s+/g, ' ').trim()
  if (!title) {
    renameError.value = SIDEBAR.renameEmpty
    return
  }
  editingId.value = ''
  renameError.value = ''
  if (title !== (session.title || '')) emit('rename', { id: session.session_id, title })
}

function cancelRename() {
  editingId.value = ''
  renameError.value = ''
}

function askDelete(session) {
  menuFor.value = ''
  confirming.value = session
}

function confirmDelete() {
  const target = confirming.value
  confirming.value = null
  if (target) emit('remove', target.session_id)
}

function select(session) {
  if (props.busy || editingId.value === session.session_id) return
  menuFor.value = ''
  emit('select', session.session_id)
}
</script>

<template>
  <!-- 窄屏时是浮层，点遮罩收起 -->
  <div v-if="open" class="session-backdrop" @click="emit('close')"></div>

  <aside class="session-side" :class="{ 'is-open': open }" @click.self="menuFor = ''">
    <div class="session-head">
      <button class="session-new" type="button" :disabled="busy" @click="emit('new')">
        <span class="session-new-plus">＋</span>{{ SIDEBAR.newChat }}
      </button>
      <button class="session-collapse" type="button" :title="SIDEBAR.collapse" @click="emit('close')">
        ‹
      </button>
    </div>

    <div class="session-list" @scroll="menuFor = ''">
      <p v-if="loading && !sessions.length" class="session-hint">{{ SIDEBAR.loading }}</p>

      <p v-else-if="error && !sessions.length" class="session-hint session-hint-error">
        {{ ERRORS.listFailed }} ·
        <button class="session-retry" type="button" @click="emit('retry')">{{ ERRORS.retry }}</button>
      </p>

      <p v-else-if="!sessions.length" class="session-hint">{{ SIDEBAR.empty }}</p>

      <section v-for="group in groups" :key="group.key" class="session-group">
        <h5 class="session-group-title">{{ group.label }}</h5>

        <div
          v-for="session in group.items"
          :key="session.session_id"
          class="session-item"
          :class="{
            active: session.session_id === activeId,
            editing: editingId === session.session_id,
            disabled: busy && session.session_id !== activeId,
          }"
          @click="select(session)"
        >
          <template v-if="editingId === session.session_id">
            <input
              ref="editInput"
              v-model="draft"
              class="session-rename"
              maxlength="64"
              :placeholder="SIDEBAR.renamePlaceholder"
              @click.stop
              @keydown.enter.prevent="commitRename(session)"
              @keydown.esc.prevent="cancelRename"
              @blur="commitRename(session)"
            />
            <span v-if="renameError" class="session-rename-error">{{ renameError }}</span>
          </template>

          <template v-else>
            <span class="session-title" :title="titleOf(session)">{{ titleOf(session) }}</span>
            <button
              class="session-more"
              type="button"
              :aria-label="SIDEBAR.rename + ' / ' + SIDEBAR.delete"
              @click.stop="toggleMenu(session.session_id)"
            >
              ⋯
            </button>
            <div v-if="menuFor === session.session_id" class="session-menu" @click.stop>
              <button type="button" @click="startRename(session)">{{ SIDEBAR.rename }}</button>
              <button type="button" class="danger" @click="askDelete(session)">{{ SIDEBAR.delete }}</button>
            </div>
          </template>
        </div>
      </section>

      <p v-if="error && sessions.length" class="session-hint session-hint-error">
        {{ ERRORS.listFailed }} ·
        <button class="session-retry" type="button" @click="emit('retry')">{{ ERRORS.retry }}</button>
      </p>
    </div>
  </aside>

  <!-- 删除确认 -->
  <div v-if="confirming" class="modal-mask" @click.self="confirming = null">
    <div class="modal" role="dialog" aria-modal="true">
      <h3>{{ SIDEBAR.deleteTitle }}</h3>
      <p>{{ SIDEBAR.deleteBody }}</p>
      <div class="modal-actions">
        <button type="button" class="modal-cancel" @click="confirming = null">{{ SIDEBAR.cancel }}</button>
        <button type="button" class="modal-danger" @click="confirmDelete">{{ SIDEBAR.confirmDelete }}</button>
      </div>
    </div>
  </div>
</template>
