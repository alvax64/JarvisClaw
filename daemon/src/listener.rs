//! PipeWire audio listener — spawns pw-cat, feeds ClapDetector.
//!
//! Output contract:
//!   stdout — "CLAP\n" per detection (machine-readable, pipeable)
//!   stderr — diagnostics, only with --verbose or --watch

use std::io::{self, Read, Write};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use signal_hook::consts::{SIGINT, SIGTERM};
use signal_hook::flag;

use crate::clap_detect::{ClapDetector, CHANNELS, FRAME_BYTES, FRAME_MS, RATE, frame_rms};

fn build_pw_cmd(device: Option<&str>) -> Command {
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
    cmd
}

/// Block forever, reading audio. Writes "CLAP\n" to stdout on detection.
pub fn listen(threshold: i16, device: Option<&str>, cooldown: f64, verbose: bool) {
    let running = Arc::new(AtomicBool::new(true));
    flag::register(SIGINT, Arc::clone(&running)).expect("register SIGINT");
    flag::register(SIGTERM, Arc::clone(&running)).expect("register SIGTERM");

    let mut child = build_pw_cmd(device)
        .spawn()
        .expect("Failed to spawn pw-cat. Is PipeWire running?");

    let mut pipe = child.stdout.take().expect("pw-cat stdout");
    let mut detector = ClapDetector::new(threshold, cooldown);
    let mut buf = [0u8; FRAME_BYTES];
    let mut out = io::stdout().lock();

    if verbose {
        eprintln!(
            "jarvis-listen: threshold={} cooldown={:.1}s frame={}ms",
            threshold, cooldown, FRAME_MS
        );
    }

    while running.load(Ordering::Relaxed) {
        match pipe.read_exact(&mut buf) {
            Ok(()) => {}
            Err(e) => {
                if verbose {
                    eprintln!("jarvis-listen: stream ended: {e}");
                }
                break;
            }
        }

        if detector.feed(&buf) {
            // The only thing that goes to stdout
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

    let _ = child.kill();
    let _ = child.wait();
}

/// Live RMS monitor — writes to stderr, never touches stdout.
pub fn watch(device: Option<&str>, threshold: i16) {
    let running = Arc::new(AtomicBool::new(true));
    flag::register(SIGINT, Arc::clone(&running)).expect("register SIGINT");

    let mut child = build_pw_cmd(device)
        .spawn()
        .expect("Failed to spawn pw-cat");

    let mut pipe = child.stdout.take().expect("pw-cat stdout");
    let mut buf = [0u8; FRAME_BYTES];
    let mut peak: i16 = 0;

    eprintln!("jarvis-listen --watch: live RMS monitor. Ctrl-C to stop.");
    eprintln!("Ambient: 100-500 | Claps: 2000+ | Current threshold: {threshold}\n");

    while running.load(Ordering::Relaxed) {
        match pipe.read_exact(&mut buf) {
            Ok(()) => {}
            Err(_) => break,
        }
        let rms = frame_rms(&buf);
        if rms > peak {
            peak = rms;
        }
        let over = if rms >= threshold { " <<< SPIKE" } else { "" };
        let bar_len = (rms / 50).min(60) as usize;
        let bar: String = "#".repeat(bar_len);
        eprint!("\r  RMS: {rms:5}  peak: {peak:5}  {bar:<60}{over}");
    }

    eprintln!("\n\nPeak: {peak}  Suggested --threshold: {}", (peak / 2).max(1500));
    let _ = child.kill();
    let _ = child.wait();
}
