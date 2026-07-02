#!/bin/bash
sed -i '/ui.on_play_video_clicked/,/});/c\
        ui.on_play_video_clicked(move |file_path: slint::SharedString| {\
            let p_clone = pipeline_clone.clone();\
            let ui_clone = ui_weak_clone.clone();\
            let file_path = file_path.to_string();\
            std::thread::spawn(move || {\
                p_clone.set_state(gst::State::Null).unwrap();\
                slint::invoke_from_event_loop({\
                    let u = ui_clone.clone();\
                    move || { if let Some(u) = u.upgrade() { u.set_notification_text("Playing...".into()); } }\
                }).unwrap();\
                \
                let uri = format!("file://{}", file_path);\
                if let Ok(pipe) = gst::parse::launch(&format!("playbin uri={} video-sink=\"kmssink force-modesetting=true\"", uri)) {\
                    let playbin = pipe.downcast::<gst::Pipeline>().unwrap();\
                    playbin.set_state(gst::State::Playing).unwrap();\
                    if let Some(bus) = playbin.bus() {\
                        for msg in bus.iter_timed(gst::ClockTime::NONE) {\
                            match msg.view() {\
                                gst::MessageView::Eos(..) | gst::MessageView::Error(..) => break,\
                                _ => (),\
                            }\
                        }\
                    }\
                    playbin.set_state(gst::State::Null).unwrap();\
                }\
                \
                p_clone.set_state(gst::State::Playing).unwrap();\
                slint::invoke_from_event_loop({\
                    let u = ui_clone.clone();\
                    move || { if let Some(u) = u.upgrade() { u.set_notification_text("Playback Finished".into()); } }\
                }).unwrap();\
            });\
        });' dvr_app/src/main.rs
