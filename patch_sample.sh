#!/bin/bash
sed -i 's/if let Ok(sample) = snap_sink.try_pull_sample(gst::ClockTime::from_mseconds(500))/if let Some(sample) = snap_sink.try_pull_sample(gst::ClockTime::from_mseconds(500))/' dvr_app/src/main.rs
sed -i 's/if let Some(buffer) = sample.buffer()/if let Some(buffer) = sample.buffer() {\n                    if let Ok(map) = buffer.map_readable()/' dvr_app/src/main.rs
sed -i 's/let map = buffer.map_readable().unwrap();//' dvr_app/src/main.rs
