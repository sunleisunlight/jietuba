# 任务3：日常系统功能对齐

状态：进行中；候选 2.10.0，尚未封版。2026-10-19（Asia/Shanghai）。

工作目录 `/Users/sunlei/codex/jietuba`；分支 `fix/macos-native-parity`，不合并 main。
本轮起点 c6b070ed98b27f788230347e6644be34c0173d92。
Windows 稳定基线 v2.8.0 / 7c0d289475ee630a4102f2b7e36b9aa8e49bb54c；fetch 后无新增远端变化。

## 已开发

- 统一平台快捷键约定，Mac 录入/加载/菜单显示 Command，Windows 保持 Ctrl；Mac 物理 Control 单独保存 lctrl，Option 保持 alt。配置按可移植 token 保存。
- 修复应用内 Meta/Control 丢失、半截组合键释放、已注册全局键在录入时按 Win32 位误解码；Carbon 临时注册探测占用后释放。
- 安全吸收 Windows 2.8.0 共享剪贴板顶部搜索、图片 OCR 索引/历史补录、四档预览及 Rust 数据库迁移。不覆盖版本和启动修复。
- OCR 失败不写成已完成空结果；队列加锁；移除识别文字日志，避免记录个人剪贴板内容。
- 自动粘贴目标不存在/本应用/焦点超时，停止且提示；不再向未知前台盲发。
- 修复任务2物理像素画布与 CG/AX 逻辑点智能选区错位；排除自身窗口；AX 仅扫描匹配目标窗口。

## 测试与候选构建

项目 Python3.11.16、Qt6.8.3、macOS arm64，QT_QPA_PLATFORM=cocoa。
本轮测试分批运行于 build/task3-*.log，各失败及修复保留，不删除旧结果。
19模块定向门禁已通过（build/task3-gate.log），另行回归显示/智能选区修改。
Rust pyclipboard 6项通过；maturin 原生 wheel 已重新构建安装到项目 venv。
真实候选 App 已由 build_macos.py 构建成功，资源/架构/模型/四原生库和 codesign 校验通过。
此处尚不代表真实 App、Windows 原生门禁或公开分发通过；四件套和最终证据待追加。

## 待完成/外部限制

本轮 Windows 精确 SHA 测试和真实 exe 构建、最新 App 安装及真实操作证据待执行。
Developer ID、公证、Windows 交互环境、鼠标侧键实体设备、混合DPR和最低系统环境不足，分别记录，不冒充通过。
翻译仅做离线契约，不使用真实用户密钥或计费服务。任务4/5不在本轮执行。
