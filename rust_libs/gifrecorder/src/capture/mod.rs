//! 平台分派：Windows → BitBlt，macOS → ScreenCaptureKit（ObjC shim）。
//!
//! 上层（recorder.rs / Python）只依赖统一的 `ScreenCapture` 接口：
//!   new(left, top, width, height) -> Result<Self, String>
//!   grab(&mut self) -> Result<&[u8], String>   （BGRA，top-down）
//!   width() / height()

#[cfg(target_os = "windows")]
mod windows;
#[cfg(target_os = "windows")]
pub(crate) use windows::ScreenCapture;

#[cfg(target_os = "macos")]
mod macos;
#[cfg(target_os = "macos")]
pub(crate) use macos::ScreenCapture;
