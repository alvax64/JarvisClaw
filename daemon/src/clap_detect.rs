//! Double-clap detector — pure signal processing, no allocations in hot path.
//!
//! A clap is a transient: sharp energy spike that decays within one frame.
//! We detect two spikes within a time window (100-500ms apart).

use std::time::Instant;

/// Audio format constants — must match pw-cat config.
pub const RATE: u32 = 16000;
pub const CHANNELS: u32 = 1;
pub const SAMPLE_WIDTH: usize = 2; // 16-bit signed LE
pub const FRAME_MS: u32 = 20;
pub const FRAME_SAMPLES: usize = (RATE * FRAME_MS / 1000) as usize; // 320
pub const FRAME_BYTES: usize = FRAME_SAMPLES * SAMPLE_WIDTH; // 640

// Detection timing
const CLAP_MIN_GAP: f64 = 0.10; // seconds — faster is one noise event
const CLAP_MAX_GAP: f64 = 0.50; // seconds — slower is two separate events

// Adaptive noise floor
const NOISE_ALPHA: f64 = 0.02;
const NOISE_MULTIPLIER: f64 = 3.0;

/// RMS energy of a 16-bit LE PCM frame. No heap allocation.
#[inline]
pub fn frame_rms(data: &[u8]) -> u16 {
    let n = data.len() / SAMPLE_WIDTH;
    if n == 0 {
        return 0;
    }
    let mut sum: i64 = 0;
    for i in 0..n {
        let sample = i16::from_le_bytes([data[i * 2], data[i * 2 + 1]]) as i64;
        sum += sample * sample;
    }
    ((sum / n as i64) as f64).sqrt() as u16
}

pub struct ClapDetector {
    threshold: u16,
    noise_floor: f64,
    cooldown: f64,
    // first_spike == Some means armed (saw first clap, waiting for second)
    first_spike: Option<Instant>,
    last_trigger: Option<Instant>,
}

impl ClapDetector {
    pub fn new(threshold: u16, cooldown: f64) -> Self {
        Self {
            threshold,
            noise_floor: 200.0,
            cooldown,
            first_spike: None,
            last_trigger: None,
        }
    }

    /// Process one audio frame. Returns true on double-clap detection.
    #[inline]
    pub fn feed(&mut self, frame: &[u8]) -> bool {
        let rms = frame_rms(frame);
        let now = Instant::now();

        // Cooldown — ignore everything right after a trigger
        if let Some(ref t) = self.last_trigger {
            if now.duration_since(*t).as_secs_f64() < self.cooldown {
                return false;
            }
        }

        // Update noise floor from quiet frames
        if rms < self.threshold {
            self.noise_floor += NOISE_ALPHA * (rms as f64 - self.noise_floor);
        }

        // Adaptive threshold
        let effective = (self.threshold as f64).max(self.noise_floor * NOISE_MULTIPLIER);
        if (rms as f64) < effective {
            return false;
        }

        // Got a spike — check against first_spike state
        let Some(ref first) = self.first_spike else {
            // First spike — arm
            self.first_spike = Some(now);
            return false;
        };

        let gap = now.duration_since(*first).as_secs_f64();

        if gap < CLAP_MIN_GAP {
            // Same noise event, update timestamp
            self.first_spike = Some(now);
            return false;
        }

        if gap > CLAP_MAX_GAP {
            // Too slow — reset, treat as new first clap
            self.first_spike = Some(now);
            return false;
        }

        // Double clap confirmed
        self.first_spike = None;
        self.last_trigger = Some(now);
        true
    }

    pub fn noise_floor(&self) -> f64 {
        self.noise_floor
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;
    use std::time::Duration;

    fn make_frame(amplitude: i16) -> Vec<u8> {
        let mut buf = vec![0u8; FRAME_BYTES];
        for i in 0..FRAME_SAMPLES {
            let bytes = amplitude.to_le_bytes();
            buf[i * 2] = bytes[0];
            buf[i * 2 + 1] = bytes[1];
        }
        buf
    }

    #[test]
    fn silence_does_not_trigger() {
        let mut d = ClapDetector::new(3000, 1.5);
        let silence = make_frame(100);
        for _ in 0..50 {
            assert!(!d.feed(&silence));
        }
    }

    #[test]
    fn double_clap_triggers() {
        let mut d = ClapDetector::new(3000, 1.5);
        let clap = make_frame(5000);

        assert!(!d.feed(&clap));
        thread::sleep(Duration::from_millis(200));
        assert!(d.feed(&clap));

        // Cooldown — should not trigger
        assert!(!d.feed(&clap));
    }

    #[test]
    fn single_clap_no_trigger() {
        let mut d = ClapDetector::new(3000, 1.5);
        let clap = make_frame(5000);

        assert!(!d.feed(&clap));
        thread::sleep(Duration::from_millis(600));
        // Past max gap — new first clap, no trigger
        assert!(!d.feed(&clap));
    }

    #[test]
    fn rms_calculation() {
        let frame = make_frame(1000);
        assert_eq!(frame_rms(&frame), 1000);

        let frame = make_frame(0);
        assert_eq!(frame_rms(&frame), 0);

        // Negative amplitude — RMS is always positive
        let frame = make_frame(-1000);
        assert_eq!(frame_rms(&frame), 1000);
    }
}
