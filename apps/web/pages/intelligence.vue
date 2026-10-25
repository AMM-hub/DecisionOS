<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import type {
  AiChatResponse,
  AiConversationDetail,
  AiConversationSummary,
  AiMessage,
  AiModelMapping,
  AiToolCall,
} from '~/shared/types'
import { ApiError, useApi } from '~/composables/api'
import { t, useLocale } from '~/composables/locale'
import { formatDateTime, formatRelative, num } from '~/composables/format'
import { parseMarkdown } from '~/composables/markdown'
import type { MarkdownBlock } from '~/composables/markdown'
import PageHeader from '~/components/PageHeader.vue'
import DcCard from '~/components/DcCard.vue'

interface ChatMessage extends AiMessage {
  latency_ms?: number
  provider_id?: string
  model_id?: string
  warning?: { ungrounded_numbers: string[] }
  ungrounded_numbers?: string[]
}

const { get, post, call } = useApi()
const { locale } = useLocale()

const conversations = ref<AiConversationSummary[]>([])
const models = ref<AiModelMapping | null>(null)
const messages = ref<ChatMessage[]>([])
const activeConversationId = ref<string | null>(null)
const composer = ref('')

const loadingConversations = ref(false)
const loadingModels = ref(false)
const loadingConversation = ref(false)
const sending = ref(false)
const error = ref<{ code?: string; detail: string } | null>(null)
const copied = ref(false)

const composerEl = ref<HTMLTextAreaElement | null>(null)
const streamScroll = ref<HTMLElement | null>(null)
const streamEnd = ref<HTMLElement | null>(null)

const suggestions = computed(() => [
  { id: 'status', text: t('intelligence.suggestionStatus', locale.value) },
  { id: 'datasets', text: t('intelligence.suggestionDatasets', locale.value) },
  { id: 'risk', text: t('intelligence.suggestionRisk', locale.value) },
])

const primaryModel = computed(() => {
  if (!models.value) return null
  return models.value.roles?.primary ?? models.value.primary ?? null
})
const modelMissing = computed(() => models.value !== null && !primaryModel.value)

function setError(e: unknown) {
  if (e instanceof ApiError) {
    const detail = typeof e.detail === 'string' ? e.detail : e.message
    error.value = { code: e.code, detail }
  } else if (e instanceof Error) {
    error.value = { detail: e.message }
  } else {
    error.value = { detail: String(e) }
  }
}

async function loadModels() {
  loadingModels.value = true
  try {
    models.value = await get<AiModelMapping>('/ai/models')
  } catch (e) {
    setError(e)
  } finally {
    loadingModels.value = false
  }
}

async function loadConversations() {
  loadingConversations.value = true
  try {
    conversations.value = await get<AiConversationSummary[]>('/ai/conversations?limit=100')
  } catch (e) {
    setError(e)
  } finally {
    loadingConversations.value = false
  }
}

onMounted(() => {
  void Promise.all([loadConversations(), loadModels()])
})

function scrollToBottom() {
  void nextTick(() => {
    const el = streamScroll.value
    if (el) {
      // Set scrollTop directly: scrollIntoView would also scroll the page shell.
      el.scrollTop = el.scrollHeight
    }
  })
}

function resizeComposer() {
  const el = composerEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight || 0, 200)}px`
}

function autoGrow(event: Event) {
  const el = event.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight || 0, 200)}px`
}

function useSuggestion(text: string) {
  composer.value = text
  void nextTick(() => {
    resizeComposer()
    composerEl.value?.focus()
  })
}

function startNew() {
  activeConversationId.value = null
  messages.value = []
  error.value = null
  composer.value = ''
  void nextTick(() => {
    resizeComposer()
    composerEl.value?.focus()
  })
}

async function openConversation(id: string) {
  if (sending.value || id === activeConversationId.value) return
  activeConversationId.value = id
  loadingConversation.value = true
  error.value = null
  messages.value = []
  try {
    const detail = await get<AiConversationDetail>(`/ai/conversations/${id}`)
    messages.value = detail.messages.map(message => ({
      ...message,
      tool_trace: message.tool_trace ?? [],
    }))
  } catch (e) {
    setError(e)
    activeConversationId.value = null
  } finally {
    loadingConversation.value = false
  }
  if (messages.value.length) scrollToBottom()
}

async function removeConversation(conversation: AiConversationSummary) {
  if (!window.confirm(t('intelligence.deleteConfirm', locale.value))) return
  error.value = null
  try {
    await call<{ deleted: boolean; id: string }>(`/ai/conversations/${conversation.id}`, {
      method: 'DELETE',
    })
    if (activeConversationId.value === conversation.id) {
      activeConversationId.value = null
      messages.value = []
    }
    await loadConversations()
  } catch (e) {
    setError(e)
  }
}

async function send() {
  if (sending.value) return
  const text = composer.value.trim()
  if (!text) return

  const pendingId = `pending-${Date.now()}`
  const optimistic: ChatMessage = {
    id: pendingId,
    role: 'user',
    content: text,
    tool_trace: [],
    usage: {},
    created_at: new Date().toISOString(),
  }
  messages.value = [...messages.value, optimistic]
  composer.value = ''
  resizeComposer()
  sending.value = true
  error.value = null
  scrollToBottom()

  const body: { message: string; conversation_id?: string } = { message: text }
  if (activeConversationId.value) body.conversation_id = activeConversationId.value

  try {
    const response = await post<AiChatResponse>('/ai/chat', body)
    const assistant: ChatMessage = {
      id: response.message_id,
      role: 'assistant',
      content: response.answer,
      tool_trace: response.tool_calls ?? [],
      usage: response.usage,
      created_at: new Date().toISOString(),
      latency_ms: response.latency_ms,
      provider_id: response.provider_id,
      model_id: response.model_id,
      warning: response.warning,
      ungrounded_numbers: response.ungrounded_numbers,
    }
    messages.value = [...messages.value, assistant]
    activeConversationId.value = response.conversation_id
    await loadConversations()
    scrollToBottom()
  } catch (e) {
    messages.value = messages.value.filter(message => message.id !== pendingId)
    composer.value = text
    resizeComposer()
    setError(e)
  } finally {
    sending.value = false
  }
}

function blocks(content: string): MarkdownBlock[] {
  return parseMarkdown(content)
}

function messageRefs(message: ChatMessage): string[] {
  const refs = new Set<string>()
  for (const call of message.tool_trace ?? []) {
    if (call.evidence_ref) refs.add(call.evidence_ref)
  }
  return [...refs]
}

function warningFor(message: ChatMessage): string[] {
  const values = message.ungrounded_numbers ?? message.warning?.ungrounded_numbers ?? []
  return Array.isArray(values) ? values : []
}

function compactJson(input: Record<string, unknown> | null | undefined): string {
  try {
    return JSON.stringify(input ?? {})
  } catch {
    return '{}'
  }
}

function toolSummary(trace: AiToolCall[]): string {
  const calls = trace.length
  const refs = new Set(trace.map(call => call.evidence_ref).filter(Boolean)).size
  const callLabel = calls === 1
    ? t('intelligence.toolCallOne', locale.value)
    : t('intelligence.toolCallsMany', locale.value)
  const refLabel = refs === 1
    ? t('intelligence.evidenceRefOne', locale.value)
    : t('intelligence.evidenceRefsMany', locale.value)
  return `${calls} ${callLabel} · ${refs} ${refLabel}`
}

async function copyRef(reference: string) {
  try {
    await navigator.clipboard?.writeText(reference)
    copied.value = true
    window.setTimeout(() => {
      copied.value = false
    }, 1600)
  } catch {
    copied.value = false
  }
}
</script>

<template>
  <section>
    <PageHeader
      :title="t('intelligence.title', locale)"
      :subtitle="t('intelligence.subtitle', locale)"
    >
      <template #actions>
        <button class="btn-primary" type="button" @click="startNew">
          {{ t('intelligence.newConversation', locale) }}
        </button>
      </template>
    </PageHeader>

    <div v-if="error" class="banner error-banner-row" data-tone="warn" role="alert">
      <span class="badge err">{{ error.code ?? t('common.error', locale) }}</span>
      <span>{{ error.detail }}</span>
      <button class="btn-ghost btn-xs" type="button" @click="error = null">
        {{ t('common.close', locale) }}
      </button>
    </div>

    <div v-if="modelMissing && !loadingModels" class="banner model-banner" data-tone="warn">
      <svg aria-hidden="true"><use href="#i-alert" /></svg>
      <div class="cell-stack">
        <strong>{{ t('intelligence.noModel', locale) }}</strong>
        <span>{{ t('intelligence.noModelHelp', locale) }}</span>
      </div>
      <NuxtLink to="/settings/ai" class="btn btn-secondary btn-sm">
        {{ t('intelligence.openAiSettings', locale) }}
      </NuxtLink>
    </div>

    <div class="chat-shell">
      <aside class="panel conv-rail" :aria-label="t('intelligence.conversations', locale)">
        <div class="rail-head">
          <h2>{{ t('intelligence.conversations', locale) }}</h2>
          <span class="badge plain">{{ conversations.length }}</span>
        </div>

        <div v-if="loadingConversations" class="rail-skeleton" aria-hidden="true">
          <span></span><span></span><span></span>
        </div>

        <div v-else-if="!conversations.length" class="rail-empty">
          <p>{{ t('intelligence.noConversations', locale) }}</p>
          <p class="muted">{{ t('intelligence.noConversationsHelp', locale) }}</p>
        </div>

        <ul v-else class="conv-list">
          <li
            v-for="conversation in conversations"
            :key="conversation.id"
            class="conv-item"
            :class="{ active: conversation.id === activeConversationId }"
          >
            <button
              type="button"
              class="conv-main"
              :aria-current="conversation.id === activeConversationId ? 'true' : undefined"
              @click="openConversation(conversation.id)"
            >
              <span class="conv-title" dir="auto">{{ conversation.title }}</span>
              <span class="conv-meta">
                <span class="mono">
                  {{ conversation.message_count }} {{ t('intelligence.messageCount', locale) }}
                </span>
                <span>{{ formatRelative(conversation.updated_at, locale) }}</span>
              </span>
            </button>
            <button
              type="button"
              class="icon-btn conv-del"
              :aria-label="t('intelligence.deleteConversation', locale)"
              @click="removeConversation(conversation)"
            >
              <svg aria-hidden="true"><use href="#i-x" /></svg>
              <span class="sr-only">{{ t('common.delete', locale) }}</span>
            </button>
          </li>
        </ul>
      </aside>

      <DcCard class="stream">
        <div v-if="loadingConversation" class="stream-skeleton" aria-hidden="true">
          <span></span><span></span><span></span>
        </div>

        <div
          v-else
          ref="streamScroll"
          class="stream-scroll"
          aria-live="polite"
          :aria-busy="sending"
        >
          <div v-if="!messages.length" class="empty stream-empty">
            <div class="e-ico">
              <svg aria-hidden="true"><use href="#i-spark" /></svg>
            </div>
            <h3>{{ t('intelligence.emptyTitle', locale) }}</h3>
            <p class="muted">{{ t('intelligence.emptyBody', locale) }}</p>
            <div class="suggestions">
              <span class="sugg-label">{{ t('intelligence.suggestionsLabel', locale) }}</span>
              <button
                v-for="suggestion in suggestions"
                :key="suggestion.id"
                type="button"
                class="suggestion"
                @click="useSuggestion(suggestion.text)"
              >
                {{ suggestion.text }}
              </button>
            </div>
          </div>

          <article
            v-for="message in messages"
            :key="message.id"
            class="msg"
            :data-role="message.role"
          >
            <div class="msg-role">
              <span class="role-mark">
                {{ message.role === 'user' ? t('intelligence.you', locale) : t('intelligence.assistant', locale) }}
              </span>
              <span class="muted mono">{{ formatDateTime(message.created_at, locale) }}</span>
            </div>

            <template v-if="message.role === 'assistant'">
              <div class="msg-body">
                <template v-for="(block, index) in blocks(message.content)" :key="`blk-${message.id}-${index}`">
                  <pre v-if="block.type === 'code'" class="msg-code" dir="auto"><code>{{ block.text }}</code></pre>

                  <h4 v-else-if="block.type === 'heading'" class="msg-heading">
                    <template v-for="(span, spanIndex) in block.spans" :key="`h-${spanIndex}`">
                      <strong v-if="span.bold">{{ span.text }}</strong>
                      <code v-else-if="span.code">{{ span.text }}</code>
                      <template v-else>{{ span.text }}</template>
                    </template>
                  </h4>

                  <div v-else-if="block.type === 'table'" class="msg-table-wrap">
                    <table class="dt msg-table">
                      <thead>
                        <tr>
                          <th v-for="(cell, cellIndex) in block.head" :key="`th-${cellIndex}`">
                            <template v-for="(span, spanIndex) in cell" :key="`thc-${spanIndex}`">
                              <strong v-if="span.bold">{{ span.text }}</strong>
                              <code v-else-if="span.code">{{ span.text }}</code>
                              <template v-else>{{ span.text }}</template>
                            </template>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(row, rowIndex) in block.rows" :key="`tr-${rowIndex}`">
                          <td
                            v-for="(cell, cellIndex) in row"
                            :key="`td-${rowIndex}-${cellIndex}`"
                            dir="auto"
                            :class="{ num: /^-?[\d.,%]+$/.test(cell.map(span => span.text).join('').trim()) }"
                          >
                            <template v-for="(span, spanIndex) in cell" :key="`tdc-${spanIndex}`">
                              <strong v-if="span.bold">{{ span.text }}</strong>
                              <code v-else-if="span.code">{{ span.text }}</code>
                              <template v-else>{{ span.text }}</template>
                            </template>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <component
                    :is="block.ordered ? 'ol' : 'ul'"
                    v-else-if="block.type === 'list'"
                    class="msg-list"
                  >
                    <li v-for="(item, itemIndex) in block.items" :key="`li-${itemIndex}`">
                      <template v-for="(span, spanIndex) in item" :key="`lic-${spanIndex}`">
                        <strong v-if="span.bold">{{ span.text }}</strong>
                        <code v-else-if="span.code">{{ span.text }}</code>
                        <template v-else>{{ span.text }}</template>
                      </template>
                    </li>
                  </component>

                  <p v-else class="msg-text" dir="auto">
                    <template v-for="(span, spanIndex) in block.spans" :key="`p-${spanIndex}`">
                      <strong v-if="span.bold">{{ span.text }}</strong>
                      <code v-else-if="span.code">{{ span.text }}</code>
                      <template v-else>{{ span.text }}</template>
                    </template>
                  </p>
                </template>
              </div>

              <div v-if="warningFor(message).length" class="banner ungrounded" data-tone="warn" role="alert">
                <svg aria-hidden="true"><use href="#i-alert" /></svg>
                <div class="cell-stack">
                  <strong>{{ t('intelligence.ungroundedTitle', locale) }}</strong>
                  <span>{{ t('intelligence.ungroundedLead', locale) }}</span>
                  <span class="row">
                    <code
                      v-for="figure in warningFor(message)"
                      :key="`${message.id}-ungrounded-${figure}`"
                      class="num-chip"
                    >
                      {{ figure }}
                    </code>
                  </span>
                </div>
              </div>

              <div v-if="messageRefs(message).length" class="ev-row">
                <span class="ev-label">{{ t('intelligence.evidence', locale) }}</span>
                <code
                  v-for="reference in messageRefs(message)"
                  :key="`${message.id}-ref-${reference}`"
                  class="ev-chip"
                  tabindex="0"
                  role="button"
                  :aria-label="`${t('intelligence.copyEvidence', locale)}: ${reference}`"
                  @click="copyRef(reference)"
                  @keydown.enter.prevent="copyRef(reference)"
                  @keydown.space.prevent="copyRef(reference)"
                >
                  {{ reference }}
                </code>
              </div>

              <details v-if="message.tool_trace.length" class="trace">
                <summary>
                  <svg class="chev" aria-hidden="true"><use href="#i-chev-r" /></svg>
                  <span>{{ toolSummary(message.tool_trace) }}</span>
                </summary>
                <ol class="trace-list">
                  <li
                    v-for="(toolCall, index) in message.tool_trace"
                    :key="`${message.id}-call-${index}`"
                    class="trace-call"
                  >
                    <div class="trace-head">
                      <code class="trace-name">{{ toolCall.name }}</code>
                      <span
                        class="badge"
                        :class="toolCall.refused ? 'warn' : toolCall.ok ? 'ok' : 'err'"
                      >
                        {{ toolCall.refused
                          ? t('intelligence.toolRefused', locale)
                          : toolCall.ok
                            ? t('intelligence.toolOk', locale)
                            : t('intelligence.toolError', locale) }}
                      </span>
                      <span v-if="toolCall.code" class="badge plain">{{ toolCall.code }}</span>
                    </div>
                    <div class="trace-line">
                      <span class="trace-k">{{ t('intelligence.input', locale) }}</span>
                      <code class="trace-json">{{ compactJson(toolCall.input) }}</code>
                    </div>
                    <div v-if="toolCall.evidence_ref" class="trace-line">
                      <span class="trace-k">{{ t('intelligence.evidence', locale) }}</span>
                      <code class="ev-chip">{{ toolCall.evidence_ref }}</code>
                    </div>
                    <p v-if="toolCall.error" class="trace-error">{{ toolCall.error }}</p>
                  </li>
                </ol>
              </details>

              <div v-if="message.usage && message.usage.total_tokens != null" class="msg-usage mono">
                <span>
                  {{ t('intelligence.promptTokens', locale) }} {{ num(message.usage.prompt_tokens) }}
                  + {{ t('intelligence.completionTokens', locale) }} {{ num(message.usage.completion_tokens) }}
                  = {{ num(message.usage.total_tokens) }} {{ t('intelligence.tokens', locale) }}
                </span>
                <span v-if="message.latency_ms != null">
                  · {{ t('intelligence.latency', locale) }} {{ num(message.latency_ms) }}
                  {{ t('intelligence.milliseconds', locale) }}
                </span>
                <span v-if="message.provider_id || message.model_id">
                  · {{ message.provider_id }} / {{ message.model_id }}
                </span>
              </div>
            </template>

            <p v-else class="msg-text" dir="auto">{{ message.content }}</p>
          </article>

          <div v-if="sending" class="thinking" role="status">
            <span class="spinner" aria-hidden="true"></span>
            <span>{{ t('intelligence.thinking', locale) }}</span>
          </div>

          <div ref="streamEnd" class="stream-end"></div>
        </div>

        <div class="composer">
          <label class="sr-only" for="intelligence-composer">
            {{ t('intelligence.composerLabel', locale) }}
          </label>
          <textarea
            id="intelligence-composer"
            ref="composerEl"
            v-model="composer"
            rows="2"
            :placeholder="t('intelligence.composerPlaceholder', locale)"
            :disabled="sending"
            @input="autoGrow"
            @keydown.enter.exact.prevent="send"
          ></textarea>
          <div class="composer-foot">
            <span class="muted composer-hint">{{ t('intelligence.composerHint', locale) }}</span>
            <button
              class="btn-primary"
              type="button"
              :disabled="sending || !composer.trim()"
              @click="send"
            >
              <span v-if="sending" class="spinner" aria-hidden="true"></span>
              {{ sending ? t('intelligence.thinking', locale) : t('intelligence.send', locale) }}
            </button>
          </div>
          <span v-if="copied" class="copy-toast" role="status">
            {{ t('intelligence.copied', locale) }}
          </span>
        </div>
      </DcCard>
    </div>
  </section>
</template>

<style scoped>
.error-banner-row {
  margin-bottom: 14px;
}
.error-banner-row > span:nth-child(2) {
  flex: 1;
  min-width: 0;
}
.model-banner {
  margin-bottom: 14px;
}
.model-banner .cell-stack {
  flex: 1;
}
.chat-shell {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.conv-rail {
  position: sticky;
  top: calc(var(--topbar-h) + 12px);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - var(--topbar-h) - 40px);
  overflow: hidden;
  margin-bottom: 0;
}
.rail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 11px 12px;
  border-bottom: 1px solid var(--border);
}
.rail-head h2 {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--muted);
}
.conv-list {
  list-style: none;
  margin: 0;
  padding: 6px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.conv-item {
  display: flex;
  align-items: stretch;
  gap: 2px;
  border-radius: var(--r);
  border: 1px solid transparent;
}
.conv-item:hover {
  background: var(--surface-2);
}
.conv-item.active {
  background: var(--accent-soft);
  border-color: var(--accent-line);
}
.conv-main {
  flex: 1;
  min-width: 0;
  text-align: start;
  padding: 8px 9px;
  border-radius: var(--r);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.conv-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--fg);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 10.5px;
  color: var(--muted);
}
.conv-del {
  width: 26px;
  height: auto;
  align-self: stretch;
  border-radius: var(--r);
  opacity: 0.55;
}
.conv-del:hover {
  opacity: 1;
  color: var(--crit-ink);
}
.conv-del svg {
  width: 14px;
  height: 14px;
}
.rail-empty {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px 13px;
  font-size: 12.5px;
}
.rail-empty .muted {
  font-size: 11.5px;
}
.rail-skeleton,
.stream-skeleton {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 12px;
}
.rail-skeleton span,
.stream-skeleton span {
  display: block;
  height: 13px;
  border-radius: var(--r-sm);
  background: linear-gradient(90deg, var(--surface-2), var(--surface-3), var(--surface-2));
  background-size: 200% 100%;
  animation: chat-shimmer 1.2s ease-in-out infinite;
}
.rail-skeleton span:nth-child(2n),
.stream-skeleton span:nth-child(2n) {
  width: 72%;
}
.rail-skeleton span:nth-child(3n),
.stream-skeleton span:nth-child(3n) {
  width: 84%;
}
@keyframes chat-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}
.stream {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--topbar-h) - 132px);
  min-height: 520px;
  overflow: hidden;
  margin-bottom: 0;
}
/* DcCard wraps the slot in .card-body; drop its padding and let the inner
   scroll area own the height so the composer is always pinned, never overlapped. */
.stream :deep(.card-body) {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  min-height: 0;
  padding: 0;
}
.stream-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 13px;
  scrollbar-gutter: stable;
}
.stream-empty {
  padding: 26px 12px;
  gap: 7px;
}
.stream-empty .muted {
  max-width: 58ch;
}
.suggestions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
  max-width: 58ch;
  margin-top: 8px;
}
.sugg-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--faint);
  text-align: start;
}
.suggestion {
  width: 100%;
  text-align: start;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--surface);
  color: var(--fg);
  font-size: 12.5px;
  transition: background 0.12s ease, border-color 0.12s ease;
}
.suggestion:hover {
  background: var(--accent-soft);
  border-color: var(--accent-line);
}
.msg {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: 10px 12px;
  max-width: 92%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.msg[data-role="user"] {
  background: var(--accent-soft);
  border-color: var(--accent-line);
  margin-inline-start: auto;
}
.msg[data-role="assistant"] {
  background: var(--surface);
  width: 100%;
  max-width: 100%;
  margin-inline-end: auto;
}
.msg-role {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  font-size: 10.5px;
}
.role-mark {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
.msg[data-role="user"] .role-mark {
  color: var(--accent-ink);
}
.msg-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.msg-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 13px;
  line-height: 1.55;
}
.msg-code {
  margin: 0;
  padding: 9px 11px;
  border-radius: var(--r);
  border: 1px solid var(--border);
  background: var(--surface-2);
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.ungrounded {
  align-items: flex-start;
}
.msg-heading {
  font-size: 13px;
  font-weight: 650;
  color: var(--fg-strong);
  letter-spacing: -0.01em;
  margin: 2px 0 0;
}
.msg-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 11.5px;
  padding: 1px 5px;
  border-radius: var(--r-xs);
  background: var(--surface-3);
  color: var(--fg-strong);
  unicode-bidi: isolate;
}
.msg-list {
  margin: 0;
  padding-inline-start: 18px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 13px;
  line-height: 1.55;
}
.msg-list li::marker {
  color: var(--faint);
}
.msg-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--r);
}
.msg-table {
  font-size: 12px;
}
.msg-table th {
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  text-align: start;
}
.msg-table td {
  padding: 5px 10px;
  border-bottom: 1px solid var(--border);
}
.msg-table tbody tr:last-child td {
  border-bottom: 0;
}
.msg-table td.num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  text-align: end;
}
.ungrounded .cell-stack {
  gap: 3px;
}
.num-chip {
  display: inline-block;
  padding: 1px 7px;
  border-radius: var(--r-full);
  border: 1px solid color-mix(in oklch, var(--warn) 45%, transparent);
  background: var(--surface);
  font-size: 11px;
}
.ev-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.ev-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--faint);
}
.ev-chip {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--r-full);
  border: 1px solid var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent-ink);
  font-size: 11px;
  cursor: copy;
  user-select: all;
  white-space: nowrap;
}
.trace {
  border-top: 1px dashed var(--border);
  padding-top: 7px;
}
.trace summary {
  display: flex;
  align-items: center;
  gap: 6px;
  list-style: none;
  cursor: pointer;
  font-size: 11.5px;
  color: var(--muted);
  width: fit-content;
}
.trace summary::-webkit-details-marker {
  display: none;
}
.trace summary:hover {
  color: var(--fg);
}
.chev {
  width: 12px;
  height: 12px;
  transition: transform 0.12s ease;
}
.trace[open] .chev {
  transform: rotate(90deg);
}
.trace-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.trace-call {
  border: 1px solid var(--border);
  border-radius: var(--r);
  padding: 8px 10px;
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.trace-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}
.trace-name {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--fg-strong);
}
.trace-line {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 11px;
}
.trace-k {
  flex: none;
  color: var(--faint);
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 9.5px;
  padding-top: 2px;
}
.trace-json {
  color: var(--muted);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.trace-error {
  color: var(--crit-ink);
  font-size: 11.5px;
}
.msg-usage {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 10.5px;
  color: var(--faint);
  border-top: 1px dashed var(--border);
  padding-top: 7px;
}
.thinking {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
  padding: 4px 2px;
}
.spinner {
  display: inline-block;
  width: 13px;
  height: 13px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: chat-spin 0.7s linear infinite;
}
@keyframes chat-spin {
  to { transform: rotate(360deg); }
}
.composer {
  position: relative;
  border-top: 1px solid var(--border);
  padding: 10px 12px 12px;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: 7px;
  box-shadow: 0 -8px 16px -12px oklch(20% 0.03 260 / 0.45);
  z-index: 1;
}
.composer textarea {
  width: 100%;
  resize: none;
  min-height: 44px;
  max-height: 200px;
  overflow-y: auto;
  line-height: 1.5;
}
.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.composer-hint {
  font-size: 11px;
}
.copy-toast {
  position: absolute;
  inset-inline-end: 12px;
  bottom: calc(100% + 6px);
  padding: 3px 9px;
  border-radius: var(--r-full);
  background: var(--fg-strong);
  color: var(--surface);
  font-size: 11px;
}
.stream-end {
  height: 1px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@media (max-width: 820px) {
  .chat-shell {
    grid-template-columns: minmax(0, 1fr);
  }
  .conv-rail {
    position: static;
    max-height: 240px;
  }
  .stream-scroll {
    max-height: none;
    min-height: 300px;
  }
  .msg {
    max-width: 100%;
  }
}
</style>
