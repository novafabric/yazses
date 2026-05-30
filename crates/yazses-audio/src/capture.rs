use anyhow::Context;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use tokio::sync::mpsc;
use tracing::{debug, info, warn};

/// Audio frame delivered over the channel — f32 mono samples at `sample_rate`.
#[derive(Debug, Clone)]
pub struct AudioFrame {
    pub samples: Vec<f32>,
    pub sample_rate: u32,
}

/// cpal-based audio capture.
///
/// `start()` opens the default input device and begins streaming `AudioFrame`
/// chunks into the supplied `mpsc::Sender`. The sender is dropped when the
/// internal cpal stream is stopped via `stop()`.
pub struct AudioCapture {
    sample_rate: u32,
    // Held to keep the stream alive; dropped on stop().
    stream: Option<cpal::Stream>,
}

impl AudioCapture {
    pub fn new(sample_rate: u32) -> Self {
        Self {
            sample_rate,
            stream: None,
        }
    }

    /// Open the default microphone and start streaming frames.
    ///
    /// The sender receives `AudioFrame` with mono f32 samples resampled (or
    /// natively at) `sample_rate`. Call `stop()` to terminate.
    pub fn start(&mut self, tx: mpsc::Sender<AudioFrame>) -> anyhow::Result<()> {
        let host = cpal::default_host();
        let device = host
            .default_input_device()
            .context("no default audio input device")?;

        let device_name = device
            .description()
            .map(|d| d.name().to_owned())
            .unwrap_or_else(|_| "unknown".into());
        info!(%device_name, sample_rate = self.sample_rate, "audio capture starting");

        let wanted_rate = self.sample_rate;

        // Prefer the device's native config closest to our target rate.
        let config = device
            .supported_input_configs()
            .context("query input configs")?
            .filter(|c| c.channels() == 1 || c.channels() == 2)
            .find(|c| c.min_sample_rate() <= wanted_rate && c.max_sample_rate() >= wanted_rate)
            .map(|c| c.with_sample_rate(wanted_rate))
            .or_else(|| device.default_input_config().ok())
            .context("no suitable input config")?;

        let actual_rate = config.sample_rate();
        let channels = config.channels() as usize;
        if actual_rate != wanted_rate {
            warn!(
                actual_rate,
                wanted_rate, "device does not support target sample rate; using actual"
            );
        }

        let err_fn = |e: cpal::StreamError| warn!("audio stream error: {e}");

        let stream = match config.sample_format() {
            cpal::SampleFormat::F32 => device.build_input_stream(
                &config.into(),
                move |data: &[f32], _| {
                    let samples = mono_mix(data, channels);
                    let _ = tx.try_send(AudioFrame {
                        samples,
                        sample_rate: actual_rate,
                    });
                },
                err_fn,
                None,
            )?,
            cpal::SampleFormat::I16 => device.build_input_stream(
                &config.into(),
                move |data: &[i16], _| {
                    let f32_data: Vec<f32> =
                        data.iter().map(|s| *s as f32 / i16::MAX as f32).collect();
                    let samples = mono_mix(&f32_data, channels);
                    let _ = tx.try_send(AudioFrame {
                        samples,
                        sample_rate: actual_rate,
                    });
                },
                err_fn,
                None,
            )?,
            cpal::SampleFormat::U16 => device.build_input_stream(
                &config.into(),
                move |data: &[u16], _| {
                    let f32_data: Vec<f32> = data
                        .iter()
                        .map(|s| (*s as f32 / u16::MAX as f32) * 2.0 - 1.0)
                        .collect();
                    let samples = mono_mix(&f32_data, channels);
                    let _ = tx.try_send(AudioFrame {
                        samples,
                        sample_rate: actual_rate,
                    });
                },
                err_fn,
                None,
            )?,
            // U8 PCM: 0=min, 128=silence, 255=max → map to [-1.0, 1.0]
            cpal::SampleFormat::U8 => device.build_input_stream(
                &config.into(),
                move |data: &[u8], _| {
                    let f32_data: Vec<f32> = data
                        .iter()
                        .map(|s| (*s as f32 - 128.0) / 128.0)
                        .collect();
                    let samples = mono_mix(&f32_data, channels);
                    let _ = tx.try_send(AudioFrame {
                        samples,
                        sample_rate: actual_rate,
                    });
                },
                err_fn,
                None,
            )?,
            // I8 PCM: signed 8-bit → map to [-1.0, 1.0]
            cpal::SampleFormat::I8 => device.build_input_stream(
                &config.into(),
                move |data: &[i8], _| {
                    let f32_data: Vec<f32> = data
                        .iter()
                        .map(|s| *s as f32 / i8::MAX as f32)
                        .collect();
                    let samples = mono_mix(&f32_data, channels);
                    let _ = tx.try_send(AudioFrame {
                        samples,
                        sample_rate: actual_rate,
                    });
                },
                err_fn,
                None,
            )?,
            fmt => anyhow::bail!("unsupported sample format: {fmt:?}"),
        };

        stream.play().context("starting audio stream")?;
        debug!("audio stream playing");
        self.stream = Some(stream);
        Ok(())
    }

    /// Stop audio capture and release the device.
    pub fn stop(&mut self) {
        if self.stream.take().is_some() {
            info!("audio capture stopped");
        }
    }
}

impl Drop for AudioCapture {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Down-mix interleaved multi-channel audio to mono by averaging channels.
fn mono_mix(data: &[f32], channels: usize) -> Vec<f32> {
    if channels == 1 {
        return data.to_vec();
    }
    data.chunks(channels)
        .map(|frame| frame.iter().sum::<f32>() / channels as f32)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::mono_mix;

    #[test]
    fn mono_passthrough() {
        let data = vec![0.1, 0.2, 0.3];
        assert_eq!(mono_mix(&data, 1), vec![0.1, 0.2, 0.3]);
    }

    #[test]
    fn stereo_to_mono_averages() {
        // Stereo: [L1, R1, L2, R2] → [(L1+R1)/2, (L2+R2)/2]
        let data = vec![0.0f32, 1.0, 0.5, 0.5];
        let out = mono_mix(&data, 2);
        assert!((out[0] - 0.5).abs() < 1e-6);
        assert!((out[1] - 0.5).abs() < 1e-6);
    }
}
