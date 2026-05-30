// Daemon state machine — mirrors the v0.4 TrayState + core/daemon.py states.
// Transitions are validated; invalid transitions return an error rather than
// silently corrupting state (fail-fast policy per project style guide).

use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum DaemonState {
    Loading,
    Idle,
    Recording,
    Transcribing,
    Injecting,
    RemoteSetup,
    RemoteActive,
    Enrolling,
    Error,
}

impl DaemonState {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Loading => "LOADING",
            Self::Idle => "IDLE",
            Self::Recording => "RECORDING",
            Self::Transcribing => "TRANSCRIBING",
            Self::Injecting => "INJECTING",
            Self::RemoteSetup => "REMOTE_SETUP",
            Self::RemoteActive => "REMOTE_ACTIVE",
            Self::Enrolling => "ENROLLING",
            Self::Error => "ERROR",
        }
    }
}

impl std::fmt::Display for DaemonState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug)]
pub enum DaemonEvent {
    /// All required models loaded successfully.
    ModelsLoaded,
    /// Model load or startup failed.
    LoadFailed(String),
    /// User pressed hold-key (or EMG squeeze threshold met).
    /// `leaked` = characters typed since last hold_end that need backspace cleanup.
    HoldStart { leaked: u32 },
    /// User released hold-key.
    HoldEnd,
    /// Streaming partial transcript (not dispatched in v1.0 — stored for correction).
    PartialTranscript { text: String },
    /// Final transcript ready for LLM.
    TranscriptReady { text: String },
    /// LLM produced a typed tool call.
    ToolCallReady { tool: serde_json::Value },
    /// Dispatcher finished executing the tool call.
    DispatchComplete,
    /// Unrecoverable error in any component.
    ErrorOccurred { message: String },
    /// User or supervisor resolved the error condition.
    ErrorResolved,
    /// Graceful shutdown requested.
    Shutdown,
    /// Calibration wizard started (yazses enroll).
    EnrollStart,
    /// Calibration wizard completed.
    EnrollComplete,
    /// Remote forwarding session started.
    RemoteStart { host: String, port: u16 },
    /// SSH tunnel established.
    RemoteConnected,
    /// Remote session ended.
    RemoteStop,
}

#[derive(Debug, Error)]
pub enum TransitionError {
    #[error("invalid transition: {from} → {event} (not allowed from this state)")]
    Invalid { from: String, event: String },
}

impl DaemonState {
    /// Apply an event, returning the next state.
    /// Returns `Err(TransitionError::Invalid)` for disallowed transitions.
    pub fn apply(&self, event: &DaemonEvent) -> Result<DaemonState, TransitionError> {
        use DaemonEvent::*;
        use DaemonState::*;

        let next = match (self, event) {
            (Loading, ModelsLoaded) => Idle,
            (Loading, LoadFailed(_)) => Error,

            (Idle, HoldStart { .. }) => Recording,
            (Idle, EnrollStart) => Enrolling,
            (Idle, RemoteStart { .. }) => RemoteSetup,
            (Idle, Shutdown) => Idle, // handled externally; stays for clean shutdown

            (Recording, HoldEnd) => Transcribing,
            (Recording, ErrorOccurred { .. }) => Error,

            (Transcribing, ToolCallReady { .. }) => Injecting,
            (Transcribing, TranscriptReady { .. }) => Transcribing, // stays until ToolCall
            (Transcribing, ErrorOccurred { .. }) => Error,

            (Injecting, DispatchComplete) => Idle,
            (Injecting, ErrorOccurred { .. }) => Error,

            (Enrolling, EnrollComplete) => Idle,
            (Enrolling, ErrorOccurred { .. }) => Error,

            (RemoteSetup, RemoteConnected) => RemoteActive,
            (RemoteSetup, ErrorOccurred { .. }) => Error,

            (RemoteActive, RemoteStop) => Idle,
            (RemoteActive, ErrorOccurred { .. }) => Error,

            (Error, ErrorResolved) => Idle,

            // Streaming partials are fire-and-forget; don't change state.
            (_, PartialTranscript { .. }) => return Ok(self.clone()),

            _ => {
                return Err(TransitionError::Invalid {
                    from: self.to_string(),
                    event: format!("{event:?}"),
                })
            }
        };
        Ok(next)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn happy_path_short_command() {
        let s = DaemonState::Loading;
        let s = s.apply(&DaemonEvent::ModelsLoaded).unwrap();
        assert_eq!(s, DaemonState::Idle);

        let s = s.apply(&DaemonEvent::HoldStart { leaked: 0 }).unwrap();
        assert_eq!(s, DaemonState::Recording);

        let s = s.apply(&DaemonEvent::HoldEnd).unwrap();
        assert_eq!(s, DaemonState::Transcribing);

        let s = s
            .apply(&DaemonEvent::ToolCallReady {
                tool: serde_json::json!({"tool": "type_text", "args": {"text": "hello"}}),
            })
            .unwrap();
        assert_eq!(s, DaemonState::Injecting);

        let s = s.apply(&DaemonEvent::DispatchComplete).unwrap();
        assert_eq!(s, DaemonState::Idle);
    }

    #[test]
    fn invalid_transition_returns_err() {
        let s = DaemonState::Idle;
        assert!(s.apply(&DaemonEvent::HoldEnd).is_err());
    }

    #[test]
    fn load_failure_goes_to_error() {
        let s = DaemonState::Loading;
        let s = s
            .apply(&DaemonEvent::LoadFailed("model not found".into()))
            .unwrap();
        assert_eq!(s, DaemonState::Error);
        let s = s.apply(&DaemonEvent::ErrorResolved).unwrap();
        assert_eq!(s, DaemonState::Idle);
    }
}
