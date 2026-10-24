<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <div class="page-head">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="muted">{{ subtitle }}</p>
    </div>
    <div class="row">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.page-head h1 {
  font-size: 22px;
  font-weight: 650;
  letter-spacing: -0.02em;
  color: var(--fg-strong);
}
.page-head .muted {
  font-size: 12.5px;
  margin-top: 2px;
  max-width: 80ch;
}
</style>
