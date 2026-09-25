fn main() {
    // macOS：编译 ScreenCaptureKit 薄 shim（只负责 SCK → BGRA 帧）
    #[cfg(target_os = "macos")]
    {
        cc::Build::new()
            .file("native/sck_capture.m")
            .flag("-fobjc-arc")
            .compile("sck_capture");
        println!("cargo:rustc-link-lib=framework=ScreenCaptureKit");
        println!("cargo:rustc-link-lib=framework=CoreVideo");
        println!("cargo:rustc-link-lib=framework=CoreMedia");
        println!("cargo:rustc-link-lib=framework=CoreGraphics");
        println!("cargo:rustc-link-lib=framework=Foundation");
        println!("cargo:rerun-if-changed=native/sck_capture.m");
    }
}
