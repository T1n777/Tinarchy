# Beeper Bridge Manager (`bbctl`) on Tinarchy

Beeper Bridge Manager is installed on Tinarchy to run and orchestrate self-hosted bridges for Beeper (Matrix).

- **Binary Path**: `~/.local/bin/bbctl`
- **CLI Helper**: `beeper` / `~/.local/bin/beeper` (`configs/scripts/beeper-ctl.sh`)
- **Data & Bridges Directory**: `~/.local/share/bbctl`
- **Config Path**: `~/.config/bbctl/config.json`
- **Systemd Template**: `/etc/systemd/system/bbctl@.service` (linked from `configs/systemd/bbctl@.service`)
- **Web Guide & Dashboard**: `https://<tailscale-domain>/beeper` (`public/guides/beeper.html`)

## 🚀 Initial Login

Authenticate your server with your Beeper account:

```bash
beeper login
# Or directly with bbctl:
bbctl login
```

Verify your login status:
```bash
beeper whoami
# Or:
bbctl whoami
```

## 🌉 Quick Management via `beeper` CLI

Use the built-in control script for easy management:

```bash
# Check status of account and running bridges
beeper status

# Start and enable any bridge on boot
beeper start sh-whatsapp
beeper start sh-discord
beeper start sh-instagram

# Stop or restart a bridge
beeper stop sh-whatsapp
beeper restart sh-whatsapp

# Live streaming logs
beeper logs sh-whatsapp

# List all available bridge identifiers
beeper bridges
```

## ⚙️ Running Bridges Directly via Systemd

Bridges run as isolated background systemd services via the template unit:

```bash
# Start and enable bridges
sudo systemctl enable --now bbctl@sh-whatsapp
sudo systemctl enable --now bbctl@sh-discord
sudo systemctl enable --now bbctl@sh-instagram

# Check service status
sudo systemctl status bbctl@sh-whatsapp

# Stream logs
journalctl -u bbctl@sh-whatsapp -f
```

## 📋 Supported Official Bridges & Pairing Instructions

| Bridge | Identifier | Pairing Bot in Beeper | Pairing Command / Action |
| :--- | :--- | :--- | :--- |
| **WhatsApp** | `sh-whatsapp` | `@sh-whatsappbot:beeper.local` | Send `login` ➔ Scan QR in WhatsApp (Linked Devices) |
| **Discord** | `sh-discord` | `@sh-discordbot:beeper.local` | Send `login-qr` ➔ Scan QR in Discord mobile app |
| **Instagram** | `sh-instagram` | `@sh-instagrambot:beeper.local` | Send `login <username>` ➔ Enter password / 2FA code |
| **Telegram** | `sh-telegram` | `@telegrambot:beeper.local` | Send `login <phone>` ➔ Enter Telegram verification code |
| **Signal** | `sh-signal` | `@signalbot:beeper.local` | Send `link` ➔ Scan QR in Signal (Linked Devices) |
| **Google Messages (RCS)** | `sh-gmessages` | `@gmessagesbot:beeper.local` | Send `login` ➔ Pair device in Google Messages |
| **Slack** | `sh-slack` | `@slackbot:beeper.local` | Send `login` ➔ Follow OAuth browser link |
| **Google Chat** | `sh-googlechat` | `@googlechatbot:beeper.local` | Send `login` ➔ Follow authorization link |
| **Meta / FB Messenger** | `sh-meta` | `@metabot:beeper.local` | Send `login <username>` ➔ Enter password |
| **Twitter / X** | `sh-twitter` | `@twitterbot:beeper.local` | Send `login` ➔ Follow authorization link |
| **Bluesky** | `sh-bluesky` | `@blueskybot:beeper.local` | Send `login <handle>` ➔ Enter app password |
| **LinkedIn** | `sh-linkedin` | `@linkedinbot:beeper.local` | Send `login` ➔ Follow authorization link |

*After launching a bridge service, open Beeper on your phone or desktop and message the corresponding bot to complete authentication.*
