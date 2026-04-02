//! jarvis-listen — clap detector for PipeWire.
//!
//! Writes "CLAP\n" to stdout on double-clap detection. That's it.
//! Compose with pipes:
//!
//!   jarvis-listen | while read ts event; do start-assistant; done
//!   jarvis-listen | awk '{print strftime("%T",$1), $2}'
//!   jarvis-listen --watch   # live RMS monitor, no detection
//!
//! Philosophy: do one thing, write to stdout, let the shell compose.

mod clap_detect;
mod listener;

use std::env;
use std::process;

fn usage() {
    eprintln!(
        "Usage: jarvis-listen [OPTIONS]\n\
         \n\
         Detects double-clap patterns from PipeWire audio.\n\
         Writes \"TIMESTAMP CLAP\" to stdout on each detection.\n\
         \n\
         Options:\n\
         \x20 --threshold N    RMS spike threshold (default: 3000)\n\
         \x20 --cooldown SECS  Ignore window after trigger (default: 1.5)\n\
         \x20 --device NAME    PipeWire source (default: system default)\n\
         \x20 --watch          Live RMS monitor (no detection)\n\
         \x20 -v, --verbose    Log detection events to stderr\n\
         \x20 -h, --help       This message"
    );
}

struct Args {
    watch: bool,
    threshold: u16,
    device: Option<String>,
    cooldown: f64,
    verbose: bool,
}

fn parse_args() -> Args {
    let mut args = Args {
        watch: false,
        threshold: 3000,
        device: None,
        cooldown: 1.5,
        verbose: false,
    };

    let argv: Vec<String> = env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        match argv[i].as_str() {
            "--watch" => args.watch = true,
            "--threshold" => {
                i += 1;
                args.threshold = argv.get(i).and_then(|s| s.parse().ok()).unwrap_or_else(|| {
                    eprintln!("--threshold requires a number");
                    process::exit(1);
                });
            }
            "--device" => {
                i += 1;
                args.device = argv.get(i).cloned().or_else(|| {
                    eprintln!("--device requires a value");
                    process::exit(1);
                });
            }
            "--cooldown" => {
                i += 1;
                args.cooldown = argv.get(i).and_then(|s| s.parse().ok()).unwrap_or_else(|| {
                    eprintln!("--cooldown requires a number");
                    process::exit(1);
                });
            }
            "-v" | "--verbose" => args.verbose = true,
            "-h" | "--help" => {
                usage();
                process::exit(0);
            }
            other => {
                eprintln!("Unknown option: {other}");
                usage();
                process::exit(1);
            }
        }
        i += 1;
    }
    args
}

fn main() {
    let args = parse_args();

    // Verify pw-cat exists
    match process::Command::new("pw-cat").arg("--version").output() {
        Ok(out) if out.status.success() => {}
        _ => {
            eprintln!("error: pw-cat not found. Install pipewire.");
            process::exit(1);
        }
    }

    if args.watch {
        listener::watch(args.device.as_deref(), args.threshold);
    } else {
        listener::listen(
            args.threshold,
            args.device.as_deref(),
            args.cooldown,
            args.verbose,
        );
    }
}
