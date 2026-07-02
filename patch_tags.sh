#!/bin/bash
sed -i 's/let tag_list = gst::tags::TagList::builder()/let mut tag_list = gst::TagList::new();\n            tag_list.get_mut().unwrap().add::<gst::tags::Comment>(marker_text.as_str(), gst::TagMergeMode::Append);\n            \/\/ .add::<gst::tags::Comment>(marker_text.as_str(), gst::TagMergeMode::Append)\n            \/\/ .build()/' dvr_app/src/main.rs
sed -i 's/\.add::<gst::tags::Comment>(marker_text.as_str(), gst::TagMergeMode::Append)//' dvr_app/src/main.rs
sed -i 's/\.build();//' dvr_app/src/main.rs
