<template>
  <div class="app-shell">
    <header class="app-header">
      <h1>Reversible Video Anonymizer</h1>
      <nav>
        <RouterLink to="/">控制台</RouterLink>
      </nav>
    </header>
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

.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 2rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(15, 23, 42, 0.75);
  backdrop-filter: blur(10px);
}

nav a {
  color: inherit;
  text-decoration: none;
  font-weight: 600;
}

nav a.router-link-active {
  color: #42b883;
}
</style>
