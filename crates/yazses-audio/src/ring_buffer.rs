/// Fixed-capacity ring buffer for float32 audio samples.
///
/// Retains the last `capacity` samples so callers can prepend pre-speech
/// padding to each recording. Port of `src/yazses/audio/padding.py`.
///
/// People with hypophonia (ALS, Parkinson's) often have delayed voice onset:
/// their speech starts soft and ramps up. Without pre-speech padding the first
/// 0.1–0.5 s of the utterance is lost.
#[derive(Debug)]
pub struct PaddingBuffer {
    buf: Vec<f32>,
    head: usize,
    filled: bool,
}

impl PaddingBuffer {
    /// `padding_ms`: how many milliseconds of audio to retain.
    /// `sample_rate`: samples per second (typically 16 000).
    pub fn new(padding_ms: u32, sample_rate: u32) -> Self {
        let capacity = (padding_ms as usize * sample_rate as usize) / 1000;
        Self {
            buf: vec![0.0f32; capacity],
            head: 0,
            filled: false,
        }
    }

    pub fn capacity(&self) -> usize {
        self.buf.len()
    }

    /// Push a chunk of samples into the ring buffer.
    pub fn push(&mut self, chunk: &[f32]) {
        let cap = self.buf.len();
        if cap == 0 || chunk.is_empty() {
            return;
        }
        let n = chunk.len();
        if n >= cap {
            // Chunk larger than the buffer — keep only the last `cap` samples.
            self.buf.copy_from_slice(&chunk[n - cap..]);
            self.head = 0;
            self.filled = true;
            return;
        }
        let end = self.head + n;
        if end <= cap {
            self.buf[self.head..end].copy_from_slice(chunk);
        } else {
            let split = cap - self.head;
            self.buf[self.head..].copy_from_slice(&chunk[..split]);
            self.buf[..end - cap].copy_from_slice(&chunk[split..]);
            self.filled = true;
        }
        self.head = end % cap;
        if self.head == 0 {
            self.filled = true;
        }
    }

    /// Drain the ring buffer into a contiguous `Vec<f32>` (oldest → newest).
    ///
    /// Returns an empty vec if no samples have been pushed yet.
    pub fn get(&self) -> Vec<f32> {
        let cap = self.buf.len();
        if cap == 0 {
            return Vec::new();
        }
        if !self.filled {
            if self.head == 0 {
                return Vec::new();
            }
            return self.buf[..self.head].to_vec();
        }
        // Re-order: head..end then 0..head.
        let mut out = Vec::with_capacity(cap);
        out.extend_from_slice(&self.buf[self.head..]);
        out.extend_from_slice(&self.buf[..self.head]);
        out
    }

    /// Return `[padding..., audio...]` with the buffered pre-speech
    /// samples prepended to `audio`.
    pub fn prepend(&self, audio: &[f32]) -> Vec<f32> {
        let pad = self.get();
        let mut out = Vec::with_capacity(pad.len() + audio.len());
        out.extend_from_slice(&pad);
        out.extend_from_slice(audio);
        out
    }

    pub fn clear(&mut self) {
        self.buf.fill(0.0);
        self.head = 0;
        self.filled = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_buffer_returns_empty() {
        let buf = PaddingBuffer::new(200, 16000);
        assert!(buf.get().is_empty());
    }

    #[test]
    fn partial_fill_returns_what_was_pushed() {
        let mut buf = PaddingBuffer::new(1000, 1000); // 1 000 samples capacity
        buf.push(&[1.0, 2.0, 3.0]);
        assert_eq!(buf.get(), vec![1.0, 2.0, 3.0]);
    }

    #[test]
    fn overflow_wraps_and_returns_oldest_first() {
        // 4-sample capacity.
        let mut buf = PaddingBuffer::new(4, 1000); // capacity = 4
        buf.push(&[1.0, 2.0, 3.0, 4.0]); // fills exactly
        buf.push(&[5.0, 6.0]); // overwrites 1,2
        assert_eq!(buf.get(), vec![3.0, 4.0, 5.0, 6.0]);
    }

    #[test]
    fn chunk_larger_than_capacity_keeps_last_n() {
        let mut buf = PaddingBuffer::new(3, 1000); // capacity = 3
        buf.push(&[10.0, 20.0, 30.0, 40.0, 50.0]);
        assert_eq!(buf.get(), vec![30.0, 40.0, 50.0]);
    }

    #[test]
    fn prepend_adds_padding_before_audio() {
        let mut buf = PaddingBuffer::new(2, 1000); // capacity = 2
        buf.push(&[1.0, 2.0]);
        let out = buf.prepend(&[3.0, 4.0, 5.0]);
        assert_eq!(out, vec![1.0, 2.0, 3.0, 4.0, 5.0]);
    }

    #[test]
    fn clear_resets_state() {
        let mut buf = PaddingBuffer::new(200, 16000);
        buf.push(&[1.0, 2.0, 3.0]);
        buf.clear();
        assert!(buf.get().is_empty());
    }
}
