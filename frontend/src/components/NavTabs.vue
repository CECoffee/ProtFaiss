<template>
  <nav class="nav-tabs">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      class="tab-btn"
      :class="{ active: modelValue === tab.id }"
      @click="$emit('update:modelValue', tab.id)"
    >
      {{ tab.label }}
    </button>
  </nav>
</template>

<script setup>
defineProps({
  modelValue: {
    type: String,
    required: true,
  },
})
defineEmits(['update:modelValue'])

const tabs = [
  { id: 'search', label: 'Search' },
  { id: 'builder', label: 'Build Index' },
  { id: 'datasets', label: 'Manage Datasets' },
]
</script>

<style scoped>
.nav-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 24px;
  border-bottom: 2px solid #e2e8f0;
  padding-bottom: 0;
}
.tab-btn {
  padding: 8px 20px;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 0.95rem;
  color: #64748b;
  border-bottom: 2px solid transparent;
  margin-bottom: -2px;
  transition: color 0.15s, border-color 0.15s;
}
.tab-btn:hover {
  color: #334155;
}
.tab-btn.active {
  color: #3b82f6;
  border-bottom-color: #3b82f6;
  font-weight: 600;
}
</style>
