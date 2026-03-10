<template>
  <div class="panel" data-testid="log-panel">
    <h4 style="margin-top:0">
      诊断 / 日志
      <button class="secondary" style="font-size:12px; padding:2px 8px; margin-left:8px" data-testid="log-toggle" @click="expanded = !expanded">
        {{ expanded ? '收起' : '展开' }}
      </button>
    </h4>
    <pre v-if="expanded" data-testid="log-area" style="white-space:pre-wrap; margin:0; max-height:200px; overflow:auto">
      <template v-for="entry in logs" :key="entry.time + entry.message">[{{ entry.time }}] {{ entry.message }}
</template>
    </pre>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  logs: { type: Array, default: () => [] },
})

const expanded = ref(true)
</script>
