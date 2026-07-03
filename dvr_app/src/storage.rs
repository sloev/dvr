use std::path::{Path, PathBuf};
use std::time::SystemTime;
use sysinfo::Disks;

pub trait StorageSystem {
    fn get_disk_usage(&mut self, mount_point: &str) -> f32;
    fn get_files(&mut self, dir: &str) -> Result<Vec<StorageFile>, std::io::Error>;
    fn remove_file(&mut self, path: &Path) -> Result<(), std::io::Error>;
}

#[derive(Clone, Debug, PartialEq)]
pub struct StorageFile {
    pub path: PathBuf,
    pub modified: SystemTime,
}

pub struct RealStorageSystem {
    disks: Disks,
}

impl RealStorageSystem {
    pub fn new() -> Self {
        Self {
            disks: Disks::new_with_refreshed_list(),
        }
    }
}

impl StorageSystem for RealStorageSystem {
    fn get_disk_usage(&mut self, mount_point: &str) -> f32 {
        self.disks.refresh_list();
        let mut disk_usage = 0.0;
        for disk in &self.disks {
            if disk.mount_point().to_str() == Some(mount_point) {
                let total = disk.total_space();
                if total > 0 {
                    disk_usage = (total.saturating_sub(disk.available_space())) as f32 / total as f32 * 100.0;
                }
            }
        }
        disk_usage
    }

    fn get_files(&mut self, dir: &str) -> Result<Vec<StorageFile>, std::io::Error> {
        let entries = std::fs::read_dir(dir)?;
        let mut files = Vec::new();
        for entry in entries.filter_map(Result::ok) {
            if let Ok(metadata) = entry.metadata() {
                if let Ok(modified) = metadata.modified() {
                    files.push(StorageFile {
                        path: entry.path(),
                        modified,
                    });
                }
            }
        }
        Ok(files)
    }

    fn remove_file(&mut self, path: &Path) -> Result<(), std::io::Error> {
        std::fs::remove_file(path)
    }
}

pub fn manage_storage(sys: &mut impl StorageSystem, mount_point: &str) -> f32 {
    let disk_usage = sys.get_disk_usage(mount_point);
    if disk_usage > 90.0 {
        if let Ok(mut files) = sys.get_files(mount_point) {
            files.sort_by_cached_key(|f| f.modified);
            if let Some(oldest) = files.iter().find(|f| f.path.extension().unwrap_or_default() == "mp4") {
                let _ = sys.remove_file(&oldest.path);
            }
        }
    }
    disk_usage
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    struct MockStorageSystem {
        disk_usage: f32,
        files: Result<Vec<StorageFile>, std::io::ErrorKind>,
        removed_files: Vec<PathBuf>,
    }

    impl MockStorageSystem {
        fn new(disk_usage: f32, files: Result<Vec<StorageFile>, std::io::ErrorKind>) -> Self {
            Self {
                disk_usage,
                files,
                removed_files: Vec::new(),
            }
        }
    }

    impl StorageSystem for MockStorageSystem {
        fn get_disk_usage(&mut self, _mount_point: &str) -> f32 {
            self.disk_usage
        }

        fn get_files(&mut self, _dir: &str) -> Result<Vec<StorageFile>, std::io::Error> {
            match &self.files {
                Ok(files) => Ok(files.clone()),
                Err(kind) => Err(std::io::Error::from(*kind)),
            }
        }

        fn remove_file(&mut self, path: &Path) -> Result<(), std::io::Error> {
            self.removed_files.push(path.to_path_buf());
            Ok(())
        }
    }

    #[test]
    fn test_manage_storage_under_limit() {
        let mut sys = MockStorageSystem::new(80.0, Ok(vec![]));
        let usage = manage_storage(&mut sys, "/mnt/dvr_storage");
        assert_eq!(usage, 80.0);
        assert!(sys.removed_files.is_empty());
    }

    #[test]
    fn test_manage_storage_over_limit_removes_oldest_mp4() {
        let now = SystemTime::now();
        let files = vec![
            StorageFile { path: PathBuf::from("new.mp4"), modified: now },
            StorageFile { path: PathBuf::from("old.mp4"), modified: now - Duration::from_secs(100) },
            StorageFile { path: PathBuf::from("old.jpg"), modified: now - Duration::from_secs(200) },
        ];
        let mut sys = MockStorageSystem::new(95.0, Ok(files));
        let usage = manage_storage(&mut sys, "/mnt/dvr_storage");

        assert_eq!(usage, 95.0);
        assert_eq!(sys.removed_files.len(), 1);
        assert_eq!(sys.removed_files[0], PathBuf::from("old.mp4"));
    }

    #[test]
    fn test_manage_storage_over_limit_no_mp4() {
        let now = SystemTime::now();
        let files = vec![
            StorageFile { path: PathBuf::from("old.jpg"), modified: now - Duration::from_secs(200) },
        ];
        let mut sys = MockStorageSystem::new(95.0, Ok(files));
        manage_storage(&mut sys, "/mnt/dvr_storage");

        assert!(sys.removed_files.is_empty());
    }

    #[test]
    fn test_manage_storage_fs_error() {
        let mut sys = MockStorageSystem::new(95.0, Err(std::io::ErrorKind::NotFound));
        manage_storage(&mut sys, "/mnt/dvr_storage");

        assert!(sys.removed_files.is_empty());
    }
}
