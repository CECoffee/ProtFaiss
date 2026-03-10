<template>
  <div class="input-section" data-testid="input-section">
    <label for="seq">输入序列（FASTA 或纯序列）</label>
    <textarea
      id="seq"
      v-model="sequence"
      data-testid="sequence-input"
      placeholder=">Query_1&#10;MSNYFVSGISSGI..."
    ></textarea>

    <div class="controls">
      <div>
        Top-N:
        <input v-model.number="topK" type="number" min="1" max="50" style="width:72px" data-testid="topk-input" />
      </div>
      <div>
        Pooling:
        <select v-model="pooling" data-testid="pooling-select">
          <option value="mean">mean</option>
          <option value="max">max</option>
          <option value="sum">sum</option>
        </select>
      </div>
      <div style="margin-left:auto">
        <button data-testid="submit-btn" @click="handleSubmit">提交任务</button>
        <button class="secondary" style="margin-left:8px" data-testid="cancel-btn" @click="$emit('cancel')">停止轮询</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const emit = defineEmits(['submit', 'cancel'])

const sequence = ref('')
const topK = ref(5)
const pooling = ref('mean')

function handleSubmit() {
  if (!sequence.value.trim()) {
    alert('请填写查询序列')
    return
  }
  emit('submit', { sequence: sequence.value.trim(), topK: topK.value, pooling: pooling.value })
}
</script>
