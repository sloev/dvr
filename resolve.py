import sys
import re

with open("dvr_app/src/main.rs", "r") as f:
    content = f.read()

# First conflict: imports and write_wifi_config
new_content = re.sub(
    r"<<<<<<< HEAD\nmod storage;\n=======\npub fn write_wifi_config\(base_path: &std::path::Path, ssid: &str, psk: &str\) -> std::io::Result<\(\)> \{\n    let conf = format!\(\"network=\{\{\\n  ssid=\\\"\{\}\\\"\\n  psk=\\\"\{\}\\\"\\n\}\}\\n\", ssid, psk\);\n    std::fs::create_dir_all\(base_path\)\?;\n    std::fs::write\(base_path\.join\(\"wpa_supplicant\.conf\"\), conf\)\?;\n    Ok\(\(\)\)\n\}\n>>>>>>> origin/master",
    r"""mod storage;

pub fn write_wifi_config(base_path: &std::path::Path, ssid: &str, psk: &str) -> std::io::Result<()> {
    let conf = format!("network={{\n  ssid=\"{}\"\n  psk=\"{}\"\n}}\n", ssid, psk);
    std::fs::create_dir_all(base_path)?;
    std::fs::write(base_path.join("wpa_supplicant.conf"), conf)?;
    Ok(())
}""",
    content,
    flags=re.DOTALL
)

# Second conflict: on_connect_wifi_clicked
new_content = re.sub(
    r"<<<<<<< HEAD\n                let base_path = std::path::Path::new\(\"/etc/wpa_supplicant\"\);\n                let ssid = \"DemoNetwork\";\n                let psk = \"password123\";\n\n                if let Err\(e\) = write_wifi_config\(base_path, ssid, psk\) \{\n                    eprintln!\(\"Failed to write Wi-Fi config: \{\}\", e\);\n                \} else \{\n                    let conf_path = base_path\.join\(\"wpa_supplicant\.conf\"\);\n                    let _ = std::process::Command::new\(\"sh\"\)\.arg\(\"-c\"\)\.arg\(&format!\(\"killall wpa_supplicant; wpa_supplicant -B -i wlan0 -c \{\}\", conf_path\.display\(\)\)\)\.spawn\(\);\n                \}\n=======\n                let conf = \"network=\{\\n  ssid=\\\"DemoNetwork\\\"\\n  psk=\\\"password123\\\"\\n\}\\n\";\n                let _ = std::fs::create_dir_all\(\"/etc/wpa_supplicant\"\);\n                let _ = std::fs::write\(\"/etc/wpa_supplicant/wpa_supplicant\.conf\", conf\);\n                let _ = std::process::Command::new\(\"killall\"\)\n                    \.arg\(\"wpa_supplicant\"\)\n                    \.status\(\);\n                let _ = std::process::Command::new\(\"wpa_supplicant\"\)\n                    \.args\(\[\"-B\", \"-i\", \"wlan0\", \"-c\", \"/etc/wpa_supplicant/wpa_supplicant\.conf\"\]\)\n                    \.spawn\(\);\n>>>>>>> origin/master",
    r"""                let base_path = std::path::Path::new("/etc/wpa_supplicant");
                let ssid = "DemoNetwork";
                let psk = "password123";

                if let Err(e) = write_wifi_config(base_path, ssid, psk) {
                    eprintln!("Failed to write Wi-Fi config: {}", e);
                } else {
                    let conf_path = base_path.join("wpa_supplicant.conf");
                    let _ = std::process::Command::new("killall")
                        .arg("wpa_supplicant")
                        .status();
                    let _ = std::process::Command::new("wpa_supplicant")
                        .args(["-B", "-i", "wlan0", "-c", conf_path.to_str().unwrap()])
                        .spawn();
                }""",
    new_content,
    flags=re.DOTALL
)

with open("dvr_app/src/main.rs", "w") as f:
    f.write(new_content)
