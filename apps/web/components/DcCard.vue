<script setup lang="ts">
defineProps<{
  title?: string
  tight?: boolean
}>()
</script>

<template>
  <section class="card">
    <header v-if="title || $slots.actions" class="card-header">
      <h2>{{ title }}</h2>
      <div class="row">
        <slot name="actions" />
      </div>
    </header>
    <div class="card-body" :class="{ tight }">
      <slot />
    </div>
  </section>
</template>
