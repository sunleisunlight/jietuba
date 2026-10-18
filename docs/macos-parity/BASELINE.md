# Windows 基线与入口真源

## 2026-10-19 只读核实

- 已执行 `git fetch origin`，退出码0。
- `origin/main`、annotated `v2.7.0^{}` 均为 `a26380ea80f73af029e7fc5f0ada65584fa1ef92`；提交日期2026-10-17 11:38:20 +0800；APP_VERSION=2.7.0。
- 新功能为选中元素改色、Delete/Backspace删除、剪贴板分组拖拽排序。任务2负责前两项，任务3负责分组排序。
- Mac旧版tag `v2.8.1^{}` 为 `cf920da1d59205cafbf631fe6a0a02552d697b39`。任务起点 `c788d1925cd36dde6e55bd21a6af3ad51be97f81` 在其上增加任务文档。**v2.8.1不是Windows正式基线。**
- `gh release list --limit 4` 无发布条目。控制中心公开更新接口只读请求：cc.sunget.top TLS连接失败，cc.jilei.cc HTTP502。未访问管理端、未改线上数据。
- 基线CI run `39141051593`，SHA a26380e，x64 lint失败，真实Windows构建步骤被跳过；arm64检查时仍在测试。Rust Wheels run `39141051600` 成功只证明wheel，不是exe。
- 因此：最新源码基线已确定；正式exe及线上版本来源**待核验**。不把提交信息当作软件发布/构建证据。

## 品牌真源

| 资源 | 来源/处理 | SHA-256 |
|---|---|---|
| 托盘.ico | Windows基线与当前文件逐字节相同 | bbb64022ed9226e3d114538c2136a1f2bcc2337c249e328bc76a0b4be61bbe9c |
| svg/托盘.svg | Windows基线与当前文件逐字节相同 | cf4566599f0b92d26d8ab0a3489ea266966ca4e54948cd84e98bb2d0330653f3 |
| assets/JileiScreenshot.icns | build_macos.py：Pillow选ICO最大图层，Lanczos各尺寸，iconutil生成；未新设计Logo | 1409a80f87427af54b1d7b38addd434fadcebe14a813d5b5f5c74cd50596250e |

保留 `cc.jilei.jileiscreenshot` Bundle ID、`JileiScreenshot` 可执行名与QSettings组织域；用户可见名称为「积磊截图」。未清空/迁走用户配置、历史或旧发布包。

## 入口发现与复核边界

通过实际启动链、托盘、设置、欢迎页、工具栏及其布局、工具默认参数、全局/应用内快捷键、钉图和剪贴板右键、GIF/长截图工具栏、测试进行发现。调用链地图先用graphify定位bootstrap/MainApp/SettingsDialog，再按本轮源码核实，不采用旧图谱行号替代代码。

`inventory.py <SHA>` 只读提取固定基线667条候选：入口标签、点击/触发绑定、工具设置、应用设置、工具快捷键。结果展开在FEATURE_MATRIX.md，另有33条任务1实际验收操作，共700行。数据驱动入口、同动作的多个入口和仅Mac可见的权限页需要区分；当前没有Windows交互环境，**可见性与清单独立复核尚未完成**，不能宣称已经证明没有遗漏。

主要源码真源：

- 启动：main/main_app.py → main/core/bootstrap.py → main/ui/welcome/wizard.py / main/ui/settings_ui/dialog.py / main/ui/tray_menu.py。
- 截图/编辑：main/ui/toolbar.py、toolbar_layout.py、main/canvas/、main/tools/、main/ui/*settings_panel.py、main/ui/selection_info/。
- 参数/快捷键：main/settings/tool_settings.py（工具默认项、应用默认项、11+1工具键、截图动作键）与main/core/shortcut_manager.py。
- 日常操作：main/clipboard/ui/menus/、main/clipboard/controllers/context_menu_controller.py、main/pin/pin_context_menu.py、main/pin/pin_toolbar.py、main/translation/、main/ocr/、main/barcode/。
- 复杂捕获：main/stitch/scroll_toolbar.py；main/gif/record_toolbar.py、playback_toolbar.py、drawing_toolbar.py。
- 账号、更新、迁移、完整安装/升级验收归任务5；不能将功能入口存在当作功能已实现。

后续每轮fetch后在此追加基线变化；未发布开发变更不得无界替换稳定功能基线。
