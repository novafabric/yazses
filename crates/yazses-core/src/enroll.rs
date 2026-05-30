// YazSes enrollment wizard — per-voice VAD calibration.
//
// Guides the user through reading 20 Harvard Sentences and derives:
//   vad_threshold  = percentile(noise_floors, 95) × 3.0   (clamped 0.001–0.1)
//   min_silence_ms = max(500, percentile(pause_durations, 95))  (clamped ≤ 5000)
//
// The `AudioRecorder` trait is injected so tests can supply deterministic audio
// without a physical microphone.

/// Harvard Sentences (phonetically diverse) — standard ASR enrollment corpus.
pub const PROMPTS: &[&str] = &[
    "The birch canoe slid on the smooth planks.",
    "Glue the sheet to the dark blue background.",
    "It is easy to tell the depth of a well.",
    "These days a chicken leg is a rare dish.",
    "Rice is often served in round bowls.",
    "The juice of lemons makes fine punch.",
    "The box was thrown beside the parked truck.",
    "The hogs were fed chopped corn and garbage.",
    "Four hours of steady work faced us.",
    "A large size in stockings is hard to sell.",
    "The boy was there when the sun rose.",
    "A rod is used to catch pink salmon.",
    "The source of the huge river is the clear spring.",
    "Kick the ball straight and follow through.",
    "Help the woman get back to her feet.",
    "A pot of tea helps to pass the evening.",
    "Smoky fires lack flame and heat.",
    "The soft cushion broke the man's fall.",
    "The salt breeze came across from the sea.",
    "The girl at the booth sold fifty bonds.",
];

/// Derived VAD calibration parameters written to config.
#[derive(Debug, Clone, PartialEq)]
pub struct EnrollResult {
    pub vad_threshold: f32,
    pub min_silence_ms: u32,
}

/// Injectable audio recording backend — real implementation uses cpal;
/// test implementation returns pre-canned samples.
pub trait AudioRecorder: Send + Sync {
    /// Record for `duration_s` seconds and return `(mono_f32_samples, sample_rate)`.
    fn record_seconds(&self, duration_s: f32) -> anyhow::Result<(Vec<f32>, u32)>;
}

/// Mock recorder for unit tests — returns the pre-set samples immediately.
pub struct MockRecorder {
    pub samples: Vec<f32>,
    pub sample_rate: u32,
}

impl MockRecorder {
    pub fn new(samples: Vec<f32>, sample_rate: u32) -> Self {
        Self {
            samples,
            sample_rate,
        }
    }

    /// Synthesise a recording with `noise_rms` during the first 500 ms and
    /// `speech_rms` for the remainder, with `trailing_silence_ms` of quiet at the end.
    pub fn synthesise(
        sample_rate: u32,
        duration_s: f32,
        noise_rms: f32,
        speech_rms: f32,
        trailing_silence_ms: f32,
    ) -> Self {
        let n = (duration_s * sample_rate as f32) as usize;
        let noise_end = (0.5 * sample_rate as f32) as usize;
        let silence_start =
            n.saturating_sub((trailing_silence_ms / 1000.0 * sample_rate as f32) as usize);

        let samples: Vec<f32> = (0..n)
            .map(|i| {
                if i < noise_end {
                    noise_rms
                } else if i >= silence_start {
                    0.0
                } else {
                    speech_rms
                }
            })
            .collect();

        Self {
            samples,
            sample_rate,
        }
    }
}

impl AudioRecorder for MockRecorder {
    fn record_seconds(&self, _duration_s: f32) -> anyhow::Result<(Vec<f32>, u32)> {
        Ok((self.samples.clone(), self.sample_rate))
    }
}

// ── Wizard ────────────────────────────────────────────────────────────────────

/// Run the enrollment wizard.
///
/// Calls `output_fn` for every user-facing message.
/// Returns derived VAD parameters on success.
pub fn run_wizard(
    recorder: &dyn AudioRecorder,
    mut output_fn: impl FnMut(&str),
) -> anyhow::Result<EnrollResult> {
    output_fn("\nYazSes Accessibility Enrollment");
    output_fn("===============================");
    output_fn("Read 20 short sentences aloud.");
    output_fn("Press Enter before each, then speak normally.\n");

    let mut noise_floors: Vec<f32> = Vec::new();
    let mut pause_durations: Vec<f32> = Vec::new();

    for (i, &prompt) in PROMPTS.iter().enumerate() {
        output_fn(&format!(
            "[{}/{}] Read aloud: \"{prompt}\"",
            i + 1,
            PROMPTS.len()
        ));
        output_fn("  Press Enter when ready...");
        // In real mode the CLI reads stdin here; in wizard mode this is injected.
        // We don't call stdin here so the caller can decide (interactive vs test).
        output_fn("  Recording for 3 seconds...");

        let (audio, sample_rate) = recorder.record_seconds(3.0)?;

        if audio.len() < sample_rate as usize {
            output_fn("  (recording too short, skipping)");
            continue;
        }

        let (nf, pause_ms) = analyse_sample(&audio, sample_rate);
        noise_floors.push(nf);
        pause_durations.push(pause_ms);
        output_fn(&format!("  ✓ noise_floor={nf:.4}  pause={pause_ms:.0}ms"));
    }

    if noise_floors.len() < 5 {
        output_fn("\nWarning: fewer than 5 valid recordings — using safe defaults.");
        return Ok(EnrollResult {
            vad_threshold: 0.01,
            min_silence_ms: 500,
        });
    }

    let vad_threshold = (percentile(&mut noise_floors, 95.0) * 3.0).clamp(0.001, 0.1);
    let min_silence_ms = (percentile(&mut pause_durations, 95.0) as u32).clamp(500, 5000);

    output_fn("\nDerived settings:");
    output_fn(&format!("  vad_threshold   = {vad_threshold:.4}"));
    output_fn(&format!("  min_silence_ms  = {min_silence_ms}"));

    Ok(EnrollResult {
        vad_threshold,
        min_silence_ms,
    })
}

/// Append (or replace) `[accessibility]` section in `config_path`.
pub fn write_config(result: &EnrollResult, config_path: &std::path::Path) -> anyhow::Result<()> {
    if let Some(parent) = config_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let existing = if config_path.exists() {
        std::fs::read_to_string(config_path)?
    } else {
        String::new()
    };

    // Strip any existing [accessibility] section.
    let stripped = strip_toml_section(&existing, "accessibility");

    let new_section = format!(
        "\n[accessibility]\nvad_threshold = {:.4}\nmin_silence_ms = {}\n",
        result.vad_threshold, result.min_silence_ms,
    );

    std::fs::write(config_path, stripped + &new_section)?;
    Ok(())
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/// Compute noise floor and trailing pause from a single recording.
fn analyse_sample(audio: &[f32], sample_rate: u32) -> (f32, f32) {
    let noise_window = (0.5 * sample_rate as f32) as usize;
    let frame_size = (0.05 * sample_rate as f32) as usize;

    let noise_floor = if audio.len() > noise_window {
        mean_abs(&audio[..noise_window])
    } else {
        mean_abs(audio)
    };

    let silence_threshold = (noise_floor * 2.0).max(0.005);
    let trailing_frames = audio
        .chunks(frame_size.max(1))
        .rev()
        .take_while(|frame| mean_abs(frame) < silence_threshold)
        .count();
    let pause_ms = trailing_frames as f32 * 50.0;

    (noise_floor, pause_ms)
}

fn mean_abs(data: &[f32]) -> f32 {
    if data.is_empty() {
        return 0.0;
    }
    data.iter().map(|x| x.abs()).sum::<f32>() / data.len() as f32
}

fn percentile(data: &mut [f32], p: f64) -> f32 {
    if data.is_empty() {
        return 0.0;
    }
    data.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let idx = ((p / 100.0) * (data.len() - 1) as f64).round() as usize;
    data[idx.min(data.len() - 1)]
}

/// Remove a named `[section]` and its key-value pairs from a TOML string.
fn strip_toml_section(toml: &str, section: &str) -> String {
    let header = format!("[{section}]");
    let mut lines: Vec<&str> = Vec::new();
    let mut in_section = false;
    for line in toml.lines() {
        let trimmed = line.trim();
        if trimmed == header {
            in_section = true;
        } else if trimmed.starts_with('[') && !trimmed.starts_with("[[") {
            in_section = false;
            lines.push(line);
        } else if !in_section {
            lines.push(line);
        }
    }
    let mut result = lines.join("\n");
    if !result.is_empty() && !result.ends_with('\n') {
        result.push('\n');
    }
    result
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;

    fn make_recorder(noise_rms: f32, speech_rms: f32, trailing_ms: f32) -> MockRecorder {
        MockRecorder::synthesise(16000, 3.0, noise_rms, speech_rms, trailing_ms)
    }

    #[test]
    fn wizard_derives_threshold_from_noise_floor() {
        // All 20 sentences: noise_rms=0.002, so percentile(95) ≈ 0.002
        // vad_threshold = 0.002 * 3 = 0.006
        let recorder = make_recorder(0.002, 0.05, 100.0);
        let mut messages = Vec::new();
        let result = run_wizard(&recorder, |m| messages.push(m.to_string())).unwrap();

        assert!((result.vad_threshold - 0.006).abs() < 0.001);
        assert!(result.min_silence_ms >= 500);
    }

    #[test]
    fn wizard_falls_back_to_defaults_on_short_recordings() {
        struct TinyRecorder;
        impl AudioRecorder for TinyRecorder {
            fn record_seconds(&self, _d: f32) -> anyhow::Result<(Vec<f32>, u32)> {
                Ok((vec![0.0; 100], 16000)) // less than 1 s
            }
        }
        let result = run_wizard(&TinyRecorder, |_| {}).unwrap();
        assert_eq!(result.vad_threshold, 0.01);
        assert_eq!(result.min_silence_ms, 500);
    }

    #[test]
    fn wizard_clamps_threshold_to_range() {
        // Very loud noise floor → raw threshold could exceed 0.1
        let recorder = make_recorder(0.04, 0.5, 0.0);
        let result = run_wizard(&recorder, |_| {}).unwrap();
        assert!(result.vad_threshold <= 0.1);
        assert!(result.vad_threshold >= 0.001);
    }

    #[test]
    fn write_config_creates_file() {
        let tmp = NamedTempFile::new().unwrap();
        let result = EnrollResult {
            vad_threshold: 0.0123,
            min_silence_ms: 750,
        };
        write_config(&result, tmp.path()).unwrap();
        let content = std::fs::read_to_string(tmp.path()).unwrap();
        assert!(content.contains("[accessibility]"));
        assert!(content.contains("vad_threshold"));
        assert!(content.contains("min_silence_ms = 750"));
    }

    #[test]
    fn write_config_replaces_existing_section() {
        let tmp = NamedTempFile::new().unwrap();
        std::fs::write(
            tmp.path(),
            "[daemon]\nport = 9876\n\n[accessibility]\nvad_threshold = 0.99\n",
        )
        .unwrap();
        let result = EnrollResult {
            vad_threshold: 0.005,
            min_silence_ms: 600,
        };
        write_config(&result, tmp.path()).unwrap();
        let content = std::fs::read_to_string(tmp.path()).unwrap();
        assert!(content.contains("[daemon]"));
        assert!(!content.contains("0.99"), "old value should be gone");
        assert!(content.contains("vad_threshold = 0.0050"));
    }

    #[test]
    fn analyse_sample_extracts_noise_floor() {
        // First 8000 samples (0.5 s at 16000 Hz): 0.01; rest: 0.1
        let mut audio = vec![0.01f32; 8000];
        audio.extend(vec![0.1f32; 8000]);
        let (nf, _) = analyse_sample(&audio, 16000);
        assert!((nf - 0.01).abs() < 0.001);
    }

    #[test]
    fn percentile_p50_gives_median() {
        let mut data = vec![1.0f32, 2.0, 3.0, 4.0, 5.0];
        assert_eq!(percentile(&mut data, 50.0), 3.0);
    }

    #[test]
    fn strip_section_removes_target_preserves_others() {
        let toml =
            "[server]\nhost = \"localhost\"\n\n[accessibility]\nval = 1\n\n[debug]\nflag = true\n";
        let stripped = strip_toml_section(toml, "accessibility");
        assert!(stripped.contains("[server]"));
        assert!(stripped.contains("[debug]"));
        assert!(!stripped.contains("[accessibility]"));
        assert!(!stripped.contains("val = 1"));
    }
}
