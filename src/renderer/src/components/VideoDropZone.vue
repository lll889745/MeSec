<template>
  <div
    class="dropzone"
    @dragover.prevent
    @drop.prevent="handleDrop"
  >
    <p>拖拽视频文件到此处，或点击选择文件</p>
    <input
      ref="fileInput"
      type="file"
      accept="video/*"
      class="hidden-input"
      @change="handleFileSelect"
    />
    <button type="button" @click="openFilePicker">选择文件</button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const emit = defineEmits<{
  process: [File]
}>();

const fileInput = ref<HTMLInputElement | null>(null);

function openFilePicker() {
  fileInput.value?.click();
}

function handleFileSelect(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.item(0);
  if (file) {
    emit('process', file);
  }
  if (target) {
    target.value = '';
  }
}

function handleDrop(event: DragEvent) {
  const file = event.dataTransfer?.files?.item(0);
  if (file) {
    emit('process', file);
    if (fileInput.value) {
      fileInput.value.value = '';
    }
  }
}
</script>

<style scoped>
.dropzone {
  border: 2px dashed rgba(255, 255, 255, 0.3);
  border-radius: 12px;
  padding: 2rem;
  text-align: center;
  background: rgba(18, 18, 18, 0.8);
}

.hidden-input {
  display: none;
}

button {
  margin-top: 1.5rem;
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  border: none;
  background: #42b883;
  color: #fff;
  cursor: pointer;
}

button:hover {
  background: #36a173;
}
</style>
