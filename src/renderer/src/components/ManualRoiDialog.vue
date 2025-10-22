<template>
  <div v-if="visible" class="roi-overlay">
    <div class="roi-dialog">
      <header class="dialog-header">
        <h2>选择处理区域</h2>
        <p>拖拽首帧定义需要额外匿名化的区域，或直接点击“开始处理”。</p>
      </header>
            <section class="frame-section" v-if="frameUrl">
              <div class="frame-wrapper" :style="{ aspectRatio: frameAspectRatio }">
                <img :src="frameUrl" alt="视频首帧" class="frame-image" />
                <canvas
                  ref="canvasRef"
                  class="frame-canvas"
                  @pointerdown.prevent="beginDraw"
                  @pointermove.prevent="updateDraw"
                  @pointerup.prevent="finishDraw"
                  @pointerleave.prevent="cancelDraw"
                />
              </div>
            </section>
      <section v-else class="frame-section frame-section--loading">
        <p>正在加载视频首帧...</p>
      </section>
      <section class="options-section">
        <h3>检测类别</h3>
        <div class="options-grid">
          <label v-for="cls in allClasses" :key="cls">
            <input type="checkbox" :value="cls" v-model="selectedClasses" />
            <span>{{ cls }}</span>
          </label>
        </div>
      </section>
      <section class="roi-list">
        <header>
          <h3>手动区域 ({{ rois.length }})</h3>
          <button type="button" class="link" @click="resetRois" :disabled="!rois.length">
            清空区域
          </button>
        </header>
        <ul v-if="rois.length">
          <li v-for="roi in rois" :key="roi.id">
            <span>#{{ roi.id + 1 }} - {{ formatRoi(roi) }}</span>
            <button type="button" class="link" @click="removeRoi(roi.id)">
              移除
            </button>
          </li>
        </ul>
        <p v-else class="hint">按住鼠标拖拽即可添加跟踪区域。</p>
      </section>
      <footer class="dialog-actions">
        <button type="button" class="secondary" @click="cancel">取消</button>
        <button type="button" class="primary" @click="confirm" :disabled="!frameUrl">开始处理</button>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, toRefs, watch } from 'vue';

type Roi = { id: number; x1: number; y1: number; x2: number; y2: number };
type RoiPayload = { classes: string[]; manualRois: Array<[number, number, number, number]> };

type Props = {
  visible: boolean;
  file: File | null;
};

const props = defineProps<Props>();
const emit = defineEmits<{
  cancel: [];
  confirm: [RoiPayload];
}>();

const { visible } = toRefs(props);

const canvasRef = ref<HTMLCanvasElement | null>(null);
const frameUrl = ref<string>('');
const allClasses = ['person', 'car', 'truck', 'bus', 'motorcycle', 'motorbike'];
const selectedClasses = ref<string[]>([...allClasses]);
const rois = ref<Roi[]>([]);
const drawingState = reactive({ active: false, pointerId: 0, startX: 0, startY: 0, currentX: 0, currentY: 0 });
const videoSize = reactive({ width: 0, height: 0 });

const frameAspectRatio = computed(() => {
  if (videoSize.width > 0 && videoSize.height > 0) {
    return `${videoSize.width} / ${videoSize.height}`;
  }
  return '16 / 9';
});

let objectUrl: string | null = null;
let roiCounter = 0;

watch(
  () => props.file,
  () => {
    if (props.visible) {
      loadFirstFrame();
    }
  }
);

watch(visible, (isVisible) => {
  if (isVisible) {
    loadFirstFrame();
  } else {
    cleanup();
  }
});

watch(rois, () => drawCanvas(), { deep: true });

onBeforeUnmount(() => {
  cleanup();
});

function cleanup(): void {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }
  frameUrl.value = '';
  resetDrawingState();
}

async function loadFirstFrame(): Promise<void> {
  resetDrawingState();
  if (!props.file) {
    frameUrl.value = '';
    return;
  }
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl);
  }
  objectUrl = URL.createObjectURL(props.file);

  const video = document.createElement('video');
  video.src = objectUrl;
  video.muted = true;
  video.playsInline = true;
  video.preload = 'auto';

  const captureFrame = () => {
    const width = video.videoWidth;
    const height = video.videoHeight;
    if (!width || !height) {
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
      return;
    }
  ctx.drawImage(video, 0, 0, width, height);
  frameUrl.value = canvas.toDataURL('image/jpeg', 0.9);
    videoSize.width = width;
    videoSize.height = height;
    nextTick(() => drawCanvas());
  };

  await new Promise<void>((resolve) => {
    let settled = false;

    const attemptCapture = () => {
      if (!video.videoWidth || !video.videoHeight) {
        return false;
      }
      if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
        return false;
      }
      captureFrame();
      finish();
      return true;
    };

    const cleanupListeners = () => {
      video.removeEventListener('loadeddata', handleLoadedData);
      video.removeEventListener('loadedmetadata', handleLoadedMetadata);
      video.removeEventListener('seeked', handleSeeked);
      video.removeEventListener('error', handleError);
    };

    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      cleanupListeners();
      resolve();
    };

    const handleLoadedData = () => {
      if (!attemptCapture()) {
        window.setTimeout(() => {
          attemptCapture();
        }, 50);
      }
    };

    const handleSeeked = () => {
      attemptCapture();
    };

    const handleLoadedMetadata = () => {
      try {
        video.currentTime = 0;
      } catch (error) {
        console.warn('Failed to reset video currentTime for ROI preview', error);
      }

      const rvfc = (video as HTMLVideoElement & { requestVideoFrameCallback?: (callback: () => void) => void }).requestVideoFrameCallback;
      if (typeof rvfc === 'function') {
        rvfc.call(video, () => {
          attemptCapture();
        });
      }
    };

    const handleError = (event: Event) => {
      console.error('Failed to load video for ROI selection', event);
      frameUrl.value = '';
      finish();
    };

    video.addEventListener('loadeddata', handleLoadedData);
    video.addEventListener('loadedmetadata', handleLoadedMetadata);
    video.addEventListener('seeked', handleSeeked);
    video.addEventListener('error', handleError);

    video.load();
    void video.play().catch(() => {
      video.pause();
    });
  });

  video.pause();
  video.removeAttribute('src');
  video.load();
}

function resetDrawingState(): void {
  drawingState.active = false;
  drawingState.pointerId = 0;
  drawingState.startX = 0;
  drawingState.startY = 0;
  drawingState.currentX = 0;
  drawingState.currentY = 0;
}

function toVideoCoords(event: PointerEvent): { x: number; y: number } {
  const canvas = canvasRef.value;
  if (!canvas) {
    return { x: 0, y: 0 };
  }
  const rect = canvas.getBoundingClientRect();
  const scaleX = videoSize.width / rect.width;
  const scaleY = videoSize.height / rect.height;
  const x = (event.clientX - rect.left) * scaleX;
  const y = (event.clientY - rect.top) * scaleY;
  return {
    x: clamp(Math.round(x), 0, videoSize.width),
    y: clamp(Math.round(y), 0, videoSize.height)
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function beginDraw(event: PointerEvent): void {
  if (!canvasRef.value || drawingState.active) {
    return;
  }
  const { x, y } = toVideoCoords(event);
  drawingState.active = true;
  drawingState.pointerId = event.pointerId;
  drawingState.startX = x;
  drawingState.startY = y;
  drawingState.currentX = x;
  drawingState.currentY = y;
  canvasRef.value.setPointerCapture(event.pointerId);
  drawCanvas();
}

function updateDraw(event: PointerEvent): void {
  if (!drawingState.active) {
    return;
  }
  const { x, y } = toVideoCoords(event);
  drawingState.currentX = x;
  drawingState.currentY = y;
  drawCanvas();
}

function finishDraw(event: PointerEvent): void {
  if (!drawingState.active || !canvasRef.value) {
    return;
  }
  canvasRef.value.releasePointerCapture(event.pointerId);
  const { x, y } = toVideoCoords(event);
  const x1 = Math.min(drawingState.startX, x);
  const y1 = Math.min(drawingState.startY, y);
  const x2 = Math.max(drawingState.startX, x);
  const y2 = Math.max(drawingState.startY, y);
  if (x2 - x1 > 4 && y2 - y1 > 4) {
    rois.value.push({ id: roiCounter++, x1, y1, x2, y2 });
  }
  resetDrawingState();
  drawCanvas();
}

function cancelDraw(event: PointerEvent): void {
  if (!drawingState.active || !canvasRef.value) {
    return;
  }
  canvasRef.value.releasePointerCapture(event.pointerId);
  resetDrawingState();
  drawCanvas();
}

function drawCanvas(): void {
  const canvas = canvasRef.value;
  if (!canvas) {
    return;
  }
  canvas.width = videoSize.width || 1;
  canvas.height = videoSize.height || 1;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return;
  }
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.lineWidth = 3;
  ctx.strokeStyle = '#42b883';
  ctx.setLineDash([8, 6]);

  for (const roi of rois.value) {
    ctx.strokeRect(roi.x1, roi.y1, roi.x2 - roi.x1, roi.y2 - roi.y1);
  }

  if (drawingState.active) {
    ctx.strokeStyle = '#f5a623';
    ctx.strokeRect(
      Math.min(drawingState.startX, drawingState.currentX),
      Math.min(drawingState.startY, drawingState.currentY),
      Math.abs(drawingState.currentX - drawingState.startX),
      Math.abs(drawingState.currentY - drawingState.startY)
    );
  }
}

function resetRois(): void {
  rois.value = [];
  roiCounter = 0;
  drawCanvas();
}

function removeRoi(id: number): void {
  rois.value = rois.value.filter((roi) => roi.id !== id);
  drawCanvas();
}

function formatRoi(roi: Roi): string {
  return `(${roi.x1}, ${roi.y1}) → (${roi.x2}, ${roi.y2})`;
}

function cancel(): void {
  emit('cancel');
}

function confirm(): void {
  const payload: RoiPayload = {
    classes: [...selectedClasses.value],
    manualRois: rois.value.map((roi) => [roi.x1, roi.y1, roi.x2, roi.y2])
  };
  emit('confirm', payload);
}
</script>

<style scoped>
.roi-overlay {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.6);
  z-index: 1000;
  padding: 2rem;
}

.roi-dialog {
  width: min(960px, 100%);
  max-height: 95vh;
  overflow-y: auto;
  background: #1e1f24;
  border-radius: 16px;
  padding: 1.5rem;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.dialog-header h2 {
  margin-bottom: 0.5rem;
}

.frame-section {
  position: relative;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 12px;
  padding: 1rem;
}

.frame-section--loading {
  text-align: center;
  color: rgba(255, 255, 255, 0.7);
}

.frame-wrapper {
  position: relative;
  width: 100%;
  background: rgba(0, 0, 0, 0.4);
  border-radius: 8px;
  overflow: hidden;
}

.frame-image {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
}

.frame-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  cursor: crosshair;
}

.options-section h3,
.roi-list h3 {
  margin-bottom: 0.75rem;
}

.options-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.75rem;
}

.options-grid label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.05);
}

.roi-list header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.roi-list ul {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.roi-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.04);
}

.hint {
  color: rgba(255, 255, 255, 0.6);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
}

button {
  border: none;
  cursor: pointer;
  border-radius: 8px;
  padding: 0.65rem 1.25rem;
}

button.primary {
  background: #42b883;
  color: #fff;
}

button.primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

button.secondary {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

button.link {
  background: none;
  color: #42b883;
  padding: 0;
}
</style>
