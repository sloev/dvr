use gstreamer as gst;
use gstreamer::prelude::*;
use futures::stream::StreamExt;
use std::sync::{Arc, Mutex};

fn main() {
    gst::init().unwrap();
    let pipeline = gst::Pipeline::new();
    let bus = pipeline.bus().unwrap();
    let mut tag_list = gst::TagList::new();
    tag_list.get_mut().unwrap().add::<gst::tags::Comment>(&"hello".to_string(), gst::TagMergeMode::Append);

    let _ = tokio::spawn(async move {
        let mut bus_stream = bus.stream();
        while let Some(msg) = bus_stream.next().await {
            if let gst::MessageView::Element(m) = msg.view() {
                if let Some(s) = m.structure() {
                    if let Ok(rms) = s.get::<gst::Array>("rms") {
                        if let Ok(v) = rms.as_slice()[0].get::<f64>() {
                            let level = 10f32.powf((v as f32) / 20.0);
                        }
                    }
                }
            }
        }
    });
}
