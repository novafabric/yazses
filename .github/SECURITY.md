# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.x (Rust) | ✅ |
| 0.4.x (Python) | ✅ |
| < 0.4 | ❌ |

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Please report security issues by emailing **mohsen.seyedkazemi@gmail.com** with the subject line `[YazSes Security]`. Include:

- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

You will receive a response within 72 hours. We will work with you to understand and resolve the issue before any public disclosure.

## Scope

YazSes runs entirely on-device with no cloud components by default. Security concerns most relevant to this project:

- Audio data handling and local storage
- Encrypted corpus / memory store (AES-256-GCM)
- IPC socket permissions (Unix socket / named pipe)
- SSH remote injection path (`yazses remote`)
- Text injection backends (xdotool, ydotool, wtype)
