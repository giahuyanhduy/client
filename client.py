import requests
import time
import os
import subprocess
import re
import json
from datetime import datetime, timedelta
from threading import Thread

def get_port_from_file():
    try:
        with open('/opt/autorun', 'r') as file:
            content = file.read()
            match = re.search(r'(\d{4}):localhost:22', content)
            if match:
                port = match.group(1)
                return port
            else:
                print("Port not found in the file.")
                return None
    except Exception as e:
        print(f"Error reading port from file: {e}")
        return None

def get_data_from_url(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Non-200 status code: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from URL: {e}")
        return None

def send_data_to_flask(data, port):
    flask_url = f"http://14.225.74.7:17071/api/receive_data/{port}"
    try:
        response = requests.post(flask_url, json=data)
        print("Status Code:", response.status_code)
        print("Response Text:", response.text)
    except requests.exceptions.RequestException as e:
        print(f"Error sending data to Flask server: {e}")

def check_getdata_status(port):
    request_url = f"http://14.225.74.7:17071/api/request/{port}"
    try:
        response = requests.get(request_url)
        if response.status_code == 200:
            data = response.json()
            print(f"Data from /api/request/{port}: {data}")
            if data.get('restart') == 'True':
                print("Restart command received. Restarting system.")
                subprocess.run(['sudo', 'reboot'])
            if 'ssh' in data and data['ssh']:
                command = data['ssh']
                print(f"SSH command received: {command}. Executing command.")
                try:
                    result = subprocess.run(command, shell=True, check=True, capture_output=True)
                    print(f"Command executed successfully: {result.stdout.decode()}")
                except subprocess.CalledProcessError as e:
                    print(f"Error executing command: {e.stderr.decode()}")
            return data.get('getdata') == 'On'
        print(f"Non-200 status code from check_getdata_status: {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"Error checking getdata status: {e}")
        return False


def send_warning(port, pump_id, warning_type):
    warning_url = f"http://14.225.74.7:17071/api/warning/{port}/{pump_id}/{warning_type}"
    try:
        response = requests.post(warning_url)
        print(f"Sent warning for port {port}, pump ID {pump_id}, type {warning_type}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending warning: {e}")

def call_daylaidulieu_api(pump_id):
    api_url = f"http://localhost:6969/daylaidulieu/{pump_id}"
    try:
        response = requests.get(api_url)
        print(f"Called daylaidulieu API for pump ID {pump_id}. Status Code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error calling daylaidulieu API: {e}")



def check_mabom(data, mabom_history, file_path, port, connection_status):
    current_time = datetime.now()

    for item in data:
        #print(f"Original item: {item}")  # In dữ liệu gốc của item

        # Kiểm tra xem phần 'MaBomMoiNhat' có tồn tại trong mục hay không
        if 'MaBomMoiNhat' in item and item['MaBomMoiNhat'] is not None:
            # Lấy giá trị 'idcot' và 'pump' từ 'MaBomMoiNhat'
            idcot = item['MaBomMoiNhat'].get('idcot')
            pump = item['MaBomMoiNhat'].get('pump')
        else:
            print(f"Skipping item because 'MaBomMoiNhat' is missing or None. Item: {item}")
            continue

        # Kiểm tra nếu 'idcot' hoặc 'pump' là None, bỏ qua mục này
        if idcot is None or pump is None:
            print(f"Skipping item because 'idcot' or 'pump' is None. idcot: {idcot}, pump: {pump}")
            continue  # Skip if idcot or pump is not present

        print(f"Processed item: idcot={idcot}, pump={pump}")  # In dữ liệu đã xử lý

        # Convert idcot to string to ensure JSON compatibility
        pump_id = str(idcot)
        mabomtiep = pump

        # Kiểm tra trạng thái kết nối
        is_disconnected = item.get('isDisconnected', False)

        if pump_id not in connection_status:
            connection_status[pump_id] = {
                'is_disconnected': is_disconnected,
                'disconnect_time': current_time if is_disconnected else None,
                'alert_sent': False  # Thêm cờ để theo dõi cảnh báo đã gửi
            }
        else:
            if is_disconnected:
                if not connection_status[pump_id]['is_disconnected']:
                    # Bắt đầu đếm thời gian ngắt kết nối
                    connection_status[pump_id]['is_disconnected'] = True
                    connection_status[pump_id]['disconnect_time'] = current_time
                    connection_status[pump_id]['alert_sent'] = False  # Reset cờ cảnh báo
                else:
                    # Kiểm tra thời gian ngắt kết nối
                    if current_time - connection_status[pump_id]['disconnect_time'] > timedelta(seconds=65):
                        if not connection_status[pump_id]['alert_sent']:
                            print(f"Pump ID {pump_id} disconnected for more than 30 seconds.")
                            send_warning(port, pump_id, "disconnection")
                            connection_status[pump_id]['alert_sent'] = True  # Đánh dấu cảnh báo đã gửi
            else:
                if connection_status[pump_id]['is_disconnected']:
                    # Xóa cờ nếu kết nối lại trong vòng 30 giây
                    if current_time - connection_status[pump_id]['disconnect_time'] <= timedelta(seconds=65):
                        print(f"Pump ID {pump_id} reconnected within 30 seconds.")
                    connection_status[pump_id] = {
                        'is_disconnected': False,
                        'disconnect_time': None,
                        'alert_sent': False  # Reset cờ cảnh báo khi kết nối lại
                    }

        if pump_id not in mabom_history:
            mabom_history[pump_id] = []

        if mabom_history[pump_id] and isinstance(mabom_history[pump_id][-1], tuple) and mabom_history[pump_id][-1][0] == mabomtiep:
            print(f"No change in mabomtiep for pump ID {pump_id}, keeping the same value.")
        else:
            mabom_history[pump_id].append((mabomtiep, current_time.strftime('%Y-%m-%d %H:%M:%S')))
            if len(mabom_history[pump_id]) > 10:
                mabom_history[pump_id].pop(0)  # Chỉ xóa mã bơm xa nhất thay vì 10 mã cũ nhất

        # Lọc các mục cảnh báo ra khỏi mabom_history[pump_id]
        mabom_entries = [entry for entry in mabom_history[pump_id] if isinstance(entry, tuple)]

        if len(mabom_entries) > 1:
            previous_mabom = mabom_entries[-2][0]
            if isinstance(mabomtiep, int) and isinstance(previous_mabom, int):
                if mabomtiep != previous_mabom + 1:
                    if not any(isinstance(warning, dict) and warning.get('type') == 'nonsequential' for warning in mabom_history[pump_id]):
                        print(f"Lỗi mã bơm không liên tiếp: Vòi bơm {pump_id} của port {port} phát hiện mã bơm không liên tiếp.")
                        send_warning(port, pump_id, "nonsequential")
                        call_daylaidulieu_api(pump_id)  # Gọi API khi phát hiện mã bơm không liên tiếp
                        mabom_history[pump_id].append({
                            'type': 'nonsequential',
                            'time': current_time.strftime('%Y-%m-%d %H:%M:%S')
                        })
                else:
                    # Xóa cờ cảnh báo không liên tiếp khi mã bơm trở lại liên tiếp
                    mabom_history[pump_id] = [entry for entry in mabom_history[pump_id] if not (isinstance(entry, dict) and entry.get('type') == 'nonsequential')]

    with open(file_path, 'w') as file:
        json.dump(mabom_history, file, indent=4)
def check_mabom_continuously(port, mabom_file_path):
    if os.path.exists(mabom_file_path):
        with open(mabom_file_path, 'r') as file:
            mabom_history = json.load(file)
    else:
        mabom_history = {}

    connection_status = {}

    while True:
        data_from_url = get_data_from_url("http://localhost:6969/GetfullupdateArr")
        #("Data from URL:", data_from_url)
        if data_from_url:
            check_mabom(data_from_url, mabom_history, mabom_file_path, port, connection_status)
        
            #print("Failed to retrieve data from URL")
        time.sleep(2)

def send_data_continuously(port):
    while True:
        if check_getdata_status(port):
            data_from_url = get_data_from_url("http://localhost:6969/GetfullupdateArr")
            #print("Data from URL:", data_from_url)
            if data_from_url:
                send_data_to_flask(data_from_url, port)
                print("Data sent to Flask server")
            else:
                print("Failed to retrieve data from URL")
        else:
            print("getdata is Off")
        time.sleep(4)

def main():
    port = get_port_from_file()
    if not port:
        print("No port found. Exiting.")
        return
    
    print(f"Using port: {port}")

    mabom_file_path = 'mabom.json'

    # Run mabom check in a separate thread
    mabom_thread = Thread(target=check_mabom_continuously, args=(port, mabom_file_path))
    mabom_thread.start()

    # Run data sending in the main thread
    send_data_continuously(port)

if __name__ == "__main__":
    main()
