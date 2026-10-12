; 积磊截图 Windows 安装器（NSIS 3 + Modern UI 2）
;
; 与积磊其它桌面端（dizhi-tool / Tauri NSIS）保持一致的做法：
; - 按「当前用户」安装（RequestExecutionLevel user），默认目录
;   %LOCALAPPDATA%\Programs\积磊截图，安装过程中不弹 UAC；
; - 用户在向导里可以自己改安装路径；
; - 之所以坚持装到用户可写目录：应用内自动更新（main/core/updater.py）是直接
;   改名替换 exe，装到 Program Files 会因为没权限而失败。
;
; 本脚本由 scripts/make_release_bundle.py 调用 makensis 编译：
; - 必须保存为 UTF-8 with BOM，NSIS 3 靠 BOM 判断脚本编码（构建脚本会兜底补 BOM）；
; - APP_VERSION / SOURCE_EXE / ICON_FILE / OUT_FILE 由 /D 传入，一律使用纯 ASCII
;   临时路径，避免中文命令行参数在不同代码页下被解析错。
; - SOURCE_EXE 传进来的是复制成 ASCII 名字的临时文件，所以这里必须用 /oname
;   指定安装后的真实文件名。

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

!define PRODUCT_NAME "积磊截图"
!define PRODUCT_EXE "积磊截图.exe"
!define PRODUCT_PUBLISHER "积磊软件"
!define PRODUCT_KEY "Software\积磊截图"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\积磊截图"
!define UNINST_EXE "uninstall.exe"
; 应用内更新下载/改名的临时文件（卸载时一并清掉）
!define UPDATE_LEFTOVER "积磊截图.new.exe"

Name "${PRODUCT_NAME} ${APP_VERSION}"
OutFile "${OUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\${PRODUCT_NAME}"
InstallDirRegKey HKCU "${PRODUCT_KEY}" "InstallDir"
RequestExecutionLevel user
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VI_VERSION}"
VIAddVersionKey "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey "FileDescription" "${PRODUCT_NAME} 安装程序"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "${PRODUCT_PUBLISHER}"

!define MUI_ABORTWARNING
!define MUI_ICON "${ICON_FILE}"
!define MUI_UNICON "${ICON_FILE}"
!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "立即运行 ${PRODUCT_NAME}"
!define MUI_FINISHPAGE_NOREBOOTSUPPORT
!define MUI_DIRECTORYPAGE_TEXT_TOP "选择 ${PRODUCT_NAME} 的安装位置。默认装在当前用户目录，不需要管理员权限；若改到 Program Files 这类受保护目录，写入会失败。"
!define MUI_COMPONENTSPAGE_SMALLDESC

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

LangString DESC_SecMain ${LANG_SIMPCHINESE} "安装 ${PRODUCT_NAME} 主程序与卸载程序（必需）。"
LangString DESC_SecDesktop ${LANG_SIMPCHINESE} "在桌面创建 ${PRODUCT_NAME} 快捷方式。"
LangString DESC_SecMain ${LANG_ENGLISH} "Install the ${PRODUCT_NAME} application and uninstaller (required)."
LangString DESC_SecDesktop ${LANG_ENGLISH} "Create a desktop shortcut for ${PRODUCT_NAME}."

; ---------------------------------------------------------------- 安装
Section "主程序" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"

  ; 运行中的 exe 无法被替换：先试删一次，删不掉说明程序还在跑（Delete 对不存在的
  ; 文件不会置错误标志，所以首次安装不会被误判）。这里必须用显式标签，别用
  ; IfErrors 的相对跳转写法——写错偏移会把下面的 File 整条跳过。
  ClearErrors
  Delete "$INSTDIR\${PRODUCT_EXE}"
  IfErrors app_running
  Goto app_closed
app_running:
  MessageBox MB_ICONSTOP|MB_OK "检测到 ${PRODUCT_NAME} 正在运行。$\r$\n请在托盘图标上右键选择退出，然后重新安装。"
  Abort
app_closed:

  File "/oname=${PRODUCT_EXE}" "${SOURCE_EXE}"

  ; 应用内更新留下的残留文件
  Delete "$INSTDIR\${PRODUCT_EXE}.old"
  Delete "$INSTDIR\${UPDATE_LEFTOVER}"

  WriteUninstaller "$INSTDIR\${UNINST_EXE}"

  ; 开始菜单（程序 + 卸载）
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
  CreateShortCut "$SMPROGRAMS\${PRODUCT_NAME}\卸载 ${PRODUCT_NAME}.lnk" "$INSTDIR\${UNINST_EXE}"

  ; 控制面板「应用和功能」入口
  WriteRegStr HKCU "${PRODUCT_KEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_EXE}"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\${UNINST_EXE}"'
  WriteRegStr HKCU "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\${UNINST_EXE}" /S'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

Section "创建桌面快捷方式" SecDesktop
  CreateShortCut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} $(DESC_SecMain)
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} $(DESC_SecDesktop)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ---------------------------------------------------------------- 卸载
Section "Uninstall"
  ClearErrors
  Delete "$INSTDIR\${PRODUCT_EXE}"
  IfErrors app_running_uninst
  Goto app_closed_uninst
app_running_uninst:
  MessageBox MB_ICONSTOP|MB_OK "检测到 ${PRODUCT_NAME} 正在运行。$\r$\n请在托盘图标上右键选择退出，然后重新卸载。"
  Abort
app_closed_uninst:

  Delete "$INSTDIR\${PRODUCT_EXE}.old"
  Delete "$INSTDIR\${UPDATE_LEFTOVER}"
  Delete "$INSTDIR\${UNINST_EXE}"
  RMDir "$INSTDIR"

  Delete "$SMPROGRAMS\${PRODUCT_NAME}\*.lnk"
  RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegKey HKCU "${PRODUCT_KEY}"

  ; 用户数据（设置、截图历史、剪贴板历史）保留在 %LOCALAPPDATA%\JileiScreenshot，
  ; 卸载不删除，避免误删用户自己的截图与记录。
SectionEnd
