# Server Management Dashboard

![Dashboard Banner](https://via.placeholder.com/1000x200/222222/FFFFFF?text=Tinarchy+Server+Dashboard)

A lightweight, web-based management dashboard for monitoring system resources and managing self-hosted services on a Linux server.

---

## Features
* **Live System Monitoring**: View real-time CPU usage, RAM availability, Disk usage, Uptime, Hostname, and Tailscale IP via a clean web interface.
* **Service Management**: Easily start, stop, and check the status of various systemd services with a single click.
* **Tor Proxy Toggle**: Enable or disable Tor proxy routing for Suwayomi (Tachidesk).
* **Tor Exit Node Routing**: Route all your server's Tailscale traffic through the Tor network dynamically using `iptables`.
* **Role-Based Access Control**: Support for multiple profiles with `admin` and `guest` permissions to restrict access to sensitive controls.

---

## Dependencies

To use all features of the dashboard, ensure your Linux system has the following installed:

### Core Requirements
* **Python 3**: For running the web server backend (`server.py`).
* **systemd**: For managing the dashboard daemon itself, and for interacting with the services you wish to manage.
* **iptables & ip6tables**: Required by the `tor_exit_node.sh` script to manage network routing for the Tor Exit Node feature.
* **tailscale**: Required for reading the VPN IP address and routing traffic via the `tailscale0` network interface.

### Custom Service Management
The dashboard is a flexible framework that can monitor and manage **any systemd service**. It does not require any specific services to function out-of-the-box. 

However, this specific configuration is currently pre-loaded with the following services as examples:
* `suwayomi-server` (Manga library)
* `navidrome` (Music server)
* `tor` (Anonymity proxy)
* `filebrowser` (Web-based file manager)
* `sshd` (SSH access)
* `web-terminal` (Browser terminal)

*(You can freely remove these or add your own in `server.py`!)*

---

## Setup and Installation

### 1. Clone the Repository
Clone the repository into your home directory. **Note:** The included systemd service file expects the repository to be located at `/home/tin/server-dashboard`. If you place it elsewhere or have a different username, you must update the paths in `server-dashboard.service` and `server.py`.

```bash
git clone https://github.com/T1n777/Tinarchy.git /home/tin/server-dashboard
cd /home/tin/server-dashboard
```

### 2. Configure Profiles (Users)
Authentication is role-based. You can manage users in the `USERS` dictionary at the top of the `server.py` file. Each user must have a `password` and a `role` (`admin` or `guest`):

```python
USERS = {
    "tin": {"password": "<ADMIN_PASSWORD>", "role": "admin"},
    "ice.kimi": {"password": "<GUEST_PASSWORD>", "role": "guest"}
}
```

### 3. Make Scripts Executable
Ensure the Tor exit script has the correct execution permissions so the dashboard can run it:
```bash
chmod +x tor_exit_node.sh
```

### 4. Install as a Systemd Service
To keep the dashboard running in the background and ensure it starts automatically on system boot, install the provided systemd service file:

```bash
# Copy the service file to the systemd directory
sudo cp server-dashboard.service /etc/systemd/system/

# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable server-dashboard.service

# Start the service immediately
sudo systemctl start server-dashboard.service
```

---

## Usage

1. Open your web browser and navigate to `http://<your-server-ip>:8080` (or your Tailscale IP on port 8080).
2. Select your username from the dropdown and log in using your configured password.
3. **Dashboard Interface**:
   * **Admin Users**: Can view live system resource charts, network stats, toggle the Tor Exit Node, and manage all services.
   * **Guest Users**: Are presented with a restricted view. System resource bars and network routing toggles are hidden, and they can only interact with explicitly whitelisted services.

---

## Adding New Services to the Dashboard

You can easily configure new services (like a Minecraft server, Docker container, etc.) to be monitored and managed by the dashboard.

1. **Ensure the service is managed by systemd** (e.g., `my-service.service`).
2. **Open `server.py`** in a text editor.
3. Locate the `SERVICES` list near the top of the file.
4. **Add a new dictionary** representing your service to the list. For example, to add Filebrowser:

   ```python
   SERVICES = [
       ...
       {
           'id': 'filebrowser',            # A unique identifier for the frontend
           'name': 'Network Storage',      # Display name on the dashboard
           'port': 8081,                   # Port the service runs on (for reference)
           'systemd': 'filebrowser',       # The exact name of the systemd service unit
           'icon': '[folder]',             # An icon representation to display on the card
           'description': 'Web-based file manager'
       },
   ]
   ```
5. **Restart the dashboard service** to apply your changes:
   ```bash
   sudo systemctl restart server-dashboard.service
   ```

---

## Setting up Multiple Instances of a Service (e.g., Navidrome)

Some services, like Navidrome, only allow pointing to a single data or music folder per instance. If different users have different tastes and need separate folders, you can create multiple instances of the service and manage them individually through the dashboard.

1. **Create multiple systemd service files**:
   Duplicate the service's systemd file and rename it for each user (e.g., `navidrome-tin.service` and `navidrome.service`).
2. **Configure separate environments**:
   Edit each new service file to use different ports (e.g., `4533` and `4534`), and point them to different configuration, data, and media directories.
3. **Register them in the Dashboard**:
   Add each instance as a separate entry in the `SERVICES` list in `server.py`, ensuring the `systemd` name matches the exact filename (without `.service`):

   ```python
   SERVICES = [
       {
           'id': 'navidrome-tin',
           'name': 'Navidrome (Tin)',
           'port': 4534,
           'systemd': 'navidrome-tin',
           'icon': '[music]',
           'description': 'Private music server'
       },
       {
           'id': 'navidrome',
           'name': 'Navidrome (Kimi)',
           'port': 4533,
           'systemd': 'navidrome',
           'icon': '[music]',
           'description': 'Shared music server'
       }
   ]
   ```
4. Modify the `/api/services` guest restriction logic in `server.py` if you want to restrict a specific instance to only specific users.

---

## Managing User Profiles and Permissions

You can configure different user accounts with `admin` or `guest` roles to restrict access to sensitive system controls.

### 1. Adding a New User
1. Add the new user to the `USERS` dictionary in `server.py` with their `password` and `role`.
2. To allow the new user to log in via the frontend, you must also add their username to the dropdown list in `public/login.html`:
   ```html
   <select id="username" required>
       <option value="tin">tin</option>
       <option value="ice.kimi">ice.kimi</option>
       <option value="new_user">new_user</option> <!-- Add new users here -->
   </select>
   ```

### 2. Restricting Services for Guest Profiles
By default, `guest` users cannot see system resource bars (CPU/RAM/Disk) or the Tor Exit Node toggle. They are also restricted from interacting with services except those explicitly whitelisted.

To control which services a `guest` profile can see and toggle on their dashboard, locate the `/api/services` route inside `server.py` and modify the allowed list in this block:

```python
if role == 'guest' and s['id'] not in ['filebrowser', 'navidrome']:
    continue
```
Simply remove or add service `id`s from this array to change what guests have access to.

---

## Important Notes
* **Root Privileges**: The dashboard executes system commands via `sudo systemctl` and `sudo iptables`. Running `server.py` as `root` (which the default `server-dashboard.service` does) is required to avoid password prompts for these commands. If you change the service to run as a standard user, you must configure `visudo` to allow passwordless execution for these specific binaries.
* **Suwayomi Integration**: The Suwayomi Tor integration hardcodes the path to the configuration file as `/var/lib/suwayomi/.local/share/Tachidesk/server.conf`. If your Tachidesk installation is located elsewhere, you must update this path in the `/api/suwayomi/tor` route in `server.py`.
* **Port Configuration**: By default, the web server listens on port `8080`. This can be changed by editing the `PORT = 8080` variable in `server.py`.
