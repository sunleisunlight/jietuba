//! macOS 屏幕截取 — ScreenCaptureKit（通过薄 ObjC shim 桥接）。
//!
//! shim（native/sck_capture.m）只负责 SCK → 紧凑 BGRA 帧回调；
//! 所有 GIF 编码 / 帧存储 / 时间轴逻辑仍在 Rust / Python 侧。
//!
//! 注意：帧坐标使用 CG 全局显示坐标（物理像素）；区域必须落在单个
//! 显示器内（跨屏区域会被 clamp 到所在显示器）。

use std::ffi::c_void;
use std::sync::mpsc::{sync_channel, Receiver, SyncSender, TryRecvError};
use std::time::Duration;

extern "C" {
    fn JTKStartCapture(
        x: i32,
        y: i32,
        w: i32,
        h: i32,
        fps: f64,
        cb: extern "C" fn(*mut c_void, *const u8, usize),
        ctx: *mut c_void,
    ) -> *mut c_void;
    fn JTKStopCapture(handle: *mut c_void);
}

/// 帧回调（在 shim 的 dispatch queue 线程执行）。
/// ctx = Box::into_raw(Box::new(SyncSender<Vec<u8>>))（泄漏，会话级）。
extern "C" fn on_frame(ctx: *mut c_void, data: *const u8, len: usize) {
    let sender: &SyncSender<Vec<u8>> = unsafe { &*(ctx as *const SyncSender<Vec<u8>>) };
    if len == 0 || data.is_null() {
        return;
    }
    let mut frame = Vec::with_capacity(len);
    unsafe {
        frame.set_len(len);
        std::ptr::copy_nonoverlapping(data, frame.as_mut_ptr(), len);
    }
    // 只保留最新一帧；满了说明消费慢，丢弃本次
    let _ = sender.try_send(frame);
}

pub(crate) struct ScreenCapture {
    handle: *mut c_void,
    rx: Receiver<Vec<u8>>,
    last: Option<Vec<u8>>,
    width: i32,
    height: i32,
}

unsafe impl Send for ScreenCapture {}

impl ScreenCapture {
    /// 创建截屏上下文（区域为 CG 全局显示坐标）。
    pub fn new(left: i32, top: i32, width: i32, height: i32) -> Result<Self, String> {
        if width <= 0 || height <= 0 {
            return Err(format!("invalid capture size: {width}x{height}"));
        }
        let (tx, rx) = sync_channel::<Vec<u8>>(1);
        let ctx = Box::into_raw(Box::new(tx));
        let handle = unsafe {
            JTKStartCapture(
                left, top, width, height, 15.0, on_frame, ctx as *mut c_void,
            )
        };
        if handle.is_null() {
            unsafe {
                drop(Box::from_raw(ctx));
            }
            return Err(
                "ScreenCaptureKit start failed (screen recording permission not granted?)".into(),
            );
        }
        Ok(Self {
            handle,
            rx,
            last: None,
            width,
            height,
        })
    }

    /// 截取一帧，返回 BGRA（top-down，紧凑无 padding）。
    ///
    /// ScreenCaptureKit 是事件驱动：画面静止时送帧频率远低于目标 fps。
    /// 为保证录制帧率由 recorder 的 fps 节拍决定（与 Windows BitBlt 轮询
    /// 一致），本方法非阻塞：有新帧取最新，无新帧复用上一帧；仅首帧
    /// 会阻塞等待（启动阶段）。
    pub fn grab(&mut self) -> Result<&[u8], String> {
        // 丢弃排队旧帧，取最新
        loop {
            match self.rx.try_recv() {
                Ok(frame) => self.last = Some(frame),
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    return Err("capture stream disconnected".into());
                }
            }
        }
        match self.rx.try_recv() {
            Ok(frame) => {
                self.last = Some(frame);
                Ok(self.last.as_ref().unwrap())
            }
            Err(TryRecvError::Disconnected) => {
                Err("capture stream disconnected".into())
            }
            Err(TryRecvError::Empty) => {
                if self.last.is_some() {
                    Ok(self.last.as_ref().unwrap())
                } else if let Ok(frame) =
                    self.rx.recv_timeout(Duration::from_millis(3000))
                {
                    self.last = Some(frame);
                    Ok(self.last.as_ref().unwrap())
                } else {
                    Err("no frame within timeout (permission not granted?)".into())
                }
            }
        }
    }

    pub fn width(&self) -> u32 {
        self.width as u32
    }

    pub fn height(&self) -> u32 {
        self.height as u32
    }
}

impl Drop for ScreenCapture {
    fn drop(&mut self) {
        unsafe {
            JTKStopCapture(self.handle);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grab_keeps_newest_queued_frame_and_reuses_it_when_idle() {
        let (tx, rx) = sync_channel(2);
        let mut capture = ScreenCapture {
            handle: std::ptr::null_mut(),
            rx,
            last: Some(vec![0; 4]),
            width: 1,
            height: 1,
        };
        tx.send(vec![1; 4]).unwrap();
        tx.send(vec![2; 4]).unwrap();
        assert_eq!(capture.grab().unwrap(), &[2; 4]);
        assert_eq!(capture.grab().unwrap(), &[2; 4]);
        tx.send(vec![3; 4]).unwrap();
        assert_eq!(capture.grab().unwrap(), &[3; 4]);
    }
}
