slint::include_modules!();

use gstreamer as gst;
use gstreamer::prelude::*;
use std::sync::{Arc, Mutex};
use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize GStreamer
    gst::init()?;

    let ui = AppWindow::new()?;
    let ui_weak = ui.as_weak();

    // Create the basic GStreamer pipeline
    // Pipeline: v4l2src -> tee -> kmssink (for preview)
    //                          -> [recording branch] queue -> v4l2h264enc -> h264parse -> mp4mux -> filesink
    
    // For this example, we'll build a dynamic pipeline that we can control.
    let pipeline_str = "v4l2src device=/dev/video0 ! video/x-raw,width=1920,height=1080 ! tee name=t \
        t. ! queue ! kmssink force-modesetting=true \
        t. ! queue name=rec_queue ! v4l2h264enc ! h264parse ! mp4mux ! filesink location=/tmp/dvr_video.mp4 name=filesink";
    
    // In a real implementation, you'd construct this programmatically to easily add/remove the recording branch.
    // For now, we'll just parse the string pipeline but keep the recording branch in a playing/paused state.
    
    let pipeline = gst::parse::launch(pipeline_str)?
        .downcast::<gst::Pipeline>()
        .expect("Expected a pipeline");

    let is_recording = Arc::new(Mutex::new(false));

    // Button Callbacks
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
                
                // In a robust implementation, you would dynamically link the recording branch.
                // Here we just ensure the pipeline is playing.
                pipeline_clone.set_state(gst::State::Playing).expect("Unable to set the pipeline to the `Playing` state");
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
                
                // Send EOS event to the pipeline to safely finalize the mp4 file
                pipeline_clone.send_event(gst::event::Eos::new());
                
                // Note: We need a bus watch to handle EOS and set state to Null, but for simplicity here:
                // pipeline_clone.set_state(gst::State::Null).unwrap();
            }
        });
    }

    {
        let pipeline_clone = pipeline.clone();
        ui.on_play_clicked(move || {
            // Playback logic would go here. E.g., re-launching a pipeline to play /tmp/dvr_video.mp4
            pipeline_clone.set_state(gst::State::Ready).unwrap();
        });
    }

    // Run the UI
    // Note: With linuxkms backend, this will take over the DRM/KMS outputs.
    ui.run()?;

    Ok(())
}
