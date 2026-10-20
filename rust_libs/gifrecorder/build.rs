fn main() {
    // macOS：编译 ScreenCaptureKit 薄 shim（只负责 SCK → BGRA 帧）
    #[cfg(target_os = "macos")]
    {
        let mut build = cc::Build::new();
        // @available emits __isPlatformVersionAtLeast. Rust's cdylib linker
        // does not add Clang's availability runtime automatically.
        let runtime = build.get_compiler().to_command()
            .arg("-print-file-name=libclang_rt.osx.a")
            .output().expect("query Clang availability runtime");
        assert!(runtime.status.success(), "Clang runtime query failed");
        let runtime_path = std::path::PathBuf::from(
            String::from_utf8(runtime.stdout).expect("Clang runtime path UTF-8").trim());
        assert!(runtime_path.is_file(), "Clang availability runtime missing: {:?}", runtime_path);
        build
            .file("native/sck_capture.m")
            .flag("-fobjc-arc")
            .flag("-mmacosx-version-min=12.3")
            .compile("sck_capture");
        println!("cargo:rustc-link-search=native={}", runtime_path.parent().unwrap().display());
        println!("cargo:rustc-link-lib=static=clang_rt.osx");
        println!("cargo:rustc-link-lib=framework=ScreenCaptureKit");
        println!("cargo:rustc-link-lib=framework=CoreVideo");
        println!("cargo:rustc-link-lib=framework=CoreMedia");
        println!("cargo:rustc-link-lib=framework=CoreGraphics");
        println!("cargo:rustc-link-lib=framework=Foundation");
        println!("cargo:rerun-if-changed=native/sck_capture.m");
    }
}
