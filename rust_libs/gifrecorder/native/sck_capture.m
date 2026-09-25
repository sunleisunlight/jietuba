#import <Foundation/Foundation.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <CoreVideo/CoreVideo.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreGraphics/CoreGraphics.h>
#include <stdint.h>
#include <stddef.h>

// gifrecorder macOS 录屏 shim（只负责 ScreenCaptureKit → BGRA 帧）
// Rust 侧通过 extern "C" 调用；帧数据逐帧回调给 Rust。

typedef void (*JTKFrameCallback)(void *ctx, const uint8_t *data, size_t len);

@interface JTKStreamDelegate : NSObject <SCStreamOutput, SCStreamDelegate>
@property (nonatomic, assign) JTKFrameCallback callback;
@property (nonatomic) void *ctx;
@property (nonatomic, strong) SCStream *stream;
@end

@implementation JTKStreamDelegate

- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
                                               ofType:(SCStreamOutputType)type {
    if (type != SCStreamOutputTypeScreen) return;
    CVImageBufferRef imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (imageBuffer == NULL) return;
    CVPixelBufferLockBaseAddress(imageBuffer, kCVPixelBufferLock_ReadOnly);
    size_t width = CVPixelBufferGetWidth(imageBuffer);
    size_t height = CVPixelBufferGetHeight(imageBuffer);
    size_t rowBytes = CVPixelBufferGetBytesPerRow(imageBuffer);
    uint8_t *base = (uint8_t *)CVPixelBufferGetBaseAddress(imageBuffer);
    if (base != NULL && self.callback != NULL) {
        size_t tight = width * 4;
        size_t total = tight * height;
        if (rowBytes == tight) {
            self.callback(self.ctx, base, total);
        } else {
            // 去除行 padding，输出紧凑 BGRA
            uint8_t *buf = malloc(total);
            if (buf != NULL) {
                for (size_t r = 0; r < height; r++) {
                    memcpy(buf + r * tight, base + r * rowBytes, tight);
                }
                self.callback(self.ctx, buf, total);
                free(buf);
            }
        }
    }
    CVPixelBufferUnlockBaseAddress(imageBuffer, kCVPixelBufferLock_ReadOnly);
}

- (void)stream:(SCStream *)stream didStopWithError:(NSError *)error {
    NSLog(@"[gifrecorder-sck] stream stopped: %@", error);
}

@end

// 启动区域录屏；区域 (x,y,w,h) 为全局显示坐标（CG 同系）。
// 返回 opaque handle（失败返回 NULL）。
void *JTKStartCapture(int x, int y, int w, int h, double fps,
                      JTKFrameCallback cb, void *ctx) {
    if (w <= 0 || h <= 0 || cb == NULL) return NULL;
    JTKStreamDelegate *delegate = [[JTKStreamDelegate alloc] init];
    delegate.callback = cb;
    delegate.ctx = ctx;
    __block SCStream *stream = nil;
    __block dispatch_semaphore_t sem = dispatch_semaphore_create(0);

    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        [SCShareableContent getShareableContentWithCompletionHandler:^(
            SCShareableContent *content, NSError *err) {
            if (content == nil || err != nil) {
                NSLog(@"[gifrecorder-sck] no shareable content: %@", err);
                dispatch_semaphore_signal(sem);
                return;
            }
            SCDisplay *target = nil;
            for (SCDisplay *d in content.displays) {
                if (CGRectContainsPoint(d.frame, CGPointMake(x, y))) {
                    target = d;
                    break;
                }
            }
            if (target == nil) {
                NSLog(@"[gifrecorder-sck] no display contains (%d,%d)", x, y);
                dispatch_semaphore_signal(sem);
                return;
            }
            CGRect df = target.frame;
            CGRect src = CGRectMake(x - df.origin.x, y - df.origin.y, w, h);
            CGRect inter = CGRectIntersection(src,
                CGRectMake(0, 0, df.size.width, df.size.height));
            if (inter.size.width < 1 || inter.size.height < 1) {
                dispatch_semaphore_signal(sem);
                return;
            }
            SCStreamConfiguration *conf = [[SCStreamConfiguration alloc] init];
            conf.width = (NSInteger)inter.size.width;
            conf.height = (NSInteger)inter.size.height;
            conf.sourceRect = inter;
            double f = fps > 1.0 ? fps : 15.0;
            conf.minimumFrameInterval = CMTimeMake(1, (int32_t)f);
            conf.pixelFormat = kCVPixelFormatType_32BGRA;
            conf.showsCursor = NO;
            conf.queueDepth = 2;
            conf.captureResolution = SCCaptureResolutionBest;
            SCContentFilter *filter =
                [[SCContentFilter alloc] initWithDisplay:target excludingWindows:@[]];
            stream = [[SCStream alloc] initWithFilter:filter
                                        configuration:conf
                                             delegate:delegate];
            delegate.stream = stream;
            NSError *addErr = nil;
            BOOL added = [stream addStreamOutput:delegate
                                            type:SCStreamOutputTypeScreen
                               sampleHandlerQueue:dispatch_get_global_queue(
                                   QOS_CLASS_USER_INITIATED, 0)
                                             error:&addErr];
            if (!added) {
                NSLog(@"[gifrecorder-sck] addStreamOutput failed: %@", addErr);
                dispatch_semaphore_signal(sem);
                return;
            }
            [stream startCaptureWithCompletionHandler:^(NSError *err2) {
                if (err2 != nil) {
                    NSLog(@"[gifrecorder-sck] start error: %@", err2);
                }
                dispatch_semaphore_signal(sem);
            }];
        }];
    });

    long waited = dispatch_semaphore_wait(
        sem, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));
    if (waited != 0 || stream == nil) {
        return NULL;
    }
    return (void *)CFBridgingRetain(delegate);
}

void JTKStopCapture(void *handle) {
    if (handle == NULL) return;
    JTKStreamDelegate *delegate = (__bridge JTKStreamDelegate *)handle;
    SCStream *stream = delegate.stream;
    if (stream != nil) {
        [stream stopCaptureWithCompletionHandler:nil];
    }
    // 延迟释放，避免 stop 异步回调期间 delegate 已被释放
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)),
                   dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        CFRelease(handle);
    });
}
