<template>
  <div class="app-shell">
    <RouterView />
  </div>
</template>

<script setup lang="ts">

</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  color: #e5e7eb;
  background: radial-gradient(circle at top, #1f2937, #111827 55%, #0b1120);
}
</style>
