<template>
  <main class="home-view">
    <section class="hero">
      <h1>可逆视频匿名化工具</h1>
      <p>利用深度学习和加密技术，在保障隐私的同时保留可恢复的原始信息。</p>
    </section>
    <section class="actions">
      <VideoDropZone @process="handleProcess" />
      <StatusBanner :status="statusMessage" />
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import VideoDropZone from '../components/VideoDropZone.vue';
import StatusBanner from '../components/StatusBanner.vue';

const statusMessage = ref('等待视频输入');

function handleProcess(file: File) {
  statusMessage.value = `处理中: ${file.name}`;
  window.electronAPI.invoke('ping').then(() => {
    statusMessage.value = 'Electron 主进程响应正常';
  });
}
</script>

<style scoped>
.home-view {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 2.5rem;
}

.hero h1 {
  margin-bottom: 0.5rem;
}

.actions {
  display: grid;
  gap: 1.5rem;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}
</style>
