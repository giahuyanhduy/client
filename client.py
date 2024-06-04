#ver 1.14
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
            # Biểu thức chính quy để bắt đầu với 1 khoảng trắng và 4 ký tự số hoặc không có khoảng trắng và 5 ký tự số
            match = re.search(r'(\s\d{4}|\d{5}):localhost:22', content)
            if match:
                port = match.group(1).strip()  # Xóa khoảng trắng ở đầu nếu có
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
    flask_url = f"http://103.77.166.69/api/receive_data/{port}"
    try:
        response = requests.post(flask_url, json=data)
        print("Status Code:", response.status_code)
        print("Response Text:", response.text)
    except requests.exceptions.RequestException as e:
        print(f"Error sending data to Flask server: {e}")

def check_getdata_status(port):
    request_url = f"http://103.77.166.69/api/request/{port}"
    try:
        response = requests.get(request_url)
        if response.status_code == 200:
            data = response.json()
            #print(f"Data from /api/request/{port}: {data}")
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




def call_daylaidulieu_api(pump_id):
    api_url = f"http://localhost:6969/daylaidulieu/{pump_id}"
    try:
        response = requests.get(api_url)
        print(f"Called daylaidulieu API for pump ID {pump_id}. Status Code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error calling daylaidulieu API: {e}")


def send_warning(port, pump_id, warning_type, mabom):
    warning_url = f"http://103.77.166.69/api/warning/{port}/{pump_id}/{warning_type}"
    try:
        response = requests.post(warning_url, json={'mabom': mabom})  # Truyền mã bơm khi gửi cảnh báo
        print(f"Sent warning for port {port}, pump ID {pump_id}, type {warning_type}, mabom {mabom}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending warning: {e}")

def check_mabom(data, mabom_history, file_path, port, connection_status, is_all_disconnect_restart):
    current_time = datetime.now()
    all_disconnected = True  # Kiểm tra tất cả các vòi đều mất kết nối

    for item in data:
        idcot = item.get('id')
        pump = item.get('pump')  # Lấy giá trị pump phía ngoài
        statusnow = item.get('status')
        mabom_moinhat = item.get('MaBomMoiNhat', {}).get('pump')  # Lấy giá trị pump trong MaBomMoiNhat

        if idcot is None or pump is None:
            #print(f"Skipping item because 'idcot' or 'pump' is None. idcot: {idcot}, pump: {pump}")
            continue

        #print(f"Processed item: idcot={idcot}, status={statusnow}")
        #print(f"Processed item: idcot={idcot}, pump(mbmn)={mabom_moinhat}")
        #print(f"Processed item: idcot={idcot}, pump={pump}")

        pump_id = str(idcot)
        mabomtiep = pump

        is_disconnected = item.get('isDisconnected', False)

        if not is_disconnected:
            all_disconnected = False  # Nếu bất kỳ vòi nào không mất kết nối, đặt cờ này thành False

        if pump_id not in connection_status:
            connection_status[pump_id] = {
                'is_disconnected': is_disconnected,
                'disconnect_time': current_time if is_disconnected else None,
                'alert_sent': False,
                'last_alerted_mabom': None,  # Thêm mục này để theo dõi mã bơm đã cảnh báo
                'mismatch_count': 0,  # Đếm số lần lệch
                'restart_done': False  # Đánh dấu nếu đã thực hiện restart
            }
        else:
            if is_disconnected:
                if not connection_status[pump_id]['is_disconnected']:
                    connection_status[pump_id]['is_disconnected'] = True
                    connection_status[pump_id]['disconnect_time'] = current_time
                    connection_status[pump_id]['alert_sent'] = False
                    connection_status[pump_id]['restart_done'] = False  # Reset cờ restart_done khi mất kết nối lần nữa
                else:
                    if current_time - connection_status[pump_id]['disconnect_time'] > timedelta(seconds=65):
                        if not connection_status[pump_id]['alert_sent']:
                            print(f"Pump ID {pump_id} disconnected for more than 65 seconds.")
                            send_warning(port, pump_id, "disconnection", mabomtiep)
                            connection_status[pump_id]['alert_sent'] = True
            else:
                if connection_status[pump_id]['is_disconnected']:
                    if current_time - connection_status[pump_id]['disconnect_time'] <= timedelta(seconds=65):
                        print(f"Pump ID {pump_id} reconnected within 65 seconds.")
                    connection_status[pump_id] = {
                        'is_disconnected': False,
                        'disconnect_time': None,
                        'alert_sent': False,
                        'last_alerted_mabom': connection_status[pump_id].get('last_alerted_mabom'),  # Giữ nguyên giá trị last_alerted_mabom
                        'mismatch_count': connection_status[pump_id].get('mismatch_count', 0),  # Giữ nguyên giá trị mismatch_count
                        'restart_done': connection_status[pump_id].get('restart_done', False)  # Giữ nguyên giá trị restart_done
                    }

        if pump_id not in mabom_history:
            mabom_history[pump_id] = []

        if mabom_history[pump_id] and isinstance(mabom_history[pump_id][-1], tuple) and mabom_history[pump_id][-1][0] == mabomtiep:
            continue
        else:
            mabom_history[pump_id].append((mabomtiep, current_time.strftime('%Y-%m-%d %H:%M:%S')))
            if len(mabom_history[pump_id]) > 10:
                mabom_history[pump_id].pop(0)

        mabom_entries = [entry for entry in mabom_history[pump_id] if isinstance(entry, tuple)]

        if statusnow == 'sẵn sàng':
            if mabom_moinhat and mabom_moinhat != pump:
                connection_status[pump_id]['mismatch_count'] += 1
                print(f"Mã bơm không khớp lần {connection_status[pump_id]['mismatch_count']} cho pump ID {pump_id}: {mabom_moinhat} != {pump}")

                if connection_status[pump_id]['mismatch_count'] == 3:
                    print(f"Pump ID {pump_id} có mã bơm không khớp 3 lần. Thực hiện restartall.")
                    subprocess.run(['forever', 'restartall'])
                    time.sleep(3)
                    call_daylaidulieu_api(pump_id)
                    send_warning(port, pump_id, "nonsequential", mabomtiep)  # Gửi cảnh báo lên server
                    connection_status[pump_id]['mismatch_count'] = 0
            else:
                connection_status[pump_id]['mismatch_count'] = 0

            if len(mabom_entries) > 1:
                previous_mabom = mabom_entries[-2][0]
                if isinstance(mabomtiep, int) and isinstance(previous_mabom, int):
                    if mabomtiep != previous_mabom + 1:
                        if connection_status[pump_id]['last_alerted_mabom'] != mabomtiep:
                            print(f"Lỗi mã bơm không liên tiếp: Vòi bơm {pump_id} của port {port} phát hiện mã bơm không liên tiếp.")
                            send_warning(port, pump_id, "nonsequential", mabomtiep)
                            call_daylaidulieu_api(pump_id)
                            mabom_history[pump_id].append({
                                'type': 'nonsequential',
                                'time': current_time.strftime('%Y-%m-%d %H:%M:%S')
                            })
                            connection_status[pump_id]['last_alerted_mabom'] = mabomtiep
                    else:
                        mabom_history[pump_id] = [entry for entry in mabom_history[pump_id] if not (isinstance(entry, dict) and entry.get('type') == 'nonsequential')]

    if all_disconnected and not any(conn['restart_done'] for conn in connection_status.values()) and not is_all_disconnect_restart[0]:
        print("Tất cả các vòi đều mất kết nối. Thực hiện restartall.")
        subprocess.run(['forever', 'restartall'])
        for conn in connection_status.values():
            conn['restart_done'] = True
        send_all_disconnected_warning(port)
        is_all_disconnect_restart[0] = True  # Đặt cờ khi tất cả các vòi đều mất kết nối và đã restartall

    if not all_disconnected:
        is_all_disconnect_restart[0] = False  # Reset cờ khi ít nhất một vòi kết nối lại

def send_all_disconnected_warning(port):
    warning_url = f"http://103.77.166.69/api/warning/{port}/all/all_disconnection"
    try:
        response = requests.post(warning_url, json={'message': 'Tất cả các vòi đều mất kết nối. Đã thực hiện restart service.'})
        print(f"Sent all disconnected warning for port {port}")
    except requests.exceptions.RequestException as e:
        print(f"Error sending all disconnected warning: {e}")

def check_mabom_continuously(port, mabom_file_path):
    if os.path.exists(mabom_file_path):
        try:
            with open(mabom_file_path, 'r') as file:
                mabom_history = json.load(file)
                print(f"Loaded existing mabom history from {mabom_file_path}")
        except Exception as e:
            print(f"Error loading mabom history from file: {e}")
            mabom_history = {}
    else:
        mabom_history = {}
        # Tạo file mới nếu chưa tồn tại
        try:
            with open(mabom_file_path, 'w') as file:
                json.dump(mabom_history, file, indent=4)
                print(f"Created new mabom history file at {mabom_file_path}")
        except Exception as e:
            print(f"Error creating mabom history file: {e}")

    connection_status = {}
    is_all_disconnect_restart = [False]  # Cờ cho biết nếu tất cả vòi đều mất kết nối và đã restartall

    while True:
        data_from_url = get_data_from_url("http://localhost:6969/GetfullupdateArr")
        #print(data_from_url)
        if data_from_url:
            check_mabom(data_from_url, mabom_history, mabom_file_path, port, connection_status, is_all_disconnect_restart)
        else:
            print("Failed to retrieve data from URL")
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
      
        time.sleep(4)

def main():
    port = get_port_from_file()
    if not port:
        print("No port found. Exiting.")
        return
    
    print(f"Using port: {port}")

    # Đảm bảo rằng mabom_file_path là đường dẫn đầy đủ
    script_dir = os.path.dirname(os.path.realpath(__file__))
    mabom_file_path = os.path.join(script_dir, 'mabom.json')

    # Kiểm tra và tạo file mabom.json nếu chưa tồn tại
    if not os.path.exists(mabom_file_path):
        try:
            with open(mabom_file_path, 'w') as file:
                json.dump({}, file, indent=4)
                print(f"Created new mabom history file at {mabom_file_path}")
        except Exception as e:
            print(f"Error creating mabom history file: {e}")
            return

    # Run mabom check in a separate thread
    mabom_thread = Thread(target=check_mabom_continuously, args=(port, mabom_file_path))
    mabom_thread.start()

    # Run data sending in the main thread
    send_data_continuously(port)
if __name__ == "__main__":
    main()
