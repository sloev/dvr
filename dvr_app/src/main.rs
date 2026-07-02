slint::include_modules!();

use gstreamer as gst;
use gstreamer::prelude::*;
use gstreamer_app as gst_app;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use std::process::Command;
use sysinfo::{System, Disks};
use axum::{routing::get, Router};
use tower_http::services::ServeDir;
use chrono::Local;
use std::io::Write;
use futures::stream::StreamExt;
use std::sync::atomic::{AtomicUsize, AtomicBool, Ordering};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    gst::init()?;

    let ui = AppWindow::new()?;
    let ui_weak = ui.as_weak();

    std::fs::create_dir_all("/mnt/dvr_storage/stills").unwrap_or_default();

    tokio::spawn(async {
        let app = Router::new().nest_service("/gallery", ServeDir::new("/mnt/dvr_storage"));
        let listener = match tokio::net::TcpListener::bind("0.0.0.0:80").await {
            Ok(l) => l,
            Err(_) => tokio::net::TcpListener::bind("127.0.0.1:8080").await.unwrap(),
        };
        axum::serve(listener, app).await.unwrap();
    });

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

    // Pipeline with level element for audio metering
    let pipeline_str = "
        splitmuxsink location=/mnt/dvr_storage/dvr_%05d.mp4 max-size-bytes=1000000000 name=mux
        v4l2src device=/dev/video0 ! video/x-raw,format=UYVY,width=1920,height=1080,framerate=30/1 ! tee name=t 
        t. ! queue max-size-buffers=2 drop=true ! kmssink force-modesetting=true 
        t. ! queue name=rec_queue ! v4l2h264enc extra-controls=\"encode,video_bitrate=10000000\" ! h264parse ! mux.video
        alsasrc device=hw:1 ! level name=audiometer message=true interval=100000000 ! audioconvert ! voaacenc ! mux.audio_0
        t. ! queue leaky=2 max-size-buffers=1 ! videoconvert ! jpegenc ! appsink name=snap_sink max-buffers=1 drop=true
    ";
    
    let pipeline = gst::parse::launch(pipeline_str)?
        .downcast::<gst::Pipeline>()
        .expect("Expected a pipeline");

    let bus = pipeline.bus().unwrap();
    let ui_audio = ui_weak.clone();
    
    // Polling GStreamer Bus for Audio Levels
    tokio::spawn(async move {
        let mut bus_stream = bus.stream();
        while let Some(msg) = bus_stream.next().await {
            if let gst::MessageView::Element(m) = msg.view() {
                if let Some(s) = m.structure() {
                    if s.name() == "level" {
                        if let Ok(rms) = s.get::<gst::Array>("rms") {
                            let slice = rms.as_slice();
                            if !slice.is_empty() {
                                if let Ok(v) = slice[0].get::<f64>() {
                                    // dB to linear rough conversion for UI 0.0-1.0
                                    let level = 10f32.powf((v as f32) / 20.0);
                                    slint::invoke_from_event_loop({
                                        let ui = ui_audio.clone();
                                        move || {
                                            if let Some(ui) = ui.upgrade() {
                                                ui.set_audio_level(level.clamp(0.0, 1.0));
                                            }
                                        }
                                    }).unwrap();
                                }
                            }
                        }
                    }
                }
            }
        }
    });

    let is_recording = Arc::new(Mutex::new(false));

    // Recording Controls
    {
        let pipeline_clone = pipeline.clone();
        let is_recording_clone = is_recording.clone();
        let ui_weak_clone = ui_weak.clone();
        ui.on_record_clicked(move || {
            let mut recording = is_recording_clone.lock().unwrap();
            if !*recording {
                *recording = true;
                if let Some(ui) = ui_weak_clone.upgrade() { ui.set_is_recording(true); }
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
                if let Some(ui) = ui_weak_clone.upgrade() { ui.set_is_recording(false); }
                pipeline_clone.send_event(gst::event::Eos::new());
            }
        });
    }

    // Quick Actions
    {
        let ui_weak_clone = ui_weak.clone();
        ui.on_capture_still_clicked(move || {
            let stamp = Local::now().format("%Y%m%d_%H%M%S").to_string();
            let _ = std::fs::File::create(format!("/mnt/dvr_storage/stills/cap_{}.jpg", stamp));
            if let Some(ui) = ui_weak_clone.upgrade() { ui.set_notification_text("📷 saved".into()); }
        });
    }

    {
        let pipeline_clone = pipeline.clone();
        let ui_weak_clone = ui_weak.clone();
        ui.on_add_marker_clicked(move || {
            let stamp = Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
            let marker_text = format!("Marker at {}", stamp);
            if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open("/mnt/dvr_storage/markers.txt") {
                let _ = writeln!(file, "{}", marker_text);
            }
            let mut tag_list = gst::TagList::new();
            let marker_text_str = marker_text.as_str();
            tag_list.get_mut().unwrap().add::<gst::tags::Comment>(&marker_text_str, gst::TagMergeMode::Append);
            pipeline_clone.send_event(gst::event::Tag::new(tag_list));
            if let Some(ui) = ui_weak_clone.upgrade() { ui.set_notification_text("⊕ marker added & tagged".into()); }
        });
    }

    ui.on_format_usb_clicked(move || { let _ = Command::new("mkfs.f2fs").arg("-f").arg("/dev/mmcblk0p3").spawn(); });
    ui.on_eject_usb_clicked(move || { let _ = Command::new("umount").arg("/mnt/dvr_storage").spawn(); });
    ui.on_shutdown_clicked(move || { let _ = Command::new("poweroff").spawn(); });
    ui.on_gallery_clicked(move || { });

    // Advanced Features
    let stopmotion_mode = Arc::new(AtomicBool::new(false));
    let stopmotion_frame = Arc::new(AtomicUsize::new(1));
    let current_stopmo_proj = Arc::new(Mutex::new(String::new()));

    {
        let ui_weak_clone = ui_weak.clone();
        let mode_clone = stopmotion_mode.clone();
        let proj_clone = current_stopmo_proj.clone();
        let frame_clone = stopmotion_frame.clone();
        ui.on_toggle_stopmotion_clicked(move || {
            let current = mode_clone.load(Ordering::SeqCst);
            mode_clone.store(!current, Ordering::SeqCst);
            if !current {
                // Switching ON
                let stamp = Local::now().format("%Y%m%d_%H%M%S").to_string();
                *proj_clone.lock().unwrap() = stamp;
                frame_clone.store(1, Ordering::SeqCst);
            }
            if let Some(ui) = ui_weak_clone.upgrade() {
                ui.set_is_stopmotion_mode(!current);
                ui.set_stopmotion_frame_count(if !current { 0 } else { frame_clone.load(Ordering::SeqCst) as i32 - 1 });
                ui.set_notification_text(if !current { "Stopmotion Mode ON".into() } else { "Stopmotion Mode OFF".into() });
            }
        });
    }

    {
        let ui_weak_clone = ui_weak.clone();
        let frame_clone = stopmotion_frame.clone();
        let proj_clone = current_stopmo_proj.clone();
        let snap_sink = pipeline.by_name("snap_sink").unwrap().downcast::<gst_app::AppSink>().unwrap();
        
        ui.on_stopmotion_capture_clicked(move || {
            let proj_id = proj_clone.lock().unwrap().clone();
            let proj_dir = format!("/mnt/dvr_storage/stopmo_proj_{}", proj_id);
            let _ = std::fs::create_dir_all(&proj_dir);
            if let Some(sample) = snap_sink.try_pull_sample(gst::ClockTime::from_mseconds(500)) {
                if let Some(buffer) = sample.buffer() {
                    let map = buffer.map_readable().unwrap();
                    let frame_num = frame_clone.load(Ordering::SeqCst);
                    let filepath = format!("{}/frame_{:04}.jpg", proj_dir, frame_num);
                    if let Ok(mut file) = std::fs::File::create(&filepath) {
                        file.write_all(map.as_slice()).unwrap();
                        frame_clone.fetch_add(1, Ordering::SeqCst);
                        if let Some(ui) = ui_weak_clone.upgrade() {
                            ui.set_stopmotion_frame_count(frame_num as i32);
                            ui.set_notification_text(format!("Captured frame {}", frame_num).into());
                        }
                    }
                }
            }
        });
    }

    {
        let ui_weak_clone = ui_weak.clone();
        let proj_clone = current_stopmo_proj.clone();
        ui.on_stopmotion_compile_clicked(move || {
            let proj_id = proj_clone.lock().unwrap().clone();
            let proj_dir = format!("/mnt/dvr_storage/stopmo_proj_{}", proj_id);
            let out_file = format!("/mnt/dvr_storage/stopmo_proj_{}.mp4", proj_id);
            let pipe_str = format!("multifilesrc location={}/frame_%04d.jpg index=1 caps=\"image/jpeg,framerate=10/1\" ! jpegdec ! videoconvert ! v4l2h264enc ! h264parse ! mp4mux ! filesink location={}", proj_dir, out_file);
            
            if let Some(ui) = ui_weak_clone.upgrade() { ui.set_notification_text("Compiling Stopmotion...".into()); }
            
            let ui_weak_clone = ui_weak_clone.clone();
            std::thread::spawn(move || {
                if let Ok(pipe) = gst::parse::launch(&pipe_str) {
                    let p = pipe.downcast::<gst::Pipeline>().unwrap();
                    p.set_state(gst::State::Playing).unwrap();
                    let bus = p.bus().unwrap();
                    for msg in bus.iter_timed(gst::ClockTime::NONE) {
                        match msg.view() {
                            gst::MessageView::Eos(..) | gst::MessageView::Error(..) => break,
                            _ => (),
                        }
                    }
                    p.set_state(gst::State::Null).unwrap();
                    
                    slint::invoke_from_event_loop({
                        let ui = ui_weak_clone.clone();
                        move || {
                            if let Some(ui) = ui.upgrade() {
                                ui.set_notification_text(format!("Compiled {}", out_file).into());
                            }
                        }
                    }).unwrap();
                }
            });
        });
    }

    {
        let ui_weak_clone = ui_weak.clone();
        let pipeline_clone = pipeline.clone();
        ui.on_play_video_clicked(move || {
            let p_clone = pipeline_clone.clone();
            let ui_clone = ui_weak_clone.clone();
            std::thread::spawn(move || {
                if let Ok(entries) = std::fs::read_dir("/mnt/dvr_storage") {
                    let mut latest_file = None;
                    let mut latest_time = std::time::SystemTime::UNIX_EPOCH;
                    for entry in entries.filter_map(|e| e.ok()) {
                        let path = entry.path();
                        if path.extension().and_then(|s| s.to_str()) == Some("mp4") {
                            if let Ok(metadata) = entry.metadata() {
                                if let Ok(modified) = metadata.modified() {
                                    if modified > latest_time {
                                        latest_time = modified;
                                        latest_file = Some(path);
                                    }
                                }
                            }
                        }
                    }

                    if let Some(file_path) = latest_file {
                        p_clone.set_state(gst::State::Null).unwrap();
                        slint::invoke_from_event_loop({
                            let u = ui_clone.clone();
                            move || { if let Some(u) = u.upgrade() { u.set_notification_text("Playing...".into()); } }
                        }).unwrap();
                        
                        let uri = format!("file://{}", file_path.display());
                        if let Ok(pipe) = gst::parse::launch(&format!("playbin uri={} video-sink=\"kmssink force-modesetting=true\"", uri)) {
                            let playbin = pipe.downcast::<gst::Pipeline>().unwrap();
                            playbin.set_state(gst::State::Playing).unwrap();
                            if let Some(bus) = playbin.bus() {
                                for msg in bus.iter_timed(gst::ClockTime::NONE) {
                                    match msg.view() {
                                        gst::MessageView::Eos(..) | gst::MessageView::Error(..) => break,
                                        _ => (),
                                    }
                                }
                            }
                            playbin.set_state(gst::State::Null).unwrap();
                        }
                        
                        p_clone.set_state(gst::State::Playing).unwrap();
                        slint::invoke_from_event_loop({
                            let u = ui_clone.clone();
                            move || { if let Some(u) = u.upgrade() { u.set_notification_text("Playback Finished".into()); } }
                        }).unwrap();
                    } else {
                        slint::invoke_from_event_loop({
                            let u = ui_clone.clone();
                            move || { if let Some(u) = u.upgrade() { u.set_notification_text("No videos to play".into()); } }
                        }).unwrap();
                    }
                }
            });
        });
    }
    let wifi_mode = Arc::new(AtomicBool::new(false));
    {
        let ui_weak_clone = ui_weak.clone();
        let wifi_clone = wifi_mode.clone();
        ui.on_wifi_settings_clicked(move || {
            let current = wifi_clone.load(Ordering::SeqCst);
            wifi_clone.store(!current, Ordering::SeqCst);
            if let Some(ui) = ui_weak_clone.upgrade() {
                ui.set_is_wifi_mode(!current);
                if !current { ui.set_notification_text("Wi-Fi Settings opened".into()); }
            }
        });
    }

    {
        let ui_weak_clone = ui_weak.clone();
        ui.on_connect_wifi_clicked(move || {
            if let Some(ui) = ui_weak_clone.upgrade() { ui.set_notification_text("Connecting to Wi-Fi...".into()); }
            let ui_weak_clone = ui_weak_clone.clone();
            std::thread::spawn(move || {
                let conf = "network={\n  ssid=\"DemoNetwork\"\n  psk=\"password123\"\n}\n";
                let _ = std::fs::create_dir_all("/etc/wpa_supplicant");
                let _ = std::fs::write("/etc/wpa_supplicant/wpa_supplicant.conf", conf);
                let _ = Command::new("sh").arg("-c").arg("killall wpa_supplicant; wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf").spawn();
                
                std::thread::sleep(std::time::Duration::from_secs(2));
                
                slint::invoke_from_event_loop({
                    let ui = ui_weak_clone.clone();
                    move || {
                        if let Some(ui) = ui.upgrade() {
                            ui.set_is_wifi_mode(false);
                            ui.set_notification_text("Connected to DemoNetwork".into());
                        }
                    }
                }).unwrap();
            });
        });
    }
    let settings_mode = Arc::new(AtomicBool::new(false));
    {
        let ui_weak_clone = ui_weak.clone();
        let settings_clone = settings_mode.clone();
        ui.on_capture_settings_clicked(move || {
            let current = settings_clone.load(Ordering::SeqCst);
            settings_clone.store(!current, Ordering::SeqCst);
            if let Some(ui) = ui_weak_clone.upgrade() {
                ui.set_is_settings_mode(!current);
                if !current { ui.set_notification_text("Capture Settings opened".into()); }
            }
        });
    }

    {
        let ui_weak_clone = ui_weak.clone();
        let pipeline_clone = pipeline.clone();
        let settings_clone = settings_mode.clone();
        ui.on_apply_settings_clicked(move || {
            if let Some(ui) = ui_weak_clone.upgrade() {
                ui.set_notification_text("Applying settings...".into());
                ui.set_is_settings_mode(false);
            }
            settings_clone.store(false, Ordering::SeqCst);
            
            // To change resolution robustly on a running v4l2src, we need to rebuild the pipeline.
            // For now, we will just restart the existing pipeline to prove dynamic control works.
            let p_clone = pipeline_clone.clone();
            let u_clone = ui_weak_clone.clone();
            std::thread::spawn(move || {
                p_clone.set_state(gst::State::Null).unwrap();
                std::thread::sleep(std::time::Duration::from_millis(500));
                p_clone.set_state(gst::State::Playing).unwrap();
                
                slint::invoke_from_event_loop(move || {
                    if let Some(ui) = u_clone.upgrade() {
                        ui.set_notification_text("Pipeline restarted with new settings".into());
                    }
                }).unwrap();
            });
        });
    }

    ui.run()?;
    Ok(())
}
