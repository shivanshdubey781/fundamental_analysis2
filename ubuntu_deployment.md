# Ubuntu Server Deployment Guide

This guide describes how to upload the project files to your Ubuntu server using `scp` and set up the Flask server as a persistent `systemd` service.

---

## 🚀 Step 1: Upload Project via SCP (From Windows Terminal/PowerShell)

Run the following command from PowerShell on your local Windows machine. 
Make sure to replace `YOUR_SERVER_IP` with your actual server's IP address.

### Option A: Using SSH Username & Password
```powershell
scp -r "C:\Users\Shivansh Dubey\OneDrive\Desktop\fundamental_analysis2" root@YOUR_SERVER_IP:/var/www/
```

### Option B: Using an SSH Private Key File (`.pem` / `.key`)
```powershell
scp -i "C:\path\to\your-key.pem" -r "C:\Users\Shivansh Dubey\OneDrive\Desktop\fundamental_analysis2" root@YOUR_SERVER_IP:/var/www/
```

---

## 🛠️ Step 2: Connect to the Server & Set Up environment

SSH into your server:
```bash
ssh root@YOUR_SERVER_IP
# Or using SSH Key:
# ssh -i your-key.pem root@YOUR_SERVER_IP
```

Inside the server, run the setup steps:
```bash
# 1. Navigate to the project directory
cd /var/www/fundamental_analysis2

# 2. Update packages and install python3 virtual environment
apt update && apt install -y python3 python3-pip python3-venv

# 3. Create a python virtual environment
python3 -m venv venv

# 4. Activate the virtual environment
source venv/bin/activate

# 5. Install the required dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## ⚙️ Step 3: Create the Environment File (`.env`)

Create a new file named `.env` in the project root on the server:
```bash
nano /var/www/fundamental_analysis2/.env
```

Paste the following variables and update with your actual credentials:
```ini
APP_HOST=0.0.0.0
APP_PORT=8023
FLASK_DEBUG=false

# Targets / SL Tunables
TARGET_PCT=0.15
SL_PCT=0.05
TRAIL_SL_PCT=0.08
TRADE_ENTRY_MIN_SCORE=65
REPORT_RETENTION_HOURS=24

# Angel One Credentials
ANGEL_API_KEY=your_api_key
ANGEL_CLIENT_ID=your_client_id
ANGEL_PASSWORD=your_password
ANGEL_TOTP_KEY=your_totp_key
```
Press `Ctrl+O` then `Enter` to save, and `Ctrl+X` to exit nano.

---

## 📋 Step 4: Configure the systemd Service

We have created the `nse-screener.service` file for you in the workspace. You can copy it directly to your systemd system folder on the server.

On the server, create the service file:
```bash
nano /etc/systemd/system/nse-screener.service
```

Paste the contents of [nse-screener.service](file:///c:/Users/Shivansh%20Dubey/OneDrive/Desktop/fundamental_analysis2/nse-screener.service):
```ini
[Unit]
Description=NSE Fundamental Screener — Flask Production Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root

# Set the working directory (where main.py lives)
WorkingDirectory=/var/www/fundamental_analysis2

# Load environment variables from .env file
EnvironmentFile=/var/www/fundamental_analysis2/.env

# Run the app using the venv Python
ExecStart=/var/www/fundamental_analysis2/venv/bin/python main.py

# Auto-restart on crash
Restart=always
RestartSec=10

# Log output to journal
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## ⚡ Step 5: Enable and Start the Service

Enable and start the service to run it persistently in the background:
```bash
# Reload systemd configuration
systemctl daemon-reload

# Enable service to run on startup
systemctl enable nse-screener

# Start the service
systemctl start nse-screener

# Check current status
systemctl status nse-screener
```

---

## 🔍 Step 6: Monitor Logs & Verification

To verify that the server is running correctly and view live output/logs:

```bash
# Watch real-time logs
journalctl -u nse-screener -f

# Verify that port 8023 is listening
ss -tlnp | grep 8023
```

---

## 🔄 Updating Your Code Later

When you modify the code locally and want to push the updates to the server:

1. Upload the files:
   ```powershell
   scp "C:\Users\Shivansh Dubey\OneDrive\Desktop\fundamental_analysis2\main.py" root@YOUR_SERVER_IP:/var/www/fundamental_analysis2/
   ```
2. Restart the systemd service to apply changes:
   ```bash
   systemctl restart nse-screener
   ```
