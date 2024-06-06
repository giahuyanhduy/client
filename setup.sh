#!/bin/bash
#123
# Đường dẫn đến file client.py
CLIENT_FILE="/home/client.py"

# URL của file client.py trên GitHub
GITHUB_URL="https://raw.githubusercontent.com/giahuyanhduy/client/main/client.py"

# Tạo file startup.sh với logic xóa file cũ và tải file mới với cơ chế thử lại
cat <<EOL > /home/startup.sh
#!/bin/bash

LOG_FILE="/home/startup.log"
CLIENT_FILE="/home/client.py"
GITHUB_URL="https://raw.githubusercontent.com/giahuyanhduy/client/main/client.py"

# Số lần thử lại
RETRY_COUNT=5
# Thời gian chờ giữa các lần thử lại (giây)
RETRY_DELAY=5

# Ghi thời gian bắt đầu vào log
echo "Starting startup script at \$(date)" >> \$LOG_FILE

# Xóa file client.py cũ
if [ -f \$CLIENT_FILE ]; then
    rm \$CLIENT_FILE
    echo "Deleted old client.py at \$(date)" >> \$LOG_FILE
else
    echo "No existing client.py to delete at \$(date)" >> \$LOG_FILE
fi

# Tải file client.py mới nhất từ GitHub với cơ chế thử lại
for ((i=1; i<=\$RETRY_COUNT; i++)); do
    if curl -o \$CLIENT_FILE \$GITHUB_URL; then
        echo "Successfully downloaded client.py from GitHub at \$(date) on attempt \$i" >> \$LOG_FILE
        break
    else
        echo "Failed to download client.py from GitHub at \$(date) on attempt \$i" >> \$LOG_FILE
        if [ \$i -eq \$RETRY_COUNT ]; then
            echo "Max retry attempts reached. Exiting." >> \$LOG_FILE
            exit 1
        fi
        sleep \$RETRY_DELAY
    fi
done

# Chạy client.py
if  python3 \$CLIENT_FILE; then
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
cat <<EOL |  tee ${SERVICE_FILE} > /dev/null
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
