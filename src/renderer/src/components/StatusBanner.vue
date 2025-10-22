<template>
  <aside class="status-banner">
    <h2>系统状态</h2>
    <p>{{ status }}</p>
  </aside>
</template>

<script setup lang="ts">
defineProps<{
  status: string;
}>();
</script>

<style scoped>
.status-banner {
  border-radius: 12px;
  padding: 1.5rem;
  background: linear-gradient(135deg, rgba(66, 184, 131, 0.2), rgba(35, 39, 47, 0.8));
  backdrop-filter: blur(6px);
}

.status-banner h2 {
  margin-bottom: 0.75rem;
  font-size: 1.25rem;
}
</style>
