# JDownloader 2 Headless on Tinarchy

JDownloader 2 is deployed in headless mode under `~/jdownloader/` and integrated directly into the Tinarchy Server Dashboard under **Automation & Downloads**.

- **Installation Directory**: `~/jdownloader` (e.g. `/home/tin/jdownloader` or `/home/pineapple/jdownloader`)
- **Default Downloads Folder**: `~/storage/Downloads` or `~/drive/Media/Downloads`
- **Systemd Unit**: `/etc/systemd/system/jdownloader.service` (linked from `configs/systemd/jdownloader.service`)
- **Remote Web Portal**: [my.jdownloader.org](https://my.jdownloader.org)

## 🚀 Quick Management CLI

Use the built-in helper command `jdownloader` from any shell:

```bash
# Check status
jdownloader status

# Install / bootstrap JDownloader.jar
jdownloader install

# Setup MyJDownloader credentials (email & password)
jdownloader login

# Start / Stop / Restart background service
jdownloader start
jdownloader stop
jdownloader restart

# Stream service logs
jdownloader logs

# Run interactively in the terminal (for troubleshooting or manual captcha prompts)
jdownloader console
```

## ⚙️ Configuration Files (`~/jdownloader/cfg/`)

- `org.jdownloader.api.myjdownloader.MyJDownloaderSettings.json`: MyJDownloader login credentials and device name (`tinarchy`). File permissions are locked to `0600`.
- `org.jdownloader.settings.GeneralSettings.json`: General settings, including `defaultdownloadfolder` pointing to storage Downloads.
- `org.jdownloader.updatev2.UpdateSettings.json`: Background auto-updating configurations.
- `org.jdownloader.settings.AccountSettings.accounts.ejs`: Saved premium hoster accounts.

## 🔗 Connecting with MyJDownloader

1. Run `jdownloader login` and enter your MyJDownloader email and password.
2. The credentials are encrypted/saved with `0600` permissions and the service restarts automatically.
3. Open [https://my.jdownloader.org](https://my.jdownloader.org) or use the MyJDownloader browser extension or mobile app. Your server will appear as `tinarchy`.

