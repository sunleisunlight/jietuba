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

## 继续执行任务1：动态菜单复核

- 再次fetch，origin/main与固定基线一致。
- 人工追踪 `clipboard/ui/menus/{item_context_menu,group_context_menu,action_menu}.py` → `clipboard/controllers/context_menu_controller.py`，确认这些文件与a26380e无差异。
- 原AST候选只扫描UI等目录，没有扫描controller，因此会漏掉由MenuAction规则动态生成的菜单。已在矩阵新增DYN-CB-01～29：内容粘贴/复制、12个特殊粘贴子动作、图片钉图/保存、置顶/取消、文件位置、动态分组迁移/移除、组内编辑/排序/删除以及分组编辑/排序/删除。各项保留类型、分组和边界条件，不计分隔线为功能。
- `main/pin/pin_context_menu.py`也与基线一致：缩略模式隐藏翻译、原尺寸、图像变换、工具栏、阴影与文字选择；复制、保存、置顶、缩略切换和关闭仍可用。任务3应按这两种状态复核既有WIN候选行，不能只测试普通钉图。
- `main/ui/toolbar_layout.py`与基线一致：23个可配置/固定按钮，默认全部显示；confirm固定显示且不可调整，其余可排序、收入更多或隐藏，隐藏按钮的快捷键仍有效。任务2需覆盖动态排布，不将用户配置隐藏误认为Mac删功能。
- 本轮仅做任务1清单发现，没有提前执行任务2/3功能测试。累计729行：33任务1操作、29动态菜单补充、667源码候选。仍不宣称清单已穷尽Windows可见功能。

## 2026-10-19 05:28：正式Windows基线更正为2.8.0

- 重新请求公开更新接口 `https://cc.jilei.cc/updates/jilei-screenshot/stable/windows/x86_64/2.6.0` 返回HTTP200：version=2.8.0，pub_date=2026-10-18T18:54:09.114961+00:00（北京时间10月19日02:54）。另一域名cc.sunget.top仍TLS失败。
- 远端annotated Tag v2.8.0对象a78cc98935fbc4597751e05873cd1dfb6a30525b，peeled提交7c0d289475ee630a4102f2b7e36b9aa8e49bb54c，APP_VERSION=2.8.0；origin/feature/jilei-account也指向该提交。origin/main仍为a26380e，不能再以main代表最新正式Windows版本。
- 清单artifact大小70,483,525字节，SHA256为867e7a10492b03af2c13ec0d6c902b66ea0ef3f1046da89d940bac25db68908f。下载地址由上述HTTPS清单给出，暂存为build/task1-windows-v2.8.0.exe；下载及实际哈希核验见后续证据。Tag版本和发布说明吻合，但没有exe构建manifest/该SHA的CI运行记录，不冒称已证明exe的精确源码SHA。
- v2.8.0在a26380e上新增剪贴板顶部搜索、截图OCR可搜索（含历史补录）、预览小/中/大/特大四档。候选Mac分支与其merge-base仍为a26380e，未包含该提交。矩阵WIN280-1～8登记新增/变更操作；任务3须安全吸收共享Python/Rust实现并回归任务1，不可覆盖APP_VERSION、启动生命周期修复，不在任务1盲目合并。
- 旧667条候选保留a26380e来源行号供追溯，后续按新基线复核；动态菜单已核对未受v2.8.0改动。另补充7条Qt通用编辑菜单操作DYN-EDIT-1～7。当前合计744行，不以数量宣称穷尽。
