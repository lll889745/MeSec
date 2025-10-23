<template>
  <aside class="status-banner">
    <p class="status-line">{{ status }}</p>
    <div v-if="progressValue !== null" class="progress">
      <div class="progress__bar">
        <div class="progress__fill" :style="{ width: `${progressValue}%` }" />
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, toRefs } from 'vue';

const rawProps = defineProps<{
  status: string;
  progress?: number | null;
}>();

const { status, progress } = toRefs(rawProps);

const progressValue = computed(() => {
  const value = progress.value;
  if (value === null || value === undefined) {
    return null;
  }
  return Math.min(100, Math.max(0, value));
});

const progressLabel = computed(() => {
  if (progressValue.value === null) {
    return '';
  }
  const value = progressValue.value;
  const precision = value < 10 ? 1 : 0;
  return value.toFixed(precision);
});
</script>

<style scoped>
.status-banner {
  border-radius: 12px;
  padding: 1.5rem;
  background: linear-gradient(135deg, rgba(66, 184, 131, 0.2), rgba(35, 39, 47, 0.8));
  backdrop-filter: blur(6px);
}

.status-line {
  font-weight: 600;
  margin: 0 0 0.5rem 0;
}

.progress {
  margin-top: 1rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.progress__bar {
  flex: 1;
  height: 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  overflow: hidden;
}

.progress__fill {
  height: 100%;
  background: linear-gradient(90deg, #42b883, #36a173);
  transition: width 0.2s ease;
}

.progress span {
  font-variant-numeric: tabular-nums;
  font-size: 0.9rem;
  color: rgba(255, 255, 255, 0.9);
}
</style>
