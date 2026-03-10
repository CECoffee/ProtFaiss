<template>
  <div class="panel" data-testid="status-panel">
    <div>
      <span class="chip" :class="`chip--${status}`" data-testid="status-chip">{{ status }}</span>
      <span class="small-muted">Task ID:</span>
      <code data-testid="task-id">{{ taskId || '-' }}</code>
    </div>
    <div class="meta" data-testid="status-meta">{{ meta }}</div>
  </div>
</template>

<script setup>
defineProps({
  status: { type: String, default: 'pending' },
  taskId: { type: String, default: null },
  meta: { type: String, default: '' },
})
</script>
