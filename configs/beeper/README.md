# Beeper Bridge Manager (`bbctl`) on Tinarchy

Beeper Bridge Manager is installed on Tinarchy to run and orchestrate self-hosted bridges for Beeper (Matrix).

- **Binary Path**: `/home/tin/.local/bin/bbctl`
- **Data & Bridges Directory**: `~/.local/share/bbctl`
- **Config Path**: `~/.config/bbctl/config.json`
- **Systemd Template**: `/etc/systemd/system/bbctl@.service` (linked from `configs/systemd/bbctl@.service`)

---

## 🚀 Initial Login

Authenticate your server with your Beeper account:

```bash
bbctl login
# Or using username/password:
bbctl login-password
```

Verify your login status:
```bash
bbctl whoami
```

---

## 🌉 Running Bridges as Systemd Services

You can run any bridge permanently in the background via the systemd template:

```bash
# Example: Running WhatsApp self-hosted bridge
sudo systemctl enable --now bbctl@sh-whatsapp

# Example: Running Telegram bridge
sudo systemctl enable --now bbctl@sh-telegram

# Check status of a bridge
sudo systemctl status bbctl@sh-whatsapp

# Stream logs of a bridge
journalctl -u bbctl@sh-whatsapp -f
```

---

## 📋 Supported Official Bridges

| Bridge | Identifier / Name Example |
| :--- | :--- |
| **Telegram** | `sh-telegram` |
| **WhatsApp** | `sh-whatsapp` |
| **Signal** | `sh-signal` |
| **Discord** | `sh-discord` |
| **Slack** | `sh-slack` |
| **Google Messages / RCS** | `sh-gmessages` |
| **Google Chat** | `sh-googlechat` |
| **Meta / Instagram / FB** | `sh-meta` |
| **Twitter / X** | `sh-twitter` |
| **Bluesky** | `sh-bluesky` |
| **IRC / Heisenbridge** | `sh-irc` |
| **LinkedIn** | `sh-linkedin` |

*To configure bridge settings after launching, start a direct message with `@<name>bot:beeper.local` in Beeper.*
