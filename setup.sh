#!/bin/bash
#123
# Đường dẫn đến file client.py
CLIENT_FILE="/home/client.py"

# URL của file client.py trên GitHub
GITHUB_URL="https://raw.githubusercontent.com/giahuyanhduy/client/main/client.py"

# Tạo file startup.sh với logic mới (bao gồm git pull và curl để tải file client.py)
cat <<EOL > /home/startup.sh
#!/bin/bash

LOG_FILE="/home/startup.log"
REPO_DIR="/home"
CLIENT_FILE="/home/client.py"
GITHUB_URL="https://raw.githubusercontent.com/giahuyanhduy/client/main/client.py"

# Ghi thời gian bắt đầu vào log
echo "Starting startup script at \$(date)" >> \$LOG_FILE

# Di chuyển vào thư mục gốc
cd \$REPO_DIR

# Pull các thay đổi mới nhất từ GitHub
if ! git pull origin main >> \$LOG_FILE 2>&1; then
    echo "Failed to pull changes from GitHub at \$(date), trying to download client.py using curl" >> \$LOG_FILE
    
    # Tải file client.py từ GitHub nếu git pull thất bại
    if curl -o \$CLIENT_FILE \$GITHUB_URL; then
        echo "Successfully downloaded client.py from GitHub at \$(date)" >> \$LOG_FILE
    else
        echo "Failed to download client.py from GitHub at \$(date)" >> \$LOG_FILE
        exit 1
    fi
else
    echo "Successfully pulled latest changes from GitHub at \$(date)" >> \$LOG_FILE
fi

# Kiểm tra xem file client.py có tồn tại không
if [ ! -f \$CLIENT_FILE ]; then
    echo "client.py not found after git pull or curl. Exiting." >> \$LOG_FILE
    exit 1
fi

# Chạy client.py
if python3 \$CLIENT_FILE; then
    echo "Successfully ran client.py at \$(date)" >> \$LOG_FILE
else
    echo "Failed to run client.py at \$(date)" >> \$LOG_FILE
    exit 1
fi
EOL

# Cấp quyền thực thi cho startup.sh
chmod +x /home/startup.sh

# Tạo file service cho systemd
SERVICE_FILE="/etc/systemd/system/client.service"
cat <<EOL | tee ${SERVICE_FILE} > /dev/null
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

# Kiểm tra xem tệp dịch vụ đã được tạo thành công chưa
if [ -f ${SERVICE_FILE} ]; then
    echo "Service file created successfully at ${SERVICE_FILE}"
else
    echo "Failed to create service file at ${SERVICE_FILE}"
    exit 1
fi

# Kích hoạt và khởi động dịch vụ
systemctl daemon-reload
systemctl enable client.service
systemctl start client.service

# Kiểm tra trạng thái của dịch vụ
systemctl status client.service

echo "Setup complete. client.service has been created and started."
