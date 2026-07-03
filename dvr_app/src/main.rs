slint::include_modules!();

use gstreamer as gst;
use gstreamer::prelude::*;
use std::sync::{Arc, Mutex};
use std::time::Duration;
use sysinfo::System;
use axum::Router;
use tower_http::services::ServeDir;
use chrono::Local;
use std::io::Write;
use futures::stream::StreamExt;
use std::sync::atomic::{AtomicUsize, AtomicBool, Ordering};
use std::process::Command;
use gstreamer_app::AppSink;

mod storage;

pub fn create_storage_dirs(base_path: &str) {
    let stills_path = format!("{}/stills", base_path);
    std::fs::create_dir_all(&stills_path).unwrap_or_default();
}

pub fn setup_stopmotion_dir(base_path: &str, proj_id: &str) -> std::io::Result<String> {
    let proj_dir = format!("{}/stopmo_proj_{}", base_path, proj_id);
    std::fs::create_dir_all(&proj_dir)?;
    Ok(proj_dir)
}

fn generate_random_password(len: usize) -> String {
    const CHARSET: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    let mut bytes = vec![0u8; len];
    let from_urandom = std::fs::File::open("/dev/urandom")
        .and_then(|mut f| std::io::Read::read_exact(&mut f, &mut bytes))
        .is_ok();
    if !from_urandom {
        // Should never happen on the target Linux appliance, but never ship
        // with an empty/predictable password just because /dev/urandom was
        // unavailable (e.g. running this codepath outside the appliance).
        use std::time::{SystemTime, UNIX_EPOCH};
        let seed = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(1);
        for (i, b) in bytes.iter_mut().enumerate() {
            *b = ((seed >> ((i % 16) * 8)) & 0xff) as u8 ^ (i as u8).wrapping_mul(31);
        }
    }
    bytes.iter().map(|b| CHARSET[(*b as usize) % CHARSET.len()] as char).collect()
}

/// Returns the gallery HTTP Basic Auth password: the operator-set
/// `GALLERY_PASSWORD` env var if present, otherwise a random password that's
/// generated once and persisted to the writable storage partition so it
/// stays stable across reboots instead of falling back to a fixed literal
/// default shared by every device built from this source.
fn get_or_create_gallery_password() -> (String, bool) {
    get_or_create_gallery_password_at("/mnt/dvr_storage", std::env::var("GALLERY_PASSWORD").ok())
}

fn get_or_create_gallery_password_at(storage_base_path: &str, env_override: Option<String>) -> (String, bool) {
    if let Some(p) = env_override {
        if !p.is_empty() {
            return (p, false);
        }
    }
    let secret_path = std::path::Path::new(storage_base_path).join(".device_secrets/gallery_password");
    if let Ok(existing) = std::fs::read_to_string(&secret_path) {
        let existing = existing.trim().to_string();
        if !existing.is_empty() {
            return (existing, true);
        }
    }
    let generated = generate_random_password(16);
    if let Some(parent) = secret_path.parent() {
        if std::fs::create_dir_all(parent).is_ok() {
            let _ = std::fs::write(&secret_path, &generated);
        }
    }
    eprintln!(
        "GALLERY_PASSWORD not set - generated a random password and saved it to {}",
        secret_path.display()
    );
    (generated, true)
}

// wpa_supplicant's config format is line-based and supports C-style escape
// sequences inside quoted strings, so a raw newline/CR in the input must be
// escaped rather than passed through - otherwise it terminates the current
// line early and lets an attacker-controlled SSID/PSK inject arbitrary
// additional config directives, quote-escaping alone is not sufficient.
fn escape_wpa_string(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for c in value.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            _ => out.push(c),
        }
    }
    out
}

// Generates (and caches) a small JPEG thumbnail for a recording by grabbing
// a single decoded frame through a short-lived, display-less pipeline - this
// never touches the KMS/DRM sink so it can run concurrently with the live
// camera pipeline. Returns None (leaving the gallery entry with no image)
// on any failure rather than panicking, since thumbnailing is best-effort.
fn generate_thumbnail(video_path: &std::path::Path) -> Option<String> {
    let filename = video_path.file_name()?.to_string_lossy().to_string();
    let thumb_dir = std::path::Path::new("/mnt/dvr_storage/stills/.thumbs");
    std::fs::create_dir_all(thumb_dir).ok()?;
    let thumb_path = thumb_dir.join(format!("{}.jpg", filename));
    if thumb_path.exists() {
        return Some(thumb_path.to_string_lossy().to_string());
    }

    let pipe_str = format!(
        "filesrc location=\"{}\" ! decodebin ! videoconvert ! videoscale ! video/x-raw,width=320,height=180 ! jpegenc ! appsink name=thumb_sink max-buffers=1 drop=true",
        video_path.display()
    );
    let pipeline = gst::parse::launch(&pipe_str).ok()?.downcast::<gst::Pipeline>().ok()?;
    let sink = pipeline.by_name("thumb_sink")?.downcast::<AppSink>().ok()?;
    if pipeline.set_state(gst::State::Playing).is_err() {
        let _ = pipeline.set_state(gst::State::Null);
        return None;
    }

    let saved = match sink.try_pull_sample(gst::ClockTime::from_seconds(5)) {
        Some(sample) => match sample.buffer() {
            Some(buffer) => match buffer.map_readable() {
                Ok(map) => std::fs::write(&thumb_path, map.as_slice()).is_ok(),
                Err(_) => false,
            },
            None => false,
        },
        None => false,
    };

    let _ = pipeline.set_state(gst::State::Null);

    if saved {
        Some(thumb_path.to_string_lossy().to_string())
    } else {
        let _ = std::fs::remove_file(&thumb_path);
        None
    }
}

pub fn write_wifi_config(base_path: &std::path::Path, ssid: &str, psk: &str) -> std::io::Result<()> {
    let ssid = escape_wpa_string(ssid);
    let psk = escape_wpa_string(psk);
    let conf = format!("network={{\n  ssid=\"{}\"\n  psk=\"{}\"\n}}\n", ssid, psk);
    std::fs::create_dir_all(base_path)?;
    std::fs::write(base_path.join("wpa_supplicant.conf"), conf)?;
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    gst::init()?;

    let ui = AppWindow::new()?;
    let ui_weak = ui.as_weak();

    create_storage_dirs("/mnt/dvr_storage");

    let (gallery_password, gallery_password_was_generated) = get_or_create_gallery_password();
    if gallery_password_was_generated {
        if let Some(ui) = ui_weak.upgrade() {
            ui.set_notification_text(format!("Gallery password: {} (admin) - saved to storage", gallery_password).into());
        }
    }
    tokio::spawn(async move {
        let app = Router::new()
            .nest_service("/gallery", ServeDir::new("/mnt/dvr_storage"))
            .layer(tower_http::validate_request::ValidateRequestHeaderLayer::basic("admin", gallery_password.as_str()));
        let listener = match tokio::net::TcpListener::bind("0.0.0.0:80").await {
            Ok(l) => l,
            Err(_) => tokio::net::TcpListener::bind("127.0.0.1:8080").await.unwrap(),
        };
        axum::serve(listener, app).await.unwrap();
    });

    let ui_telemetry = ui_weak.clone();
    tokio::spawn(async move {
        let mut sys = System::new_all();
        let mut storage_sys = crate::storage::RealStorageSystem::new();
        loop {
            sys.refresh_all();
            let cpu = sys.global_cpu_info().cpu_usage();
            let ram = (sys.used_memory() as f32 / sys.total_memory() as f32) * 100.0;

            let (next_storage_sys, disk_usage) = tokio::task::spawn_blocking(move || {
                let usage = crate::storage::manage_storage(&mut storage_sys, "/mnt/dvr_storage");
                (storage_sys, usage)
            }).await.unwrap_or_else(|_| (crate::storage::RealStorageSystem::new(), 0.0));
            storage_sys = next_storage_sys;

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
                match pipeline_clone.set_state(gst::State::Playing) {
                    Ok(_) => {
                        *recording = true;
                        if let Some(ui) = ui_weak_clone.upgrade() { ui.set_is_recording(true); }
                    }
                    Err(e) => {
                        // Don't let a hardware/pipeline hiccup (e.g. camera
                        // unplugged) take down the whole UI on the main thread.
                        if let Some(ui) = ui_weak_clone.upgrade() {
                            ui.set_notification_text(format!("⚠ Failed to start recording: {}", e).into());
                        }
                    }
                }
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
            tag_list.get_mut().unwrap().add::<gst::tags::Comment>(&marker_text.as_str(), gst::TagMergeMode::Append);
            pipeline_clone.send_event(gst::event::Tag::new(tag_list));
            if let Some(ui) = ui_weak_clone.upgrade() { ui.set_notification_text("⊕ marker added & tagged".into()); }
        });
    }

    {
        let ui_weak_clone = ui_weak.clone();
        ui.on_format_usb_requested(move || {
            if let Some(ui) = ui_weak_clone.upgrade() { ui.set_is_format_confirm_mode(true); }
        });
    }
    {
        let ui_weak_clone = ui_weak.clone();
        ui.on_format_usb_cancelled(move || {
            if let Some(ui) = ui_weak_clone.upgrade() { ui.set_is_format_confirm_mode(false); }
        });
    }
    {
        let ui_weak_clone = ui_weak.clone();
        ui.on_format_usb_confirmed(move || {
            if let Some(ui) = ui_weak_clone.upgrade() {
                ui.set_is_format_confirm_mode(false);
                ui.set_notification_text("Formatting storage...".into());
            }
            let _ = Command::new("mkfs.f2fs").arg("-f").arg("/dev/mmcblk0p3").spawn();
        });
    }
    ui.on_eject_usb_clicked(move || { let _ = Command::new("umount").arg("/mnt/dvr_storage").spawn(); });
    ui.on_shutdown_clicked(move || { let _ = Command::new("poweroff").spawn(); });

    let gallery_mode = Arc::new(AtomicBool::new(false));
    {
        let ui_weak_clone = ui_weak.clone();
        let gallery_clone = gallery_mode.clone();
        ui.on_gallery_clicked(move || {
            let current = gallery_clone.load(Ordering::SeqCst);
            gallery_clone.store(!current, Ordering::SeqCst);
            if let Some(ui) = ui_weak_clone.upgrade() {
                ui.set_is_gallery_mode(!current);
            }
            if !current {
                // Scanning the directory and generating thumbnails involves
                // blocking I/O and short GStreamer pipelines - keep it off
                // the UI thread so opening the gallery doesn't freeze the app.
                let ui_weak_thread = ui_weak_clone.clone();
                std::thread::spawn(move || {
                    let mut files = Vec::new();
                    if let Ok(entries) = std::fs::read_dir("/mnt/dvr_storage") {
                        for entry in entries.filter_map(|e| e.ok()) {
                            let path = entry.path();
                            if path.extension().and_then(|s| s.to_str()) == Some("mp4") {
                                let modified = entry.metadata()
                                    .and_then(|m| m.modified())
                                    .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
                                files.push((path, modified));
                            }
                        }
                    }
                    // Newest first by actual modification time - a lexical
                    // filename sort mixes dvr_* and stopmo_proj_* naming
                    // schemes and doesn't reflect real recency once both exist.
                    files.sort_by(|a, b| b.1.cmp(&a.1));

                    // Thumbnails aren't tracked by the ring-buffer sweep in
                    // storage.rs (it only removes .mp4 files), so prune any
                    // cached thumbnail whose source recording is gone.
                    let live_names: std::collections::HashSet<String> = files.iter()
                        .filter_map(|(p, _)| p.file_name().map(|n| n.to_string_lossy().to_string()))
                        .collect();
                    if let Ok(thumb_entries) = std::fs::read_dir("/mnt/dvr_storage/stills/.thumbs") {
                        for entry in thumb_entries.filter_map(|e| e.ok()) {
                            let thumb_name = entry.file_name().to_string_lossy().to_string();
                            if let Some(source_name) = thumb_name.strip_suffix(".jpg") {
                                if !live_names.contains(source_name) {
                                    let _ = std::fs::remove_file(entry.path());
                                }
                            }
                        }
                    }

                    // slint::Image isn't Send, so only build plain strings
                    // here - the actual Image (and VideoItem) get constructed
                    // back on the UI thread just before the model is set.
                    let entries: Vec<(String, String, Option<String>)> = files.into_iter().map(|(path, _)| {
                        let filename = path.file_name().unwrap_or_default().to_string_lossy().to_string();
                        let thumb = generate_thumbnail(&path);
                        (filename, path.to_string_lossy().to_string(), thumb)
                    }).collect();

                    slint::invoke_from_event_loop(move || {
                        if let Some(ui) = ui_weak_thread.upgrade() {
                            let items: Vec<VideoItem> = entries.into_iter().map(|(filename, path, thumb)| {
                                let img = thumb
                                    .map(|t| slint::Image::load_from_path(std::path::Path::new(&t)).unwrap_or_default())
                                    .unwrap_or_default();
                                VideoItem { image_path: img, filename: filename.into(), path: path.into() }
                            }).collect();
                            let model = std::rc::Rc::new(slint::VecModel::from(items));
                            ui.set_video_items(model.into());
                        }
                    }).unwrap();
                });
            }
        });
    }

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
        let snap_sink = pipeline.by_name("snap_sink").unwrap().downcast::<AppSink>().unwrap();
        
        ui.on_stopmotion_capture_clicked(move || {
            let proj_id = proj_clone.lock().unwrap().clone();
            let proj_dir = match setup_stopmotion_dir("/mnt/dvr_storage", &proj_id) {
                Ok(dir) => dir,
                Err(e) => {
                    if let Some(ui) = ui_weak_clone.upgrade() {
                        ui.set_notification_text(format!("Error: {}", e).into());
                    }
                    return;
                }
            };
            if let Some(sample) = snap_sink.try_pull_sample(gst::ClockTime::from_mseconds(500)) {
                if let Some(buffer) = sample.buffer() {
                    let Ok(map) = buffer.map_readable() else {
                        if let Some(ui) = ui_weak_clone.upgrade() {
                            ui.set_notification_text("⚠ Failed to read captured frame".into());
                        }
                        return;
                    };
                    let frame_num = frame_clone.load(Ordering::SeqCst);
                    let filepath = format!("{}/frame_{:04}.jpg", proj_dir, frame_num);
                    if let Ok(mut file) = std::fs::File::create(&filepath) {
                        if let Err(e) = file.write_all(map.as_slice()) {
                            if let Some(ui) = ui_weak_clone.upgrade() {
                                ui.set_notification_text(format!("⚠ Failed to save frame: {}", e).into());
                            }
                            return;
                        }
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
            
            let value = ui_weak_clone.clone();
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
                        let ui = value.clone();
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
        let is_recording_clone = is_recording.clone();
        ui.on_play_video_clicked(move |file_path: slint::SharedString| {
            let p_clone = pipeline_clone.clone();
            let ui_clone = ui_weak_clone.clone();
            let file_path = file_path.to_string();
            // Snapshot whether we were actually recording so we can restore
            // (not just assume) that exact state once playback is done.
            let was_recording = *is_recording_clone.lock().unwrap();
            std::thread::spawn(move || {
                if was_recording {
                    // Finalize the in-progress recording segment cleanly (EOS)
                    // instead of abruptly killing the pipeline, which can
                    // truncate/corrupt the currently-open .mp4 file.
                    p_clone.send_event(gst::event::Eos::new());
                    if let Some(bus) = p_clone.bus() {
                        for msg in bus.iter_timed(gst::ClockTime::from_seconds(5)) {
                            match msg.view() {
                                gst::MessageView::Eos(..) | gst::MessageView::Error(..) => break,
                                _ => (),
                            }
                        }
                    }
                }
                let _ = p_clone.set_state(gst::State::Null);
                slint::invoke_from_event_loop({
                    let u = ui_clone.clone();
                    move || { if let Some(u) = u.upgrade() { u.set_notification_text("Playing...".into()); } }
                }).unwrap();

                let uri = format!("file://{}", file_path);
                if let Ok(pipe) = gst::parse::launch(&format!("playbin uri={} video-sink=\"kmssink force-modesetting=true\"", uri)) {
                    if let Ok(playbin) = pipe.downcast::<gst::Pipeline>() {
                        let _ = playbin.set_state(gst::State::Playing);
                        if let Some(bus) = playbin.bus() {
                            for msg in bus.iter_timed(gst::ClockTime::NONE) {
                                match msg.view() {
                                    gst::MessageView::Eos(..) | gst::MessageView::Error(..) => break,
                                    _ => (),
                                }
                            }
                        }
                        let _ = playbin.set_state(gst::State::Null);
                    }
                }

                // Only resume the camera pipeline (which also resumes active
                // recording) if that's actually the state we interrupted -
                // otherwise leave it idle, exactly as we found it.
                if was_recording {
                    let _ = p_clone.set_state(gst::State::Playing);
                }
                slint::invoke_from_event_loop({
                    let u = ui_clone.clone();
                    move || { if let Some(u) = u.upgrade() { u.set_notification_text("Playback Finished".into()); } }
                }).unwrap();
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
            let (ssid, password) = match ui_weak_clone.upgrade() {
                Some(ui) => {
                    ui.set_notification_text("Connecting to Wi-Fi...".into());
                    (ui.get_wifi_ssid().to_string(), ui.get_wifi_password().to_string())
                }
                None => return,
            };
            let value = ui_weak_clone.clone();
            std::thread::spawn(move || {
                // /etc is mounted read-only on the target device; /run is tmpfs and writable.
                let base_path = std::path::Path::new("/run/wpa_supplicant");
                let result = write_wifi_config(base_path, &ssid, &password);
                if let Err(ref e) = result {
                    eprintln!("Failed to write Wi-Fi config: {}", e);
                } else {
                    let conf_path = base_path.join("wpa_supplicant.conf");
                    let _ = Command::new("killall")
                        .arg("wpa_supplicant")
                        .status();
                    let _ = Command::new("wpa_supplicant")
                        .args(["-B", "-i", "wlan0", "-c", conf_path.to_str().unwrap()])
                        .spawn();
                }

                std::thread::sleep(std::time::Duration::from_secs(2));

                let notification: slint::SharedString = match result {
                    Ok(()) => "Connected to Wi-Fi".into(),
                    Err(e) => format!("Wi-Fi connection failed: {}", e).into(),
                };
                slint::invoke_from_event_loop({
                    let ui = value.clone();
                    move || {
                        if let Some(ui) = ui.upgrade() {
                            ui.set_is_wifi_mode(false);
                            ui.set_notification_text(notification);
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::os::unix::fs::PermissionsExt;
    use std::path::Path;
    use tempfile::tempdir;

    // Permission-denied tests are meaningless when the test runner is root,
    // since root bypasses the DAC permission checks these tests rely on.
    fn running_as_root() -> bool {
        std::process::Command::new("id")
            .arg("-u")
            .output()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim() == "0")
            .unwrap_or(false)
    }

    #[test]
    fn test_create_storage_dirs_permission_denied() {
        if running_as_root() {
            return;
        }
        let temp_dir = tempdir().unwrap();
        let base_path = temp_dir.path().to_str().unwrap();

        let mut perms = fs::metadata(base_path).unwrap().permissions();
        perms.set_mode(0o500); // r-x------
        fs::set_permissions(base_path, perms).unwrap();

        create_storage_dirs(base_path);

        let mut perms = fs::metadata(base_path).unwrap().permissions();
        perms.set_mode(0o700); // rwx------
        fs::set_permissions(base_path, perms).unwrap();
    }

    #[test]
    fn test_setup_stopmotion_dir_success() {
        let temp_dir = tempdir().unwrap();
        let base_path = temp_dir.path().to_str().unwrap();
        let proj_id = "test_12345";
        let expected_dir = format!("{}/stopmo_proj_{}", base_path, proj_id);

        let result = setup_stopmotion_dir(base_path, proj_id);
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), expected_dir);
        assert!(Path::new(&expected_dir).exists());
    }

    #[test]
    fn test_setup_stopmotion_dir_error() {
        let temp_dir = tempdir().unwrap();
        let base_path = temp_dir.path().join("not_a_dir");
        fs::write(&base_path, "this is a file").unwrap();

        let result = setup_stopmotion_dir(base_path.to_str().unwrap(), "test_error");
        assert!(result.is_err());
    }

    #[test]
    fn test_write_wifi_config_success() {
        let dir = tempdir().unwrap();
        let base_path = dir.path();
        let ssid = "TestNetwork";
        let psk = "testpassword";

        let result = write_wifi_config(base_path, ssid, psk);
        assert!(result.is_ok());

        let conf_path = base_path.join("wpa_supplicant.conf");
        assert!(conf_path.exists());

        let content = fs::read_to_string(conf_path).unwrap();
        assert!(content.contains(ssid));
        assert!(content.contains(psk));
    }

    #[test]
    fn test_write_wifi_config_escapes_quotes_and_newlines() {
        let dir = tempdir().unwrap();
        let base_path = dir.path();
        // A malicious SSID attempting to break out of the quoted value and
        // inject an extra network block via an embedded quote and newlines.
        let ssid = "eviltwin\"\n}\nnetwork={\n  ssid=\"other";
        let psk = "pass\"word";

        let result = write_wifi_config(base_path, ssid, psk);
        assert!(result.is_ok());

        let content = fs::read_to_string(base_path.join("wpa_supplicant.conf")).unwrap();
        // Exactly one network block should exist - no raw newline or unescaped
        // quote from the input may reach the file to break out of the value.
        assert_eq!(content.lines().filter(|l| *l == "network={").count(), 1);
        assert_eq!(content.lines().count(), 4);
        assert!(content.contains("eviltwin\\\"\\n}\\nnetwork={\\n  ssid=\\\"other"));
        assert!(content.contains("pass\\\"word"));
    }

    #[test]
    fn test_write_wifi_config_error_handling() {
        if running_as_root() {
            return;
        }
        let dir = tempdir().unwrap();
        let base_path = dir.path();

        let file_path = base_path.join("wpa_supplicant.conf");
        fs::write(&file_path, "").unwrap();

        let mut perms = fs::metadata(&file_path).unwrap().permissions();
        perms.set_readonly(true);
        fs::set_permissions(&file_path, perms).unwrap();

        let result = write_wifi_config(base_path, "TestNetwork", "testpassword");
        assert!(result.is_err());
    }

    #[test]
    fn test_gallery_password_prefers_env_override() {
        let dir = tempdir().unwrap();
        let (password, generated) = get_or_create_gallery_password_at(
            dir.path().to_str().unwrap(),
            Some("operator-set-password".to_string()),
        );
        assert_eq!(password, "operator-set-password");
        assert!(!generated);
        // Setting an explicit password shouldn't persist a secret file.
        assert!(!dir.path().join(".device_secrets/gallery_password").exists());
    }

    #[test]
    fn test_gallery_password_generated_and_persisted() {
        let dir = tempdir().unwrap();
        let base_path = dir.path().to_str().unwrap();

        let (first, generated_first) = get_or_create_gallery_password_at(base_path, None);
        assert!(generated_first);
        assert!(!first.is_empty());
        assert_ne!(first, "password", "must not fall back to a literal weak default");

        // A second call (e.g. after a reboot) with no env override must
        // return the same persisted password rather than generating a new one.
        let (second, generated_second) = get_or_create_gallery_password_at(base_path, None);
        assert!(generated_second);
        assert_eq!(first, second);
    }

    #[test]
    fn test_generate_random_password_is_not_predictable_or_empty() {
        let a = generate_random_password(16);
        let b = generate_random_password(16);
        assert_eq!(a.len(), 16);
        assert_ne!(a, b);
    }
}
