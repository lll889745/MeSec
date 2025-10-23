# 可逆视频匿名化工具

一个基于 Electron 和 Vue 3 的桌面应用，集成了 Python、PyTorch 和 YOLOv8，提供高性能、可逆的视频隐私处理功能。

## ✨ 核心功能

- **多种匿名化风格**: 支持高斯模糊、像素化和马赛克三种效果。
- **可逆加密**: 对视频中的关键区域（ROI）进行 AES-256-GCM 加密，并将元数据打包，以便未来使用密钥恢复。
- **自动目标检测**: 利用 YOLOv8 模型自动识别和匿名化视频中的常见目标（如行人、车辆等）。
- **手动区域选择**: 支持用户在视频第一帧手动框选任意区域进行跟踪和匿名化。
- **高性能处理**:
  - 通过复用 Python 子进程和模型实例，避免重复加载开销。
  - 采用多线程流水线（Producer-Consumer 模式）并行处理视频帧，充分利用多核 CPU 资源。
- **硬件加速**: 支持使用 CUDA (NVIDIA GPU) 或 CPU 进行模型推理。
- **数据完整性**: 使用 HMAC 校验确保加密数据包在传输或存储过程中未被篡改。

## 🛠️ 技术栈

- **前端**: Electron, Vue 3, Vite, TypeScript
- **后端/计算**: Python
- **AI/ML**: PyTorch, Ultralytics YOLOv8
- **加密**: AES-256-GCM, HMAC

## 📋 前置要求

- Node.js 18+
- npm 9+
- Python 3.9+
- **NVIDIA GPU** (推荐，用于 CUDA 加速) 及对应的 CUDA Toolkit 和 cuDNN。

## 🚀 快速开始

**1. 安装前端依赖**

```powershell
npm install
```

**2. 安装 Python 依赖**

建议在虚拟环境中安装，以避免与系统环境冲突。

```powershell
# 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 安装依赖
pip install -r backend/requirements.txt
```
*注意：`requirements.txt` 中包含了 PyTorch (CPU版)。如果你的设备支持 CUDA，请根据你的 CUDA 版本从 [PyTorch 官网](https://pytorch.org/get-started/locally/) 获取对应的安装命令，以获得 GPU 加速能力。*

**3. 启动应用**

```powershell
# 启动 Electron + Vite 开发环境
npm run dev
```

## 📦 构建应用

```powershell
# 打包渲染进程与主进程代码
npm run build

# 可选：为当前平台打包安装包 (Windows)
npm run build:win
```

## 🏗️ 架构简介

本应用采用 Electron 作为主框架，负责 UI 展示和任务调度，同时将计算密集型任务分发给一个长期运行的 Python 子服务。

1.  **主进程 (Electron)**:
    -   创建和管理应用窗口 (`src/main/index.ts`)。
    -   响应 UI 事件，并通过 `ipcMain` 与渲染进程通信。
    -   在首次需要时，启动一个独立的 Python 服务进程 (`scripts/anonymize_service.py`)。

2.  **渲染进程 (Vue 3)**:
    -   构建用户界面 (`src/renderer`)，包括视频拖放区、参数设置和状态显示。
    -   将用户请求（如开始匿名化、取消任务）发送给主进程。

3.  **Python 服务 (`scripts/anonymize_service.py`)**:
    -   一个长期运行的进程，通过标准输入/输出（stdin/stdout）与 Electron 主进程进行 JSON-RPC 通信。
    -   在启动时加载 YOLOv8 模型，并将其保留在内存中，以处理后续的所有匿名化请求，避免了重复加载的性能损耗。
    -   接收到任务后，为每个任务创建一个独立的线程，并调用核心处理流水线。

4.  **视频处理流水线 (`scripts/video_pipeline.py`)**:
    -   采用多线程的生产者-消费者模型：
        -   **Producer**: 从视频文件中读取帧并放入队列。
        -   **Workers**: 从队列中获取帧，执行目标检测、ROI 加密和匿名化处理。支持多个 Worker 并行处理。
        -   **Consumer**: 从结果队列中获取处理后的帧，并将其写入新的视频文件。
    -   处理完成的元数据（如加密后的 ROI、密钥信息等）被写入一个 `.pack` 文件，用于后续的视频恢复。

