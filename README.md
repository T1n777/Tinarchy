# Tinarchy Server Dashboard

A powerful, customizable, and role-based server dashboard designed to manage services, track system resources, and route traffic through a Tor exit node.

## Setup and Installation

Follow these detailed steps to properly install and configure the server dashboard on your system.

### 1. Clone the Repository
First, you need to download the source code to your machine. The provided systemd service file assumes that you are installing the repository in the `/home/tin/server-dashboard` directory. If your username is different or you choose a different path, you must manually update the paths in both `server-dashboard.service` and `server.py` before proceeding.

Run the following commands in your terminal:
```bash
git clone https://github.com/T1n777/Tinarchy.git /home/tin/server-dashboard
cd /home/tin/server-dashboard
```

### 2. Configure Profiles (Users)
The dashboard uses a role-based authentication system. Passwords should be stored securely and never committed to version control. You will create a `.env` file in the project directory to store your credentials as environment variables.

Run these commands to create and populate your `.env` file. Replace `your_admin_password` and `your_guest_password` with secure passwords of your choosing:
```bash
echo "ADMIN_PASSWORD=your_admin_password" >> .env
echo "GUEST_PASSWORD=your_guest_password" >> .env
```
The application loads these environment variables into the `USERS` dictionary at the top of the `server.py` file to authenticate users upon login.

### 3. Make Scripts Executable
The dashboard requires execution permissions for certain shell scripts to function correctly. Specifically, the script responsible for managing the Tor exit node routing must be executable.

Run the following command in the project directory:
```bash
chmod +x tor_exit_node.sh
```

### 4. Install as a Systemd Service
To ensure the dashboard runs continuously in the background and automatically restarts if the server reboots, you must install the included systemd service file.

Execute the following commands sequentially:
```bash
# 1. Copy the service file to the systemd system directory
sudo cp server-dashboard.service /etc/systemd/system/

# 2. Reload the systemd daemon so it recognizes the newly added service
sudo systemctl daemon-reload

# 3. Enable the service so it starts automatically on system boot
sudo systemctl enable server-dashboard.service

# 4. Start the service immediately without needing to reboot
sudo systemctl start server-dashboard.service
```

---

## Usage Guide

Once the installation is complete, you can access the dashboard from any device on your network.

1. **Access the Dashboard:** Open your preferred web browser and enter your server's IP address followed by port `8080` (for example, `http://192.168.1.50:8080`). If you are using Tailscale, you can use your Tailscale IP address.
2. **Log In:** On the login screen, select your username from the dropdown menu and enter the password you configured in the `.env` file.
3. **Understand the Interface:**
   * **Admin Users:** Administrators have full access. They can view real-time system resource metrics (CPU, RAM, Disk usage), monitor network traffic, toggle the Tor Exit Node routing, and manage all configured services.
   * **Guest Users:** Guests have a strictly limited view. The system resource bars, network statistics, and Tor routing controls are completely hidden. Furthermore, guests can only interact with services that have been explicitly whitelisted by an administrator.

---

## Adding New Services to the Dashboard

The dashboard is designed to be easily extensible. You can add any service (such as a Minecraft server, a Docker container, or a custom application) to the dashboard as long as it is managed by systemd.

### Step-by-Step Instructions:
1. **Verify Systemd Management:** Ensure the service you want to add is currently managed by systemd (for example, you should be able to run `sudo systemctl status my-service.service`).
2. **Edit the Configuration:** Open the `server.py` file in your preferred text editor (such as `nano` or `vim`).
3. **Locate the Services List:** Find the list named `SERVICES` located near the top of the file.
4. **Append the New Service:** Add a new dictionary object representing your service to this list. Ensure you use the exact systemd service name. 
   
   Here is an example of adding Filebrowser:
   ```python
   SERVICES = [
       # ... existing services ...
       {
           'id': 'filebrowser',            # A unique string identifier used by the frontend
           'name': 'Network Storage',      # The display name that will appear on the dashboard card
           'port': 8081,                   # The port the service runs on (used for display reference)
           'systemd': 'filebrowser',       # The exact name of the systemd service unit (without .service)
           'icon': '',                     # Leave blank or add an SVG/HTML icon representation
           'description': 'Web-based file manager' # A short description of what the service does
       },
   ]
   ```
5. **Apply the Changes:** Save your changes to `server.py` and restart the dashboard service to load the new configuration:
   ```bash
   sudo systemctl restart server-dashboard.service
   ```

---

## Setting up Multiple Instances of a Service

Certain applications, like Navidrome, only support a single data or media directory per instance. If you have multiple users who require their own separate libraries or configurations, you can run multiple instances of the same application and manage them independently through the dashboard.

### Step-by-Step Instructions:
1. **Duplicate the Systemd Service:** Create a copy of the application's systemd service file for the new user. Rename it to distinguish it (for example, `navidrome-tin.service` and `navidrome-kimi.service`).
2. **Configure Unique Environments:** Edit each systemd service file to ensure they do not conflict. This typically involves changing the listening port (e.g., `4533` for one, `4534` for the other) and specifying different paths for their data, configuration, and media directories.
3. **Register Instances in the Dashboard:** Open `server.py` and add each instance as a separate entry within the `SERVICES` list. The `systemd` key must precisely match the respective filename.

   Example configuration:
   ```python
   SERVICES = [
       {
           'id': 'navidrome-tin',
           'name': 'Navidrome (Tin)',
           'port': 4534,
           'systemd': 'navidrome-tin',
           'icon': '',
           'description': 'Private music server for Tin'
       },
       {
           'id': 'navidrome-kimi',
           'name': 'Navidrome (Kimi)',
           'port': 4533,
           'systemd': 'navidrome-kimi',
           'icon': '',
           'description': 'Shared music server for Kimi'
       }
   ]
   ```
4. **Adjust Guest Restrictions (Optional):** If you wish to hide a specific instance from guest users, ensure its `id` is not included in the `GUEST_SERVICES` list in `server.py`.

---

## Managing User Profiles and Permissions

The dashboard relies on the `USERS` dictionary and the `GUEST_SERVICES` list in `server.py` to enforce security and access control.

### 1. Adding a New User Account
To grant a new person access to the dashboard:
1. Open `server.py` and locate the `USERS` dictionary.
2. Add a new entry defining their username, linking it to a password environment variable, and assigning a role (`admin` or `guest`).
3. Open `public/login.html` and locate the `<select id="username" required>` element.
4. Add a new `<option>` tag for the new user so their name appears in the login dropdown menu.
   ```html
   <select id="username" required>
       <option value="tin">tin</option>
       <option value="ice.kimi">ice.kimi</option>
       <option value="new_user">new_user</option> <!-- newly added user -->
   </select>
   ```

### 2. Restricting Services for Guest Profiles
Guest accounts are heavily restricted by default. They cannot view system metrics or interact with the Tor routing. Furthermore, they can only see and interact with services that are explicitly whitelisted.

To configure the whitelist:
1. Open `server.py` and locate the `GUEST_SERVICES` list near the top of the file.
   ```python
   GUEST_SERVICES = ['filebrowser', 'navidrome']
   ```
2. Add or remove the `id` of any service (matching the `id` defined in the `SERVICES` list) to alter what a guest user is permitted to see and control.

### 3. Session Limits
To ensure optimal performance and security, the backend enforces a strict session limit. Each user account is permitted a maximum of 5 concurrent active sessions across different devices or browsers. If a user successfully logs in from a 6th device, the backend will automatically identify and revoke their oldest active session.

---

## Customizing the Background (Wallpaper Gallery)

The dashboard includes a dynamic wallpaper gallery system, allowing you to personalize the appearance of both the login screen and the main dashboard view directly from the Settings modal.

### Step-by-Step Instructions to Add Wallpapers:
1. **Locate the Directory:** Ensure a directory named `Wallpapers` exists inside the `public/` folder. The full path should be `/home/tin/server-dashboard/public/Wallpapers/`. If it does not exist, create it.
2. **Add Images:** Move or copy your desired image files into this directory. The system supports standard web image formats: `.jpg`, `.jpeg`, `.png`, and `.webp`.
3. **Categorize Images (Optional):** To organize your wallpapers into logical groups within the settings dropdown menu, you can prefix the filename with a category name followed by a double dash. For example, renaming a file to `synthwave--neon-city.jpg` will place it under a "synthwave" category.
4. **Apply Wallpapers:** Open your dashboard in a web browser, navigate to the Settings page, and select your new wallpapers from the dropdown lists.

*Performance Note: If you choose the "Solid Dark" or "Ultra" performance themes in the appearance settings, background wallpapers will be intentionally disabled to conserve GPU resources and improve rendering speed on lower-end devices.*

---

## Appearance Customization (UI Engine)

The dashboard features a robust UI engine that allows for deep visual customization without touching the code. You can access these options via the **Settings** page. All configuration choices are saved locally in your browser's `localStorage`.

* **Font Selection:** The engine includes several bundled Google Fonts (such as Inter, Roboto, and Poppins). Selecting a new font will immediately update the typography across the entire dashboard interface.
* **Color Schemes:** You can choose to have the dashboard automatically extract and apply an accent color based on your current wallpaper, or you can manually define a specific hex color code. This accent color is applied to interactive elements like toggle switches and progress bars. *Note: When utilizing the "Solid Dark" or "Ultra" performance themes, the automatic color option will default to a pre-defined, high-contrast theme color to guarantee text readability.*
* **Liquid Glass Engine:** When using the default glass theme, you can manipulate the translucency slider to adjust the opacity of the dashboard cards and navigation bars. Dragging the slider all the way down will completely disable the CSS backdrop blur effect, which significantly improves scrolling and rendering performance on older hardware.

---

## Important Technical Notes

* **Root Privileges:** The dashboard backend heavily relies on executing system-level commands using `sudo systemctl` (for service management) and `sudo iptables` (for Tor routing). Because the provided `server-dashboard.service` file runs the python script as the `root` user, these commands execute silently. However, if you modify the service to run under a standard user account, the application will break unless you explicitly configure the `/etc/sudoers` file (using `visudo`) to allow that specific user to execute those exact binaries without being prompted for a password.
* **Suwayomi Integration:** The integration for routing Suwayomi traffic through Tor utilizes a hardcoded configuration path: `/var/lib/suwayomi/.local/share/Tachidesk/server.conf`. If your Tachidesk instance is installed in a non-standard location or under a different user directory, you must manually edit this file path within the `/api/suwayomi/tor` routing logic found in `server.py`.
* **Port Configuration:** Out of the box, the dashboard's web server binds to and listens on port `8080`. If this conflicts with another service on your machine, you can change it by modifying the `PORT = 8080` variable near the bottom of `server.py` and restarting the dashboard service.
