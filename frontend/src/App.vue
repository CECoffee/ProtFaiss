<template>
  <div class="app-container">
    <NavTabs v-model="currentView" />
    <SearchView v-if="currentView === 'search'" @goto-datasets="currentView = 'datasets'" />
    <BuilderView
      v-else-if="currentView === 'builder'"
      @goto-datasets="currentView = 'datasets'"
    />
    <DatasetsView v-else />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import NavTabs from './components/NavTabs.vue'
import SearchView from './views/SearchView.vue'
import BuilderView from './views/BuilderView.vue'
import DatasetsView from './views/DatasetsView.vue'

const currentView = ref('search')
</script>

<style>
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  margin: 0;
  padding: 0;
  background: #f8fafc;
  color: #1e293b;
}
.app-container {
  max-width: 1000px;
  margin: 0 auto;
  padding: 32px 20px;
}
h1 { margin-bottom: 4px; }
h2 { margin-bottom: 12px; }
.small { color: #94a3b8; font-size: 0.85rem; margin: 0 0 20px; }
</style>
