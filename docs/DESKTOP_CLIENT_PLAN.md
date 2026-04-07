# Daily Recommender Desktop 客户端计划

目标：在保留当前网页端视觉与交互效果的前提下，交付可打包的 macOS / Windows 客户端。

## 1. 当前代码现状

当前项目已经具备一套可以直接复用的 Web 架构：

- `web_server.py`
  - FastAPI 提供 API、WebSocket、公开页 `/`、管理页 `/admin`
- `public-web-ui.html`
  - 面向终端用户的网页首页
- `web-ui.html`
  - 管理后台
- `main.py`
  - 真正执行 GitHub / HuggingFace / X 抓取、LLM 评估、发信流程

这意味着桌面端不应该重写一套 UI，而应该尽量复用：

1. 现有 HTML / CSS / JS
2. 现有 FastAPI 接口
3. 现有 Python 主流程

## 2. 推荐技术路线

推荐第一阶段采用：

- `PyWebView` 作为桌面壳
- `FastAPI + Uvicorn` 继续作为本地服务
- `PyInstaller` 负责 macOS / Windows 打包

不建议第一阶段直接上 Electron / Tauri，原因：

- 当前仓库是纯 Python 项目，没有 Node / Rust 工具链
- 网页端已经是静态 HTML + FastAPI，PyWebView 复用成本最低
- Electron / Tauri 仍然需要额外管理 Python 子进程，整体复杂度更高
- 现阶段目标是“先复现网页端效果”，不是做重型原生客户端

## 3. 桌面端目标形态

客户端启动后行为：

1. 桌面 App 启动本地 FastAPI 服务
2. 自动选择一个空闲 localhost 端口
3. 打开内嵌 WebView，加载 `http://127.0.0.1:<port>/`
4. 默认展示公开页
5. 用户可进入管理页 `/admin`
6. 关闭 App 时同时关闭本地服务

这样可以最大限度复用现有网页端外观与逻辑。

## 4. 必须先处理的技术问题

### 4.1 配置与历史目录不能再写项目根目录

当前 `web_server.py` 使用项目根目录下这些文件：

- `.web_config.json`
- `.env`
- `profiles/description.txt`
- `profiles/researcher_profile.md`
- `profiles/x_accounts.txt`
- `history/`

这在桌面安装场景下是有问题的：

- macOS `.app` 内部通常不应写入
- Windows 安装到 `Program Files` 时通常是只读或受限写入

因此桌面端必须把“用户可写数据”迁移到系统用户目录：

- macOS：`~/Library/Application Support/DailyRecommender/`
- Windows：`%AppData%/DailyRecommender/`

需要新增统一的 `APP_DATA_DIR` 概念，替代当前直接写 `PROJECT_ROOT`。

### 4.2 前端 CDN 资源需要本地化

当前 `public-web-ui.html` 依赖：

- Tailwind CDN
- Google Fonts

桌面客户端如果要稳定、可离线启动，不能依赖线上资源。

因此需要：

1. 把 Tailwind 样式构建成本地静态 CSS
2. 把字体改成本地资源或系统字体栈
3. 确保所有前端资源都能随安装包一起分发

### 4.3 桌面端不能假设固定端口

当前 Web 版默认跑 `8080`。桌面端不应绑定固定端口，否则容易与本机已有服务冲突。

需要：

1. 启动时探测空闲端口
2. 桌面壳把实际端口传给内嵌浏览器
3. 健康检查成功后再打开窗口

### 4.4 启动与关闭要可控

桌面端需要保证：

- 后端启动失败时能弹出错误，而不是白屏
- 用户关闭窗口时，后台进程能正常退出
- 日志需要有本地文件落盘，方便排查 SMTP / API / 网络错误

## 5. 推荐目录结构

建议新增：

```text
desktop/
├── app.py                 # 桌面端主入口
├── server.py              # 启动/关闭 FastAPI，本地端口管理
├── paths.py               # 统一管理 app data 路径
├── packaging/
│   ├── pyinstaller-mac.spec
│   └── pyinstaller-win.spec
└── assets/
    ├── icon.icns
    ├── icon.ico
    └── splash.png
```

建议新增：

- `requirements-desktop.txt`
  - `pywebview`
  - `pyinstaller`

## 6. 分阶段实施计划

### Phase 0：把 Web 版改造成“可嵌入桌面端”

目标：先让当前网页代码不依赖“在线资源 + 项目根目录写入”。

任务：

1. 抽出统一的数据目录配置
2. 把 `web_server.py`、`main.py`、历史输出目录改成可切换的 app data 路径
3. 去掉前端 CDN 依赖，改为本地静态资源
4. 确认 `public-web-ui.html` 和 `/admin` 都能在离线环境运行

交付标准：

- 在本地断网时仍可打开 UI
- 配置和历史结果不再写仓库目录

### Phase 1：做最小可用桌面客户端

目标：能在 macOS / Windows 启动一个桌面窗口，复现网页端效果。

任务：

1. 新建 `desktop/app.py`
2. 启动本地 Uvicorn 服务
3. 自动探测空闲端口
4. 用 PyWebView 打开公开页 `/`
5. 增加窗口关闭时的后端清理逻辑
6. 增加启动失败错误提示

交付标准：

- 本机可直接运行桌面客户端
- 页面效果与网页端一致
- 支持进入 `/admin`

### Phase 2：补齐桌面端体验

目标：让桌面端不仅能打开，而且像一个真正的软件。

任务：

1. 增加菜单项：公开页、管理页、打开数据目录、查看日志
2. 增加系统托盘或菜单栏入口
3. 增加“服务启动中 / 启动失败”状态页
4. 增加日志文件落盘
5. 增加首启引导

交付标准：

- 用户不需要终端即可使用
- 启动、报错、关闭行为稳定

### Phase 3：跨平台打包

目标：产出可分发的安装包。

任务：

1. macOS：生成 `.app`
2. Windows：生成 `.exe` 或安装包
3. 打包静态资源、HTML、图标、后端代码
4. 验证 WebView 依赖
   - Windows 需要确认 WebView2
5. 形成构建脚本和发布说明

交付标准：

- macOS 可直接双击运行
- Windows 可直接启动
- 不依赖开发环境目录

## 7. 风险点

### 7.1 Windows WebView2 依赖

PyWebView 在 Windows 通常依赖 Edge WebView2。需要确认：

- 用户系统是否已有 WebView2
- 如果没有，是否在安装器中提示或打包引导

### 7.2 写权限问题

只要还有任何代码写回仓库目录，打包后都可能出问题。这个必须在 Phase 0 彻底清掉。

### 7.3 前端资源在线依赖

如果还保留 Google Fonts / Tailwind CDN，桌面端首次打开就可能变慢、失败或样式错乱。

### 7.4 本地服务生命周期

如果 Uvicorn 没有被正确关闭，客户端退出后可能残留后台进程。

## 8. 建议的实施顺序

建议按下面顺序做，而不是直接先上桌面壳：

1. 先完成 Phase 0：清理路径和前端静态依赖
2. 再完成 Phase 1：做 PyWebView 最小桌面壳
3. 然后做 Phase 2：桌面体验补齐
4. 最后做 Phase 3：macOS / Windows 打包

## 9. 结论

从当前代码出发，最快、最稳妥的路线不是重写客户端，而是：

`现有 FastAPI + 现有 HTML 页面 + PyWebView 桌面壳 + PyInstaller 打包`

这样可以：

- 最大化复用网页端效果
- 保持 Python 主流程不动
- 最快拿到 macOS / Windows 可运行版本

下一步建议直接开始做 `Phase 0`。
