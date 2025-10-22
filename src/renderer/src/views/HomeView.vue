<template>
  <main class="home-view">
    <section class="hero">
      <h1>可逆视频匿名化工具</h1>
      <p>利用深度学习和加密技术，在保障隐私的同时保留可恢复的原始信息。</p>
    </section>
    <section class="actions">
      <VideoDropZone @process="handleProcess" />
      <StatusBanner :status="statusMessage" :progress="progressValue" />
    </section>
    <section v-if="hasLatestOutput" class="results">
      <h2>最近任务输出</h2>
      <dl class="results__list">
        <div v-if="latestOutput.output">
          <dt>匿名视频</dt>
          <dd>{{ latestOutput.output }}</dd>
        </div>
        <div v-if="latestOutput.dataPack">
          <dt>加密数据包</dt>
          <dd>{{ latestOutput.dataPack }}</dd>
        </div>
        <div v-if="latestOutput.digest">
          <dt>数据包哈希</dt>
          <dd>{{ latestOutput.digest }}</dd>
        </div>
        <div v-if="latestOutput.aesKey">
          <dt>AES 密钥</dt>
          <dd>{{ latestOutput.aesKey }}</dd>
        </div>
        <div v-if="latestOutput.hmacKey">
          <dt>HMAC 密钥</dt>
          <dd>{{ latestOutput.hmacKey }}</dd>
        </div>
        <div v-if="latestOutput.restored">
          <dt>恢复输出</dt>
          <dd>{{ latestOutput.restored }}</dd>
        </div>
      </dl>
      <div class="results__actions">
        <button
          type="button"
          class="secondary"
          @click="triggerRestore"
          :disabled="!canRestoreFromLatest || isProcessing"
        >
          使用上述文件恢复原视频
        </button>
        <p v-if="!canRestoreFromLatest" class="hint">需要匿名视频、数据包和 AES 密钥才能发起恢复。</p>
      </div>
    </section>
  </main>
  <ManualRoiDialog
    :visible="showManualDialog"
    :file="selectedFile"
    @cancel="handleDialogCancel"
    @confirm="handleDialogConfirm"
  />
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import VideoDropZone from '../components/VideoDropZone.vue';
import StatusBanner from '../components/StatusBanner.vue';
import ManualRoiDialog from '../components/ManualRoiDialog.vue';

type FileWithPath = File & { path?: string };
type JobEventPayload = { jobId: string; event: string; [key: string]: unknown };
type LatestOutput = {
  output?: string;
  dataPack?: string;
  digest?: string;
  aesKey?: string;
  hmacKey?: string;
  restored?: string;
};

const statusMessage = ref('等待视频输入');
const selectedFile = ref<FileWithPath | null>(null);
const showManualDialog = ref(false);
const isProcessing = ref(false);
const processedFrames = ref(0);
const totalFrames = ref(0);
const activeJobId = ref<string | null>(null);
const activeJobType = ref<'anonymize' | 'restore' | null>(null);
const eventUnsubscribe = ref<(() => void) | null>(null);
const restoreEventUnsubscribe = ref<(() => void) | null>(null);
const latestOutput = ref<LatestOutput>({});

const progressValue = computed(() => {
  if (!isProcessing.value) {
    return null;
  }
  if (totalFrames.value > 0) {
    return Math.min(100, Math.max(0, (processedFrames.value / totalFrames.value) * 100));
  }
  if (processedFrames.value === 0) {
    return 0;
  }
  return Math.min(100, processedFrames.value);
});

const canRestoreFromLatest = computed(() => {
  const { output, dataPack, aesKey } = latestOutput.value;
  return Boolean(output && dataPack && aesKey);
});

const hasLatestOutput = computed(() => {
  const value = latestOutput.value;
  return Boolean(value.output || value.dataPack || value.digest || value.aesKey || value.hmacKey || value.restored);
});

function handleProcess(file: File) {
  if (isProcessing.value) {
    statusMessage.value = '已有任务在执行，请等待完成或取消';
    return;
  }
  const candidate = file as FileWithPath;
  if (!candidate.path) {
    statusMessage.value = '无法获取视频文件路径，请检查应用权限';
    return;
  }
  selectedFile.value = candidate;
  showManualDialog.value = true;
}

function handleDialogCancel(): void {
  showManualDialog.value = false;
  selectedFile.value = null;
  statusMessage.value = '已取消选择';
}

async function handleDialogConfirm(payload: { classes: string[]; manualRois: Array<[number, number, number, number]> }): Promise<void> {
  const file = selectedFile.value;
  showManualDialog.value = false;
  if (!file?.path) {
    statusMessage.value = '无法获取视频文件路径';
    return;
  }

  statusMessage.value = `任务启动: ${file.name}`;
  isProcessing.value = true;
  processedFrames.value = 0;
  totalFrames.value = 0;
  activeJobType.value = 'anonymize';
  latestOutput.value = {};

  try {
    const response = await window.electronAPI.startAnonymize({
      inputPath: file.path,
      classes: payload.classes.length ? payload.classes : undefined,
      manualRois: payload.manualRois.length ? payload.manualRois : undefined
    });
    selectedFile.value = null;
    activeJobId.value = response.jobId;
    statusMessage.value = '匿名任务已启动';
    latestOutput.value = {
      output: response.outputPath,
      dataPack: response.dataPackPath
    };
  } catch (error) {
    console.error('Failed to start anonymization', error);
    statusMessage.value = '任务启动失败';
    isProcessing.value = false;
    activeJobId.value = null;
    selectedFile.value = null;
    activeJobType.value = null;
  }
}

function handleAnonymizeEvent(payload: JobEventPayload): void {
  if (payload.jobId !== activeJobId.value) {
    return;
  }
  const event = String(payload.event ?? '');
  switch (event) {
    case 'started': {
      statusMessage.value = '匿名任务已启动';
      break;
    }
    case 'metadata': {
      const total = Number(payload.total_frames ?? payload.totalFrames ?? 0) || 0;
      if (total) {
        totalFrames.value = total;
      }
      statusMessage.value = '匿名任务准备完成';
      break;
    }
    case 'progress': {
      processedFrames.value = Number(payload.processed ?? payload.frame_index ?? 0);
      const total = Number(payload.total_frames ?? payload.totalFrames ?? 0) || totalFrames.value;
      if (total) {
        totalFrames.value = total;
      }
      const percent = totalFrames.value
        ? Math.min(100, Math.max(0, (processedFrames.value / totalFrames.value) * 100))
        : null;
      if (percent !== null) {
        const precision = percent < 10 ? 1 : 0;
        statusMessage.value = `匿名处理中 ${processedFrames.value} / ${totalFrames.value} (${percent.toFixed(precision)}%)`;
      } else {
        statusMessage.value = `匿名处理中 ${processedFrames.value}`;
      }
      break;
    }
    case 'log': {
      const message = payload.message as string | undefined;
      if (message) {
        console.info('[python]', message);
      }
      break;
    }
    case 'detection':
    case 'manual_roi':
      break;
    case 'finalizing': {
      statusMessage.value = '匿名任务收尾中';
      break;
    }
    case 'finalized': {
      if (typeof payload.digest === 'string') {
        latestOutput.value = { ...latestOutput.value, digest: payload.digest as string };
      }
      if (totalFrames.value && isProcessing.value) {
        processedFrames.value = totalFrames.value;
      }
      break;
    }
    case 'completed': {
      isProcessing.value = false;
      const output = payload.output as string | undefined;
      const dataPack = payload.data_pack as string | undefined;
      const digest = payload.digest as string | undefined;
      const aesKey = payload.aes_key as string | undefined;
      const hmacKey = payload.hmac_key as string | undefined;
      if (totalFrames.value) {
        processedFrames.value = totalFrames.value;
      }
      latestOutput.value = { output, dataPack, digest, aesKey, hmacKey };
      statusMessage.value = output ? `匿名任务完成，输出文件位于 ${output}` : '匿名任务完成';
      activeJobId.value = null;
      activeJobType.value = null;
      break;
    }
    case 'error': {
      const message = payload.message as string | undefined;
      statusMessage.value = `任务失败：${message ?? '未知错误'}`;
      isProcessing.value = false;
      activeJobId.value = null;
      activeJobType.value = null;
      break;
    }
    case 'cancelled': {
      statusMessage.value = '匿名任务已取消';
      isProcessing.value = false;
      activeJobId.value = null;
      activeJobType.value = null;
      break;
    }
    case 'exit': {
      const code = payload.code as number | undefined;
      if (isProcessing.value && code && code !== 0) {
        statusMessage.value = `任务异常结束 (退出码 ${code})`;
        isProcessing.value = false;
        activeJobId.value = null;
        activeJobType.value = null;
      }
      break;
    }
    default:
      break;
  }
}

function handleRestoreEvent(payload: JobEventPayload): void {
  if (payload.jobId !== activeJobId.value) {
    return;
  }
  const event = String(payload.event ?? '');
  switch (event) {
    case 'started': {
      statusMessage.value = '恢复任务已启动';
      break;
    }
    case 'metadata': {
      const total = Number(payload.total_frames ?? payload.totalFrames ?? 0) || 0;
      if (total) {
        totalFrames.value = total;
      }
      statusMessage.value = '恢复准备完成';
      break;
    }
    case 'progress': {
      processedFrames.value = Number(payload.processed ?? payload.frame_index ?? 0);
      const total = Number(payload.total_frames ?? payload.totalFrames ?? 0) || totalFrames.value;
      if (total) {
        totalFrames.value = total;
      }
      const percent = totalFrames.value
        ? Math.min(100, Math.max(0, (processedFrames.value / totalFrames.value) * 100))
        : null;
      if (percent !== null) {
        const precision = percent < 10 ? 1 : 0;
        statusMessage.value = `恢复中 ${processedFrames.value} / ${totalFrames.value} (${percent.toFixed(precision)}%)`;
      } else {
        statusMessage.value = `恢复中 ${processedFrames.value}`;
      }
      break;
    }
    case 'log': {
      const message = payload.message as string | undefined;
      if (message) {
        console.info('[restore]', message);
      }
      break;
    }
    case 'completed': {
      isProcessing.value = false;
      const output = payload.output as string | undefined;
      if (totalFrames.value) {
        processedFrames.value = totalFrames.value;
      }
      latestOutput.value = { ...latestOutput.value, restored: output };
      statusMessage.value = output ? `恢复完成，输出文件位于 ${output}` : '恢复任务完成';
      activeJobId.value = null;
      activeJobType.value = null;
      break;
    }
    case 'error': {
      const message = payload.message as string | undefined;
      statusMessage.value = `恢复失败：${message ?? '未知错误'}`;
      isProcessing.value = false;
      activeJobId.value = null;
      activeJobType.value = null;
      break;
    }
    case 'cancelled': {
      statusMessage.value = '恢复任务已取消';
      isProcessing.value = false;
      activeJobId.value = null;
      activeJobType.value = null;
      break;
    }
    case 'exit': {
      const code = payload.code as number | undefined;
      if (isProcessing.value && code && code !== 0) {
        statusMessage.value = `恢复任务异常结束 (退出码 ${code})`;
        isProcessing.value = false;
        activeJobId.value = null;
        activeJobType.value = null;
      }
      break;
    }
    default:
      break;
  }
}

async function triggerRestore(): Promise<void> {
  if (isProcessing.value) {
    statusMessage.value = '已有任务在执行，请等待完成或取消';
    return;
  }
  const { output, dataPack, aesKey, hmacKey } = latestOutput.value;
  if (!output || !dataPack || !aesKey) {
    statusMessage.value = '缺少恢复所需的信息';
    return;
  }

  statusMessage.value = '准备启动恢复任务';
  isProcessing.value = true;
  processedFrames.value = 0;
  totalFrames.value = 0;
  activeJobType.value = 'restore';

  try {
    const response = await window.electronAPI.startRestore({
      anonymizedPath: output,
      dataPackPath: dataPack,
      aesKey,
      hmacKey: hmacKey || undefined
    });
    activeJobId.value = response.jobId;
    latestOutput.value = { ...latestOutput.value, restored: response.outputPath };
    statusMessage.value = '恢复任务已启动';
  } catch (error) {
    console.error('Failed to start restore', error);
    statusMessage.value = '恢复任务启动失败';
    isProcessing.value = false;
    activeJobId.value = null;
    activeJobType.value = null;
  }
}

onMounted(() => {
  eventUnsubscribe.value = window.electronAPI.onAnonymizeEvent(handleAnonymizeEvent);
  restoreEventUnsubscribe.value = window.electronAPI.onRestoreEvent(handleRestoreEvent);
});

onBeforeUnmount(() => {
  eventUnsubscribe.value?.();
  restoreEventUnsubscribe.value?.();
});
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

.results {
  border-radius: 12px;
  padding: 1.5rem;
  background: rgba(255, 255, 255, 0.04);
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.results__list {
  display: grid;
  gap: 0.75rem;
}

.results__list div {
  display: grid;
  grid-template-columns: 120px 1fr;
  align-items: center;
  gap: 0.75rem;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 0.75rem 1rem;
}

.results__list dt {
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}

.results__list dd {
  margin: 0;
  word-break: break-all;
  color: rgba(255, 255, 255, 0.8);
}

.results__actions {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
}

.results__actions button {
  border: none;
  border-radius: 8px;
  padding: 0.65rem 1.25rem;
  background: rgba(66, 184, 131, 0.15);
  color: #42b883;
  cursor: pointer;
}

.results__actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.results__actions .hint {
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.85rem;
}
</style>
