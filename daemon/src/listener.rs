//! PipeWire audio listener — spawns pw-cat, feeds ClapDetector.
//!
//! Output contract:
//!   stdout — "CLAP\n" per detection (machine-readable, pipeable)
//!   stderr — diagnostics, only with --verbose or --watch

use std::io::{self, Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use signal_hook::consts::{SIGINT, SIGTERM};
use signal_hook::flag;

use crate::clap_detect::{ClapDetector, CHANNELS, FRAME_BYTES, FRAME_MS, RATE, frame_rms};

struct AudioStream {
    child: Child,
    pipe: std::process::ChildStdout,
    running: Arc<AtomicBool>,
}

impl AudioStream {
    fn open(device: Option<&str>) -> Self {
        let running = Arc::new(AtomicBool::new(true));
        flag::register(SIGINT, Arc::clone(&running)).expect("register SIGINT");
        flag::register(SIGTERM, Arc::clone(&running)).expect("register SIGTERM");

        let mut cmd = Command::new("pw-cat");
        cmd.arg("--record");
        if let Some(dev) = device {
            if dev != "default" {
                cmd.arg(format!("--target={dev}"));
            }
        }
        cmd.args(["--rate", &RATE.to_string()]);
        cmd.args(["--channels", &CHANNELS.to_string()]);
        cmd.args(["--format", "s16"]);
        cmd.arg("-");
        cmd.stdout(Stdio::piped());
        cmd.stderr(Stdio::null());

        let mut child = cmd.spawn().expect("Failed to spawn pw-cat. Is PipeWire running?");
        let pipe = child.stdout.take().expect("pw-cat stdout");

        Self { child, pipe, running }
    }

    fn is_running(&self) -> bool {
        self.running.load(Ordering::Relaxed)
    }

    fn read_frame(&mut self, buf: &mut [u8; FRAME_BYTES]) -> bool {
        self.pipe.read_exact(buf).is_ok()
    }
}

impl Drop for AudioStream {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Block forever, reading audio. Writes "CLAP\n" to stdout on detection.
pub fn listen(threshold: u16, device: Option<&str>, cooldown: f64, verbose: bool) {
    let mut stream = AudioStream::open(device);
    let mut detector = ClapDetector::new(threshold, cooldown);
    let mut buf = [0u8; FRAME_BYTES];
    let mut out = io::stdout().lock();

    if verbose {
        eprintln!(
            "jarvis-listen: threshold={} cooldown={:.1}s frame={}ms",
            threshold, cooldown, FRAME_MS
        );
    }

    while stream.is_running() {
        if !stream.read_frame(&mut buf) {
            if verbose {
                eprintln!("jarvis-listen: stream ended");
            }
            break;
        }

        if detector.feed(&buf) {
            let _ = out.write_all(b"CLAP\n");
            let _ = out.flush();

            if verbose {
                eprintln!(
                    "jarvis-listen: detected (noise_floor={:.0})",
                    detector.noise_floor()
                );
            }
        }
    }
}

/// Live RMS monitor — writes to stderr, never touches stdout.
pub fn watch(device: Option<&str>, threshold: u16) {
    let mut stream = AudioStream::open(device);
    let mut buf = [0u8; FRAME_BYTES];
    let mut peak: u16 = 0;
    let bar_full: &str = "############################################################"; // 60 chars

    eprintln!("jarvis-listen --watch: live RMS monitor. Ctrl-C to stop.");
    eprintln!("Ambient: 100-500 | Claps: 2000+ | Current threshold: {threshold}\n");

    while stream.is_running() {
        if !stream.read_frame(&mut buf) {
            break;
        }
        let rms = frame_rms(&buf);
        if rms > peak {
            peak = rms;
        }
        let over = if rms >= threshold { " <<< SPIKE" } else { "" };
        let bar_len = (rms / 50).min(60) as usize;
        eprint!("\r  RMS: {rms:5}  peak: {peak:5}  {:<60}{over}", &bar_full[..bar_len]);
    }

    eprintln!("\n\nPeak: {peak}  Suggested --threshold: {}", (peak / 2).max(1500));
}
