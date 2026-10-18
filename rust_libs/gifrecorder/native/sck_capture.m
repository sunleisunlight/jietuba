#import <Foundation/Foundation.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <CoreVideo/CoreVideo.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreGraphics/CoreGraphics.h>
#include <stdint.h>
#include <stddef.h>
#include <unistd.h>

// gifrecorder macOS 录屏 shim（只负责 ScreenCaptureKit → BGRA 帧）
// Rust 侧通过 extern "C" 调用；帧数据逐帧回调给 Rust。

typedef void (*JTKFrameCallback)(void *ctx, const uint8_t *data, size_t len);
typedef void (*JTKContextRelease)(void *ctx);

@interface JTKStreamDelegate : NSObject <SCStreamOutput, SCStreamDelegate>
@property (nonatomic, assign) JTKFrameCallback callback;
@property (nonatomic) void *ctx;
@property (nonatomic, assign) JTKContextRelease releaseContext;
@property (nonatomic, strong) SCStream *stream;
@property (nonatomic) BOOL cancelled;
@property (nonatomic) BOOL started;
@property (nonatomic) size_t width;
@property (nonatomic) size_t height;
- (void)cancel;
@end

@implementation JTKStreamDelegate

- (void)dealloc {
    // Rust context 的所有权随 delegate。包括启动超时后的迟到回调，均不会
    // 在 Rust 先释放 sender 后再使用它，也不再每次录制泄漏一个 Box。
    if (_releaseContext != NULL && _ctx != NULL) _releaseContext(_ctx);
}

- (void)cancel {
    @synchronized (self) {
        self.cancelled = YES;
        self.callback = NULL;
        SCStream *stream = self.stream;
        self.stream = nil;
        if (stream != nil) {
            [stream stopCaptureWithCompletionHandler:^(NSError *error) {
                NSError *removeError = nil;
                [stream removeStreamOutput:self type:SCStreamOutputTypeScreen error:&removeError];
            }];
        }
    }
}

- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
                                               ofType:(SCStreamOutputType)type {
    if (type != SCStreamOutputTypeScreen) return;
    if (!CMSampleBufferIsValid(sampleBuffer)) return;
    NSArray *attachments = (__bridge NSArray *)CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, NO);
    NSNumber *status = attachments.firstObject[SCStreamFrameInfoStatus];
    if (status == nil || status.integerValue != SCFrameStatusComplete) return;
    CVImageBufferRef imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (imageBuffer == NULL) return;
    CVPixelBufferLockBaseAddress(imageBuffer, kCVPixelBufferLock_ReadOnly);
    size_t width = CVPixelBufferGetWidth(imageBuffer);
    size_t height = CVPixelBufferGetHeight(imageBuffer);
    size_t rowBytes = CVPixelBufferGetBytesPerRow(imageBuffer);
    uint8_t *base = (uint8_t *)CVPixelBufferGetBaseAddress(imageBuffer);
    @synchronized (self) {
    if (base != NULL && !self.cancelled && self.callback != NULL &&
        width == self.width && height == self.height) {
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
    }
    CVPixelBufferUnlockBaseAddress(imageBuffer, kCVPixelBufferLock_ReadOnly);
}

- (void)stream:(SCStream *)stream didStopWithError:(NSError *)error {
    NSLog(@"[gifrecorder-sck] stream stopped: %@", error);
    [self cancel];
}

@end

// 启动区域录屏；区域 (x,y,w,h) 为全局显示坐标（CG 同系）。
// 返回 opaque handle（失败返回 NULL）。
void *JTKStartCapture(int x, int y, int w, int h, double fps,
                      JTKFrameCallback cb, void *ctx, JTKContextRelease releaseContext) {
    if (w <= 0 || h <= 0 || cb == NULL) {
        if (releaseContext != NULL) releaseContext(ctx);
        return NULL;
    }
    JTKStreamDelegate *delegate = [[JTKStreamDelegate alloc] init];
    delegate.callback = cb;
    delegate.ctx = ctx;
    delegate.releaseContext = releaseContext;
    delegate.width = (size_t)w;
    delegate.height = (size_t)h;
    __block SCStream *stream = nil;
    __block dispatch_semaphore_t sem = dispatch_semaphore_create(0);

    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        [SCShareableContent getShareableContentWithCompletionHandler:^(
            SCShareableContent *content, NSError *err) {
            @synchronized (delegate) {
            if (delegate.cancelled) {
                dispatch_semaphore_signal(sem);
                return;
            }
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
            // Rust 编码器必须收到 w*h*4 字节；不能静默裁小后仍宣称原尺寸。
            if (!CGRectEqualToRect(inter, src)) {
                NSLog(@"[gifrecorder-sck] recording region must stay within one display");
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
            if (@available(macOS 14.0, *)) {
                conf.captureResolution = SCCaptureResolutionBest;
            }
            NSMutableArray<SCWindow *> *ownWindows = [NSMutableArray array];
            for (SCWindow *window in content.windows) {
                if (window.owningApplication.processID == getpid()) {
                    [ownWindows addObject:window];
                }
            }
            SCContentFilter *filter =
                [[SCContentFilter alloc] initWithDisplay:target excludingWindows:ownWindows];
            stream = [[SCStream alloc] initWithFilter:filter
                                        configuration:conf
                                             delegate:delegate];
            delegate.stream = stream;
            NSError *addErr = nil;
            BOOL added = [stream addStreamOutput:delegate
                                            type:SCStreamOutputTypeScreen
                               sampleHandlerQueue:dispatch_queue_create("cc.jilei.sck.frames", DISPATCH_QUEUE_SERIAL)
                                             error:&addErr];
            if (!added) {
                NSLog(@"[gifrecorder-sck] addStreamOutput failed: %@", addErr);
                [delegate cancel];
                dispatch_semaphore_signal(sem);
                return;
            }
            [stream startCaptureWithCompletionHandler:^(NSError *err2) {
                @synchronized (delegate) {
                if (err2 != nil) {
                    NSLog(@"[gifrecorder-sck] start error: %@", err2);
                    [delegate cancel];
                } else if (delegate.cancelled) {
                    [stream stopCaptureWithCompletionHandler:nil];
                } else {
                    delegate.started = YES;
                }
                }
                dispatch_semaphore_signal(sem);
            }];
            }
        }];
    });

    long waited = dispatch_semaphore_wait(
        sem, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));
    @synchronized (delegate) {
        if (waited != 0 || !delegate.started || delegate.cancelled) {
            [delegate cancel];
            return NULL;
        }
        return (void *)CFBridgingRetain(delegate);
    }
}

void JTKStopCapture(void *handle) {
    if (handle == NULL) return;
    JTKStreamDelegate *delegate = CFBridgingRelease(handle);
    [delegate cancel];
}
