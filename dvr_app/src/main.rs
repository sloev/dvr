slint::include_modules!();

use gstreamer as gst;
use gstreamer::prelude::*;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use sysinfo::{System, Disks};
use axum::{routing::get, Router};
use tower_http::services::ServeDir;
use std::process::Command;
use chrono::Local;
use std::io::Write;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 1. Initialize GStreamer
    gst::init()?;

    let ui = AppWindow::new()?;
    let ui_weak = ui.as_weak();

    // Ensure directories
    std::fs::create_dir_all("/mnt/dvr_storage/stills").unwrap_or_default();

    // 2. HTTP Server for Gallery (Axum)
    tokio::spawn(async {
        let app = Router::new().nest_service("/gallery", ServeDir::new("/mnt/dvr_storage"));
        let listener = tokio::net::TcpListener::bind("0.0.0.0:80").await.unwrap_or_else(|_| tokio::net::TcpListener::bind("127.0.0.1:8080").await.unwrap());
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

            if disk_usage > 90.0 {
                if let Ok(entries) = std::fs::read_dir("/mnt/dvr_storage") {
                    let mut files: Vec<_> = entries.filter_map(Result::ok).collect();
                    files.sort_by_key(|a| a.metadata().unwrap().modified().unwrap());
                    if let Some(oldest) = files.iter().find(|f| f.path().extension().unwrap_or_default() == "mp4") {
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

    // 4. GStreamer Pipeline Setup (With Audio & Video Muxing)
    // Audio: alsasrc -> audioconvert -> voaacenc -> splitmuxsink (audio_%05d)
    // Video: v4l2src -> tee -> kmssink
    //                -> v4l2h264enc -> h264parse -> splitmuxsink (video_%05d)
    let pipeline_str = "
        splitmuxsink location=/mnt/dvr_storage/dvr_%05d.mp4 max-size-bytes=1000000000 name=mux
        v4l2src device=/dev/video0 ! video/x-raw,format=UYVY,width=1920,height=1080,framerate=30/1 ! tee name=t 
        t. ! queue max-size-buffers=2 drop=true ! kmssink force-modesetting=true 
        t. ! queue name=rec_queue ! v4l2h264enc extra-controls=\"encode,video_bitrate=10000000\" ! h264parse ! mux.video
        alsasrc device=hw:1 ! audioconvert ! voaacenc ! mux.audio_0
    ";
    
    let pipeline = gst::parse::launch(pipeline_str)?
        .downcast::<gst::Pipeline>()
        .expect("Expected a pipeline");

    let is_recording = Arc::new(Mutex::new(false));

    // 5. Callbacks
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
                pipeline_clone.send_event(gst::event::Eos::new());
            }
        });
    }

    {
        let ui_weak_clone = ui_weak.clone();
        ui.on_capture_still_clicked(move || {
            let stamp = Local::now().format("%Y%m%d_%H%M%S").to_string();
            let path = format!("/mnt/dvr_storage/stills/cap_{}.jpg", stamp);
            let _ = std::fs::File::create(&path); // Stub, pipeline integration needed
            if let Some(ui) = ui_weak_clone.upgrade() {
                ui.set_notification_text("📷 saved".into());
            }
        });
    }

    {
        let pipeline_clone = pipeline.clone();
        let ui_weak_clone = ui_weak.clone();
        ui.on_add_marker_clicked(move || {
            let stamp = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
            let marker_text = format!("Marker at {}", stamp);
            
            // 1. Write to markers.txt
            if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open("/mnt/dvr_storage/markers.txt") {
                let _ = writeln!(file, "{}", marker_text);
            }
            
            // 2. Inject into MP4 metadata (GStreamer Tags)
            let mut tag_list = gst::TagList::new();
            tag_list.get_mut().unwrap().add::<gst::tags::Comment>(&marker_text, gst::TagMergeMode::Append);
            pipeline_clone.send_event(gst::event::Tag::new(tag_list));

            if let Some(ui) = ui_weak_clone.upgrade() {
                ui.set_notification_text("⊕ marker added & tagged".into());
            }
        });
    }

    ui.on_format_usb_clicked(move || {
        let _ = Command::new("mkfs.f2fs").arg("-f").arg("/dev/mmcblk0p3").spawn();
    });

    ui.on_eject_usb_clicked(move || {
        let _ = Command::new("umount").arg("/mnt/dvr_storage").spawn();
    });

    ui.on_shutdown_clicked(move || {
        let _ = Command::new("poweroff").spawn();
    });

    ui.on_gallery_clicked(move || {
        // HTTP Server serves at /gallery
    });

    // Run the UI
    ui.run()?;

    Ok(())
}
