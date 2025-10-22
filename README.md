# 可逆视频匿名化工具

Electron + Vue 3 桌面应用的基础脚手架，预留 Python 计算后端的集成入口，用于后续实现可逆视频匿名化。

## 目录结构

- `src/main`：Electron 主进程代码。
- `src/preload`：在渲染进程和主进程之间暴露安全 API。
- `src/renderer`：Vue 3 + Vite 渲染进程项目。
- `backend`：Python 后端占位符（FastAPI 示例），用于部署深度学习推理与加密逻辑。

## 前置要求

- Node.js 18+
- npm 9+
- Python 3.9+
- NVIDIA CUDA 环境（待后续配置 PyTorch CUDA 版本）

## 快速开始

```powershell
# 安装前端依赖
npm install

# 启动 Electron + Vite 开发环境
npm run dev
```

## 构建应用

```powershell
# 打包渲染进程与主进程代码
npm run build

# 可选：为不同平台打包安装包
npm run build:mac
npm run build:linux
```

## Python 后端

```powershell
# 进入 backend 目录安装依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 启动占位 FastAPI 服务
python backend/server.py
```

前端可通过调用 `http://127.0.0.1:8000/health` 检查 Python 服务状态，后续可在此基础上扩展模型推理、CUDA 加速与密钥管理流程。
