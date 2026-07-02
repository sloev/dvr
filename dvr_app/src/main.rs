slint::include_modules!();

use gstreamer as gst;
use gstreamer::prelude::*;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use sysinfo::{System, Disks};
use axum::{routing::get, Router};
use tower_http::services::ServeDir;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 1. Initialize GStreamer
    gst::init()?;

    let ui = AppWindow::new()?;
    let ui_weak = ui.as_weak();

    // 2. HTTP Server for Gallery (Axum)
    tokio::spawn(async {
        let app = Router::new().nest_service("/gallery", ServeDir::new("/mnt/dvr_storage"));
        let listener = tokio::net::TcpListener::bind("0.0.0.0:80").await.unwrap();
        axum::serve(listener, app).await.unwrap();
    });

    // 3. Telemetry Task (sysinfo)
    let ui_telemetry = ui_weak.clone();
    tokio::spawn(async move {
        let mut sys = System::new_all();
        loop {
            sys.refresh_all();
            let cpu = sys.global_cpu_info().cpu_usage();
            let ram = (sys.used_memory() as f32 / sys.total_memory() as f32) * 100.0;
            
            let disks = Disks::new_with_refreshed_list();
            let mut disk_usage = 0.0;
            for disk in &disks {
                if disk.mount_point().to_str() == Some("/mnt/dvr_storage") {
                    disk_usage = (disk.total_space() - disk.available_space()) as f32 / disk.total_space() as f32 * 100.0;
                }
            }

            // Disk sweep logic: If > 90%, delete oldest file
            if disk_usage > 90.0 {
                if let Ok(entries) = std::fs::read_dir("/mnt/dvr_storage") {
                    let mut files: Vec<_> = entries.filter_map(Result::ok).collect();
                    files.sort_by_key(|a| a.metadata().unwrap().modified().unwrap());
                    if let Some(oldest) = files.first() {
                        let _ = std::fs::remove_file(oldest.path());
                    }
                }
            }

            let cpu_str = format!("{:.1}%", cpu);
            let ram_str = format!("{:.1}%", ram);
            let disk_str = format!("{:.1}%", disk_usage);

            slint::invoke_from_event_loop({
                let ui = ui_telemetry.clone();
                move || {
                    if let Some(ui) = ui.upgrade() {
                        ui.set_cpu_load(cpu_str.into());
                        ui.set_ram_usage(ram_str.into());
                        ui.set_disk_usage(disk_str.into());
                    }
                }
            }).unwrap();

            tokio::time::sleep(Duration::from_secs(1)).await;
        }
    });

    // 4. GStreamer Pipeline Setup
    // v4l2src -> tee -> kmssink (Preview)
    //                -> v4l2h264enc -> h264parse -> splitmuxsink (Recording)
    let pipeline_str = "v4l2src device=/dev/video0 ! video/x-raw,format=UYVY,width=1920,height=1080,framerate=30/1 ! tee name=t \
        t. ! queue max-size-buffers=2 drop=true ! kmssink force-modesetting=true \
        t. ! queue name=rec_queue ! v4l2h264enc extra-controls=\"encode,video_bitrate=10000000\" ! h264parse ! splitmuxsink location=/mnt/dvr_storage/dvr_%05d.mp4 max-size-bytes=1000000000 name=mux";
    
    let pipeline = gst::parse::launch(pipeline_str)?
        .downcast::<gst::Pipeline>()
        .expect("Expected a pipeline");

    let is_recording = Arc::new(Mutex::new(false));

    // 5. Button Callbacks
    {
        let pipeline_clone = pipeline.clone();
        let is_recording_clone = is_recording.clone();
        let ui_weak_clone = ui_weak.clone();

        ui.on_record_clicked(move || {
            let mut recording = is_recording_clone.lock().unwrap();
            if !*recording {
                *recording = true;
                if let Some(ui) = ui_weak_clone.upgrade() {
                    ui.set_is_recording(true);
                }
                pipeline_clone.set_state(gst::State::Playing).expect("Unable to set playing state");
            }
        });
    }

    {
        let pipeline_clone = pipeline.clone();
        let is_recording_clone = is_recording.clone();
        let ui_weak_clone = ui_weak.clone();

        ui.on_stop_clicked(move || {
            let mut recording = is_recording_clone.lock().unwrap();
            if *recording {
                *recording = false;
                if let Some(ui) = ui_weak_clone.upgrade() {
                    ui.set_is_recording(false);
                }
                // Send EOS to cleanly finalize mp4
                pipeline_clone.send_event(gst::event::Eos::new());
            }
        });
    }

    ui.on_gallery_clicked(move || {
        // Implementation for showing gallery or a QR code to the HTTP server
    });

    // 6. Run the UI (takes over DRM/KMS outputs via linuxkms backend)
    ui.run()?;

    Ok(())
}
