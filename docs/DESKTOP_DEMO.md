# Desktop Demo

这是一个最小可用的桌面 demo，目标是复用当前网页端效果，而不是先做完整安装包。

## 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-desktop.txt
```

## 启动公开页

```bash
.venv/bin/python -m desktop.app
```

## 启动管理页

```bash
.venv/bin/python -m desktop.app --admin
```

## 调试模式

```bash
.venv/bin/python -m desktop.app --debug
```

## 浏览器降级

如果本机缺少 WebView 运行环境，可以先用浏览器降级模式确认流程：

```bash
.venv/bin/python -m desktop.app --browser-fallback
```

## 当前行为

- 启动一个本地 FastAPI 服务
- 自动选择空闲 localhost 端口
- 用桌面 WebView 打开 `/` 或 `/admin`
- 关闭窗口后自动关闭本地服务

## 说明

这只是桌面 demo：

- 还没有图标、安装包、菜单栏、托盘
- 还没有把配置/历史目录迁移到系统用户目录
- 还没有去掉网页端的线上字体 / Tailwind 依赖

这些会在后续正式客户端阶段处理。
