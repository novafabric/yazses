use std::path::Path;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use pbkdf2::pbkdf2_hmac;
use sha2::Sha256;

// getrandom 0.4 provides fill() for cryptographic random bytes
use getrandom::fill as getrandom_fill;

/// Number of PBKDF2 iterations (adr-007: default 256 000).
pub const DEFAULT_ITERATIONS: u32 = 256_000;

/// Number of consecutive wrong-passphrase attempts before lockout (R-06).
const MAX_FAILED_ATTEMPTS: u32 = 5;

/// Duration of the lockout window once `MAX_FAILED_ATTEMPTS` is exceeded (R-06).
const LOCKOUT_DURATION: Duration = Duration::from_secs(15 * 60);

/// Manages the per-installation salt and the in-session derived AES-256 key.
///
/// Also enforces a passphrase lockout policy (R-06): after
/// [`MAX_FAILED_ATTEMPTS`] consecutive wrong attempts the manager refuses
/// further unlock calls for [`LOCKOUT_DURATION`].  Successful unlock resets
/// the counter.
pub struct KeyManager {
    derived_key: [u8; 32],
    failed_attempts: AtomicU32,
    lockout_until: Mutex<Option<Instant>>,
}

impl KeyManager {
    /// Derive a key from `passphrase` + `salt` using PBKDF2-HMAC-SHA256.
    pub fn new(passphrase: &str, salt: &[u8], iterations: u32) -> Self {
        let mut key = [0u8; 32];
        pbkdf2_hmac::<Sha256>(passphrase.as_bytes(), salt, iterations, &mut key);
        Self {
            derived_key: key,
            failed_attempts: AtomicU32::new(0),
            lockout_until: Mutex::new(None),
        }
    }

    /// Returns the key as a SQLCipher hex pragma value: `x'AABBCC...'`
    pub fn sqlcipher_pragma(&self) -> String {
        format!("x'{}'", hex::encode(self.derived_key))
    }

    /// Loads an existing 32-byte salt from `path`, or generates one and writes it.
    pub fn load_or_create_salt(path: &Path) -> anyhow::Result<[u8; 32]> {
        if path.exists() {
            let bytes = std::fs::read(path)?;
            if bytes.len() != 32 {
                anyhow::bail!(
                    "salt file {} has wrong length {} (expected 32)",
                    path.display(),
                    bytes.len()
                );
            }
            let mut salt = [0u8; 32];
            salt.copy_from_slice(&bytes);
            return Ok(salt);
        }

        let mut salt = [0u8; 32];
        getrandom_fill(&mut salt).map_err(|e| anyhow::anyhow!("failed to generate salt: {e}"))?;

        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(path, salt)?;
        Ok(salt)
    }

    // ── Lockout helpers (R-06) ─────────────────────────────────────────────

    /// Check whether the caller is currently locked out.  If not, increment
    /// the failed-attempt counter and, if `MAX_FAILED_ATTEMPTS` is reached,
    /// set a lockout window.
    ///
    /// Returns `Err` with a human-readable message when locked out.
    pub fn check_and_record_failure(&self) -> anyhow::Result<()> {
        // ── Check existing lockout ─────────────────────────────────────────
        {
            let guard = self
                .lockout_until
                .lock()
                .expect("lockout_until mutex poisoned");
            if let Some(until) = *guard {
                if Instant::now() < until {
                    let remaining = until.duration_since(Instant::now());
                    anyhow::bail!(
                        "passphrase locked out for {} more seconds",
                        remaining.as_secs() + 1
                    );
                }
            }
        }

        // ── Increment failure counter ──────────────────────────────────────
        let attempts = self.failed_attempts.fetch_add(1, Ordering::SeqCst) + 1;

        if attempts >= MAX_FAILED_ATTEMPTS {
            let mut guard = self
                .lockout_until
                .lock()
                .expect("lockout_until mutex poisoned");
            *guard = Some(Instant::now() + LOCKOUT_DURATION);
        }

        Ok(())
    }

    /// Reset the failed-attempt counter and clear any active lockout.
    /// Call this after a successful passphrase verification.
    pub fn record_success(&self) {
        self.failed_attempts.store(0, Ordering::SeqCst);
        let mut guard = self
            .lockout_until
            .lock()
            .expect("lockout_until mutex poisoned");
        *guard = None;
    }

    /// Returns `true` if the passphrase manager is currently locked out.
    pub fn is_locked_out(&self) -> bool {
        let guard = self
            .lockout_until
            .lock()
            .expect("lockout_until mutex poisoned");
        guard
            .map(|until| Instant::now() < until)
            .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn derive_is_deterministic() {
        let km1 = KeyManager::new("passphrase", b"salt1234567890abcdef123456789012", 1);
        let km2 = KeyManager::new("passphrase", b"salt1234567890abcdef123456789012", 1);
        assert_eq!(km1.derived_key, km2.derived_key);
    }

    #[test]
    fn different_passphrase_gives_different_key() {
        let km1 = KeyManager::new("pass1", b"salt1234567890abcdef123456789012", 1);
        let km2 = KeyManager::new("pass2", b"salt1234567890abcdef123456789012", 1);
        assert_ne!(km1.derived_key, km2.derived_key);
    }

    #[test]
    fn sqlcipher_pragma_format() {
        let km = KeyManager::new("test", b"00000000000000000000000000000000", 1);
        let p = km.sqlcipher_pragma();
        assert!(p.starts_with("x'"));
        assert!(p.ends_with('\''));
        assert_eq!(p.len(), 2 + 64 + 1); // x' + 32 bytes hex + '
    }

    #[test]
    fn load_or_create_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test.salt");
        let salt1 = KeyManager::load_or_create_salt(&path).unwrap();
        let salt2 = KeyManager::load_or_create_salt(&path).unwrap();
        assert_eq!(salt1, salt2);
    }

    #[test]
    fn no_lockout_before_threshold() {
        let km = KeyManager::new("pass", b"salt1234567890abcdef123456789012", 1);
        // 4 failures — should not lock out
        for _ in 0..(MAX_FAILED_ATTEMPTS - 1) {
            assert!(km.check_and_record_failure().is_ok());
        }
        assert!(!km.is_locked_out());
    }

    #[test]
    fn lockout_after_five_failures() {
        let km = KeyManager::new("pass", b"salt1234567890abcdef123456789012", 1);
        // First 4 calls succeed (they record failures but don't yet lock out).
        for _ in 0..(MAX_FAILED_ATTEMPTS - 1) {
            assert!(km.check_and_record_failure().is_ok());
        }
        // 5th call triggers lockout — it still returns Ok (the lockout is set
        // for the *next* call).
        let _ = km.check_and_record_failure();
        // Now we should be locked out.
        assert!(km.is_locked_out());
        // Next call should return Err.
        assert!(km.check_and_record_failure().is_err());
    }

    #[test]
    fn success_resets_lockout() {
        let km = KeyManager::new("pass", b"salt1234567890abcdef123456789012", 1);
        for _ in 0..MAX_FAILED_ATTEMPTS {
            let _ = km.check_and_record_failure();
        }
        assert!(km.is_locked_out());
        km.record_success();
        assert!(!km.is_locked_out());
        // After reset, failures start fresh — 4 more should not lock out.
        for _ in 0..(MAX_FAILED_ATTEMPTS - 1) {
            assert!(km.check_and_record_failure().is_ok());
        }
        assert!(!km.is_locked_out());
    }
}
