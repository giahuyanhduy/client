#!/bin/bash

# Đường dẫn đến file client.py
CLIENT_FILE="/home/client.py"

# URL của file client.py trên GitHub
GITHUB_URL="https://raw.githubusercontent.com/giahuyanhduy/client/main/client.py"

# Tải file client.py mới nhất từ GitHub
curl -o $CLIENT_FILE $GITHUB_URL

# Tạo file startup.sh
cat <<EOL > /home/startup.sh
#!/bin/bash
CLIENT_FILE="/home/client.py"
GITHUB_URL="$GITHUB_URL"
curl -o \$CLIENT_FILE \$GITHUB_URL
python3 \$CLIENT_FILE
EOL

# Cấp quyền thực thi cho startup.sh
chmod +x /home/startup.sh

# Tạo file service cho systemd
SERVICE_FILE="/etc/systemd/system/client.service"
cat <<EOL | sudo tee $SERVICE_FILE > /dev/null
[Unit]
Description=Run client.py from GitHub on startup
After=network.target

[Service]
Type=simple
ExecStart=/bin/bash /home/startup.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

# Kích hoạt service
sudo systemctl daemon-reload
sudo systemctl enable client.service
sudo systemctl start client.service
