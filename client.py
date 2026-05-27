import requests
import time
import os
import subprocess
import re
import random
import json
import socket
import struct
import logging
from datetime import datetime, timedelta
from threading import Thread, Lock

logging.basicConfig(filename='client_log.log', level=logging.INFO, 
                    format='%(asctime)s %(levelname)s:%(message)s')

# ============================================================
# CHẾ ĐỘ HOẠT ĐỘNG:
#   - MODE_API  = Dùng API localhost:6969 (cũ, mặc định)
#   - MODE_8086 = Dùng Socket 8086 (khi #MAXPUMP= trong /opt/autorun)
# ============================================================
MODE_API = "api"
MODE_8086 = "8086"

# ============================================================
# CÁC HÀM TIỆN ÍCH CHUNG
# ============================================================

def get_cpu_arch():
    try:
        arch = subprocess.check_output(['uname', '-m']).decode().strip()
        if 'arm' in arch.lower() or 'aarch64' in arch.lower():
            return 'ARM'
        elif 'x86' in arch.lower() or 'i686' in arch.lower():
            return 'X86'
        else:
            return 'Unknown'
    except subprocess.CalledProcessError as e:
        logging.error(f"Lỗi khi lấy kiến trúc CPU: {e}")
        return 'Unknown'
    except Exception as e:
        logging.error(f"Lỗi không mong muốn khi lấy kiến trúc CPU: {e}")
        return 'Unknown'

def detect_mode():
    """
    Kiểm tra file /opt/autorun:
      - Nếu tìm thấy dòng #MAXPUMP= (đã bị comment) -> dùng MODE_8086
      - Nếu MAXPUMP= đang active hoặc không có -> dùng MODE_API (cũ)
    """
    try:
        with open('/opt/autorun', 'r') as file:
            content = file.read()
            # Tìm dòng #MAX_PUMP= hoặc #MAXPUMP= (đã comment)
            if re.search(r'^\s*#\s*MAX_?PUMP\s*=', content, re.MULTILINE):
                logging.info("Phát hiện #MAX_PUMP= (commented). Chuyển sang chế độ Socket 8086.")
                return MODE_8086
            else:
                logging.info("MAX_PUMP= active hoặc không có. Dùng chế độ API 6969.")
                return MODE_API
    except Exception as e:
        logging.error(f"Lỗi khi đọc /opt/autorun để detect mode: {e}")
        return MODE_API

def get_version(mode):
    """
    Nếu mode = 8086 -> version = "{CPU}-NONE" hoặc "{CPU}-NANO" (nếu có index.js)
    Nếu mode = api  -> version lấy từ GasController.js (logic cũ)
    """
    cpu_arch = get_cpu_arch()
    has_ips, has_fuelmet, has_nano = _check_autorun_services()
    
    if mode == MODE_8086:
        mode_suffix = "NANO" if has_nano else "NONE"
        version = f"{cpu_arch}-{mode_suffix}"
        if has_ips and has_fuelmet:
            return version + "-IPS-Fuelmet"
        elif has_ips:
            return version + "-IPS"
        elif has_fuelmet:
            return version + "-Fuelmet"
        return version
    else:
        return get_version_from_js(has_ips, has_fuelmet)

def _check_autorun_services():
    has_ips = False
    has_fuelmet = False
    has_nano = False
    try:
        if os.path.exists('/opt/autorun'):
            with open('/opt/autorun', 'r') as file:
                for line in file:
                    line_strip = line.strip()
                    # Bỏ qua dòng trống hoặc dòng bị comment bằng dấu #
                    if not line_strip or line_strip.startswith('#'):
                        continue
                    if './ips' in line_strip:
                        has_ips = True
                    if 'fuelmet' in line_strip:
                        has_fuelmet = True
                    if 'forever start src/index.js' in line_strip:
                        has_nano = True
    except Exception as e:
        logging.error(f"Lỗi khi đọc file /opt/autorun để kiểm tra dịch vụ: {e}")
    return has_ips, has_fuelmet, has_nano

def get_version_from_js(has_ips, has_fuelmet):
    possible_paths = [
        '/home/Phase_3/GasController.js',
        '/home/giang/Phase_3/GasController.js'
    ]
    cpu_arch = get_cpu_arch()
    
    for path in possible_paths:
        if os.path.exists(path):
            with open(path, 'r') as file:
                content = file.read()
                match = re.search(r'const\s+ver\s*=\s*"([^"]+)"', content)
                if match:
                    version = f"{cpu_arch}-{match.group(1)}"
                    if has_ips and has_fuelmet:
                        return version + "-IPS-Fuelmet"
                    elif has_ips:
                        return version + "-IPS"
                    elif has_fuelmet:
                        return version + "-Fuelmet"
                    return version
    
    version = f"{cpu_arch}-1.0"
    if has_ips and has_fuelmet:
        return version + "-IPS-Fuelmet"
    elif has_ips:
        return version + "-IPS"
    elif has_fuelmet:
        return version + "-Fuelmet"
    return version

def get_port_from_file():
    try:
        with open('/opt/autorun', 'r') as file:
            content = file.read()
            match = re.search(r'(\s\d{4}|\d{5}):localhost:22', content)
            if match:
                port = match.group(1).strip()
                return port
            else:
                logging.error("Không tìm thấy port trong file.")
                return None
    except Exception as e:
        logging.error(f"Lỗi khi đọc port từ file: {e}")
        return None

def get_mac():
    try:
        interface_cmd = "ip route get 1.1.1.1 | grep -oP 'dev \\K\\w+'"
        interface = subprocess.check_output(interface_cmd, shell=True).decode().strip()
        result = subprocess.check_output(f"ip link show {interface}", shell=True).decode()
        mac_match = re.search(r"ether ([\da-fA-F:]+)", result)
        if mac_match:
            return mac_match.group(1)
    except subprocess.CalledProcessError as e:
        print(f"Lỗi khi chạy lệnh ip link: {e}")
        logging.error(f"Lỗi khi chạy lệnh ip link: {e}")
    except Exception as e:
        print(f"Lỗi lấy MAC Address: {e}")
        logging.error(f"Lỗi lấy MAC Address: {e}")
    return "00:00:00:00:00:00"

# ============================================================
# CÁC HÀM SOCKET 8086 (MỚI)
# ============================================================

STATUS_MAP = {
    0x00: 'offline',          # Offline / Power off
    0x01: 'offline',          # Không hoạt động
    0x02: 'offline',          # Chưa sẵn sàng
    0x06: 'sẵn sàng',        # Idle - Sẵn sàng bơm
    0x07: 'gọi',             # Calling - Nhấc vòi / Gọi bơm
    0x08: 'đang bơm',        # Busy / Fueling - Đang bơm xăng
    0x09: 'đang bơm',        # Authorized / Fueling started
    0x0A: 'kết thúc',        # Completed - Đã bơm xong, chờ treo vòi
    0x0B: 'lỗi',             # Error
    0x0C: 'tạm dừng',        # Suspended - Tạm dừng bơm
    0x0E: 'sẵn sàng',        # Idle variant
    0x10: 'sẵn sàng',        # Extended idle - Đã treo vòi, sẵn sàng
    0x11: 'sẵn sàng',        # Post-transaction idle
    0x14: 'đang bơm',        # Fueling variant
    0x20: 'Chuẩn bị',             # Calling - Nhấc vòi / Đang chuẩn bị (lít về 0)
    0x22: 'đang bơm',        # Fueling (xác nhận từ thực tế: lít tăng liên tục)
}

FUEL_MAP = {
    1: {'metro': 'DO 0.05S', 'metroId': 1},
    2: {'metro': 'E5 RON92', 'metroId': 2},
    3: {'metro': 'RON95', 'metroId': 3},
    4: {'metro': 'DO 0.01S', 'metroId': 4},
}

def _calculate_checksum(data):
    total = sum(data)
    return (256 - (total % 256)) % 256

def _build_cmd_0x49(device_id):
    stx = 0x10
    cnt = 0x06
    cmd = 0x49
    cmd_id = 0xFF
    payload = bytearray([stx, cnt, device_id, cmd, cmd_id])
    payload.append(_calculate_checksum(payload))
    return payload

def _parse_pump_response(data, pump_id):
    """
    Parse binary response từ KIT và chuyển thành JSON format GIỐNG HỆT API 6969.
    Xử lý cả NAK (lỗi) và trạng thái offline.
    """
    if not data or len(data) < 5:
        return None
    
    # Kiểm tra NAK (response lỗi - packet ngắn)
    # Kiểm tra NAK (response lỗi - packet ngắn hoặc CMD=0x4E)
    if len(data) < 47 or (len(data) >= 4 and data[3] == 0x4E):
        # Có thể là NAK error response
        if len(data) >= 6:
            error_code = data[4]
            errors = {
                0x81: 'không tìm thấy vòi bơm',
                0x82: 'vòi bơm power off',
                0x83: 'invalid data',
            }
            err_msg = errors.get(error_code, f'mã lỗi 0x{error_code:02X}')
            print(f"[8086] Vòi ID {pump_id}: NAK - {err_msg}")
            logging.error(f"Pump ID {pump_id} NAK: {err_msg}")
        return None  # Trả None → sẽ tạo disconnected entry ở hàm gọi
    
    if sum(data) % 256 != 0:
        logging.error(f"Checksum lỗi cho pump ID {pump_id}")
        return None

    try:
        status_byte = data[4]
        pump_code = struct.unpack('<I', data[5:9])[0]
        lit_raw = struct.unpack('<I', data[9:13])[0]       # mili-lit
        gia = struct.unpack('<I', data[13:17])[0]           # đơn giá
        tien = struct.unpack('<I', data[17:21])[0]          # thành tiền
        ca_lit = struct.unpack('<I', data[21:25])[0]        # lít trong ca
        ca_mlit = struct.unpack('<H', data[25:27])[0]       # mili-lít lẻ trong ca
        tong_lit = struct.unpack('<I', data[27:31])[0]      # tổng lít tích lũy
        tong_mlit = struct.unpack('<H', data[31:33])[0]     # mili-lít lẻ tổng
        cur_shift = struct.unpack('<H', data[33:35])[0]     # mã ca hiện tại
        fuel_type = data[35]                                 # mã nhiên liệu
        rfid_nv = struct.unpack('<I', data[36:40])[0]       # RFID nhân viên
        rfid_tx = struct.unpack('<I', data[40:44])[0]       # RFID tài xế

        status_str = STATUS_MAP.get(status_byte, 'sẵn sàng')
        fuel_info = FUEL_MAP.get(fuel_type, {'metro': 'NONE', 'metroId': fuel_type})
        now = datetime.now()
        utc_now = datetime.utcnow()
        now_str = now.strftime('%d-%m-%Y %H:%M:%S')

        # Kiểm tra trạng thái offline → đánh dấu mất kết nối
        is_disconnected = (status_str == 'offline')
        if is_disconnected:
            print(f"[8086] Vòi ID {pump_id}: Offline (status=0x{status_byte:02X})")

        # Cập nhật cache mã bơm thực tế (chỉ khi vòi đang hoạt động)
        if not is_disconnected and pump_code > 0:
            _last_known_pump[pump_id] = {
                'pump': pump_code,
                'dongia': gia,
                'metro': fuel_info['metro'],
                'metroId': fuel_info['metroId'],
            }

        # Tính toán lít thực tế (đã chia 1000)
        lit_val = 0 if is_disconnected else (lit_raw / 1000.0)

        # Tạo JSON format giống hệt API 6969
        return {
            'timeOut': 0,
            'id': pump_id,
            'com': '127.0.0.18086',
            'status': 'mất kết nối' if is_disconnected else status_str,
            'statusID': status_byte,
            'dongia': gia,
            'lit': lit_val,
            'tien': 0 if is_disconnected else tien,
            'tienOld': 0 if is_disconnected else tien,
            'pump': pump_code,
            'currentmaBom': pump_code,
            'ca_Lit': ca_lit,
            'ca_mLit': ca_mlit,
            'tongsolitdenhientai': tong_lit,
            'totalcare': tong_mlit,
            'macabom': cur_shift,
            'metro': fuel_info['metro'],
            'metroId': fuel_info['metroId'],
            'flag': 0,
            'IDKhachhang': None,
            'thoigianUpdateCuoi': now_str,
            'flagGetCaBom': True,
            'flagGetMaBom': True,
            'lenhsetthoigian_gannhat': None,
            'MaBomMoiNhat': {
                'idca': cur_shift,
                'idcot': pump_id,
                'date': utc_now.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                'startTime': utc_now.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
                'money': tien,
                'mili': lit_val,
                'pos': 0,
                'pump': pump_code,
                'type': fuel_type,
                'id1': rfid_nv,
                'id2': rfid_tx,
                'gia': -1,
                'startTimeDate_Text': now.strftime('%d/%m/%Y %H:%M:%S'),
                'date_Text': now.strftime('%d/%m/%Y %H:%M:%S'),
                'idct': None,
            },
            'CaBomMoiNhat': {
                'idca': cur_shift,
                'gia': gia
            },
            'CaBomCu': [],
            'isGiaBomChange': False,
            'hanmuc': None,
            'isDisconnected': is_disconnected,
            'timeStartDisconnect': utc_now.strftime('%Y-%m-%dT%H:%M:%S.000Z') if is_disconnected else None,
            'isHandleMaBom': False,
            'tienchuachotngay': 0,
            'litchuachotngay': 0,
            'mili': lit_val,
            'money': 0 if is_disconnected else tien,
        }
    except Exception as e:
        logging.error(f"Lỗi khi parse dữ liệu pump ID {pump_id}: {e}")
        return None

def get_pump_ids_from_settings():
    """Đọc danh sách ID vòi bơm từ app_settings.json"""
    paths = ['app_settings.json', '/root/app_settings.json', '/home/app_settings.json']
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    settings = json.load(f)
                    ids = []
                    for pts in settings.get('ptss', []):
                        for disp in pts.get('dispensers', []):
                            ids.append(disp.get('id'))
                    if ids:
                        logging.info(f"Đã đọc {len(ids)} pump IDs từ {path}: {ids}")
                        return ids
            except Exception as e:
                logging.error(f"Lỗi khi đọc {path}: {e}")
    logging.warning("Không tìm thấy app_settings.json, dùng mặc định [1,2,3,4]")
    return [1, 2, 3, 4]

# Lock để tránh 2 thread cùng kết nối socket 8086 đồng thời
_socket_lock = Lock()
_cached_data = None
_cached_time = None
_CACHE_TTL = 1.5  # Dữ liệu cache có hiệu lực trong 1.5 giây

# Cache mã bơm cuối cùng biết được cho mỗi ID vòi (kể cả khi offline)
# Format: {pump_id: {'pump': 14851, 'dongia': 27220, 'metro': '...', 'metroId': 1}}
_last_known_pump = {}

def get_data_from_socket(pump_ids):
    """
    Kết nối tới KIT qua Socket 8086, quét từng vòi bơm.
    Sử dụng Lock + Cache để tránh xung đột khi 2 thread gọi đồng thời.
    Trả về list[dict] giống format của API 6969 /GetfullupdateArr.
    """
    global _cached_data, _cached_time
    
    # Kiểm tra cache: nếu dữ liệu còn mới thì trả về luôn, không cần kết nối lại
    if _cached_data and _cached_time:
        age = (datetime.now() - _cached_time).total_seconds()
        if age < _CACHE_TTL:
            return _cached_data
    
    # Chỉ cho phép 1 thread kết nối socket tại một thời điểm
    with _socket_lock:
        # Double-check cache sau khi lấy được lock (thread khác có thể đã cập nhật)
        if _cached_data and _cached_time:
            age = (datetime.now() - _cached_time).total_seconds()
            if age < _CACHE_TTL:
                return _cached_data
        
        HOST = '127.0.0.1'
        PORT = 8086
        results = []
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5.0)
                s.connect((HOST, PORT))
                
                for pid in pump_ids:
                    try:
                        packet = _build_cmd_0x49(pid)
                        s.sendall(packet)
                        response = s.recv(1024)
                        if response:
                            parsed = _parse_pump_response(response, pid)
                            if parsed:
                                results.append(parsed)
                            else:
                                print(f"[8086] Vòi ID {pid}: Phản hồi không hợp lệ")
                                results.append(_make_disconnected_entry(pid))
                    except Exception as e:
                        print(f"[8086] Lỗi quét vòi ID {pid}: {e}")
                        logging.error(f"Lỗi khi quét pump ID {pid}: {e}")
                        results.append(_make_disconnected_entry(pid))
        except Exception as e:
            print(f"[8086] Không thể kết nối Socket 8086: {e}")
            logging.error(f"Lỗi kết nối Socket 8086: {e}")
            for pid in pump_ids:
                results.append(_make_disconnected_entry(pid))
        
        if results:
            _cached_data = results
            _cached_time = datetime.now()
        
        return results if results else None

def _make_disconnected_entry(pid):
    """Tạo entry mất kết nối theo format 6969, giữ nguyên mã bơm cũ"""
    last = _last_known_pump.get(pid, {})
    last_pump = last.get('pump', 0)
    last_dongia = last.get('dongia', 0)
    last_metro = last.get('metro', '')
    last_metro_id = last.get('metroId', 0)
    now = datetime.now()
    utc_now = datetime.utcnow()
    now_str = now.strftime('%d-%m-%Y %H:%M:%S')
    now_iso = utc_now.strftime('%Y-%m-%dT%H:%M:%S.000Z')
    return {
        'timeOut': 0, 'id': pid, 'com': '127.0.0.18086',
        'status': 'mất kết nối', 'statusID': 0,
        'dongia': last_dongia, 'lit': 0, 'tien': 0, 'tienOld': 0,
        'pump': last_pump, 'currentmaBom': last_pump,
        'ca_Lit': 0, 'ca_mLit': 0,
        'tongsolitdenhientai': 0, 'totalcare': 0,
        'macabom': 0,
        'metro': last_metro, 'metroId': last_metro_id, 'flag': 0,
        'IDKhachhang': None,
        'thoigianUpdateCuoi': now_str,
        'flagGetCaBom': True,
        'flagGetMaBom': True,
        'lenhsetthoigian_gannhat': None,
        'MaBomMoiNhat': {
            'idca': 0, 'idcot': pid,
            'date': now_iso, 'startTime': now_iso,
            'money': 0, 'mili': 0, 'pos': 0,
            'pump': last_pump, 'type': 0,
            'id1': 0, 'id2': 0, 'gia': -1,
            'startTimeDate_Text': now.strftime('%d/%m/%Y %H:%M:%S'),
            'date_Text': now.strftime('%d/%m/%Y %H:%M:%S'),
            'idct': None,
        },
        'CaBomMoiNhat': {'idca': 0, 'gia': last_dongia},
        'CaBomCu': [],
        'isGiaBomChange': False,
        'hanmuc': None,
        'isDisconnected': True,
        'timeStartDisconnect': now_iso,
        'isHandleMaBom': False,
        'tienchuachotngay': 0,
        'litchuachotngay': 0,
        'mili': 0,
        'money': 0,
    }

# ============================================================
# CÁC HÀM API 6969 (CŨ - GIỮ NGUYÊN)
# ============================================================

def get_data_from_url(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Mã trạng thái không phải 200: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Lỗi khi lấy dữ liệu từ URL: {e}")
        return None

# ============================================================
# HÀM LẤY DỮ LIỆU THỐNG NHẤT (TỰ CHỌN MODE)
# ============================================================

# Dict để lưu thời điểm bắt đầu mất kết nối của từng ID vòi: {pump_id: iso_timestamp}
_disconnection_times = {}

def get_pump_data(mode, pump_ids=None):
    """
    Hàm trung gian: tùy mode mà lấy dữ liệu từ Socket hoặc API.
    Trả về list[dict] với cùng format.
    Quản lý logic 'timeStartDisconnect' thống nhất cho cả 2 mode:
      - Chỉ ghi nhận thời gian mất kết nối lần đầu.
      - Xóa khỏi cache khi kết nối lại bình thường.
    """
    if mode == MODE_8086:
        data = get_data_from_socket(pump_ids)
    else:
        data = get_data_from_url("http://localhost:6969/GetfullupdateArr")
        
    if not data:
        return data
        
    # Chuẩn hóa timeStartDisconnect cho toàn bộ dữ liệu trả về
    for item in data:
        pump_id = item.get('id')
        
        # Nhận diện mất kết nối: Kiểm tra cả flag isDisconnected và từ khóa trong status (cho mode 6969)
        status_str = str(item.get('status', '')).lower()
        is_disconnected = item.get('isDisconnected', False) or 'mất kết nối' in status_str
        
        if is_disconnected:
            # Đồng bộ hóa flag để các module khác (như check_mabom) cũng nhận diện được
            item['isDisconnected'] = True

            # Nếu mới mất kết nối (chưa có trong dictionary)
            if pump_id not in _disconnection_times:
                # Nếu API cũ gửi timeStartDisconnect chuẩn, giữ lại. 
                # Nếu không, bám vào thời gian đầu tiên hệ thống Python ghi nhận.
                current_time_iso = item.get('timeStartDisconnect')
                if not current_time_iso: # Fallback
                    utc_now = datetime.utcnow()
                    current_time_iso = utc_now.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                _disconnection_times[pump_id] = current_time_iso
            
            # Ghi đè timeStartDisconnect bằng giá trị đã nhớ để tránh bị đổi liên tục
            item['timeStartDisconnect'] = _disconnection_times[pump_id]
        else:
            # Nếu đang kết nối tốt, xóa khỏi bộ nhớ mất kết nối
            if pump_id in _disconnection_times:
                del _disconnection_times[pump_id]
                
    return data

# ============================================================
# CÁC HÀM GỬI DỮ LIỆU LÊN SERVER (GIỮ NGUYÊN)
# ============================================================

def send_data_to_flask(data, port):
    flask_url = f"http://14.225.192.65/api/receive_data/{port}"
    try:
        # In tóm gọn nội dung gửi lên server
        print(f"[→ SV] Gửi {len(data)} vòi lên port {port}:")
        for d in data:
            print(f"  Vòi {d.get('id')}: {d.get('status')} | Mã:{d.get('pump')} | {d.get('lit',0):.3f}L | {d.get('tien',0):,}đ | {d.get('dongia',0):,}đ/L")
        response = requests.post(flask_url, json=data, timeout=60)
        print(f"[← SV] HTTP {response.status_code}: {response.text[:120]}")
        logging.info(f"Dữ liệu đã gửi tới Flask server. Mã trạng thái: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"[← SV] LỖI gửi lên server: {e}")
        logging.error(f"Lỗi khi gửi dữ liệu tới Flask server: {e}")

def check_getdata_status(port, version, mac):
    request_url = f"http://14.225.192.65/api/request/{port},{version},{mac}"
    try:
        response = requests.get(request_url, timeout=60)
        if response.status_code == 200:
            data = response.json()
            laymabom = data.get('laymabom')
            if laymabom and laymabom != 'Off':
                logging.info(f"Nhận được giá trị laymabom: {laymabom}. Gọi API daylaidulieu.")
                call_daylaidulieu_api(laymabom)
            if data.get('restart') == 'True':
                logging.info("Nhận được lệnh restart. Đang khởi động lại hệ thống.")
                try:
                    result = subprocess.check_output(['reboot', 'now'], stderr=subprocess.STDOUT)
                    logging.info(f"Lệnh thực thi thành công: {result.decode()}")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Lỗi khi thực thi lệnh: {e.output.decode()}")
                except Exception as e:
                    logging.error(f"Lỗi không mong muốn khi thực thi lệnh: {str(e)}")
            if 'ssh' in data and data['ssh']:
                command = data['ssh']
                logging.info(f"Nhận được lệnh SSH: {command}. Đang thực thi lệnh.")
                try:
                    subprocess.Popen(command, shell=True)
                    logging.info(f"Đã bắt đầu thực thi lệnh: {command}")
                except subprocess.CalledProcessError as e:
                    logging.error(f"Lỗi khi thực thi lệnh: {e.output.decode()}")
                except Exception as e:
                    logging.error(f"Lỗi không mong muốn khi thực thi lệnh: {str(e)}")
            return data.get('getdata') == 'On'
        logging.error(f"Mã trạng thái không phải 200 từ check_getdata_status: {response.status_code}")
        return False
    except requests.exceptions.RequestException as e:
        logging.error(f"Lỗi khi kiểm tra trạng thái getdata: {e}")
        return False

def call_daylaidulieu_api(pump_id):
    api_url = f"http://localhost:6969/daylaidulieu/{pump_id}"
    try:
        response = requests.get(api_url, timeout=10)
        logging.info(f"Đã gọi API daylaidulieu cho pump ID {pump_id}. Mã trạng thái: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Lỗi khi gọi API daylaidulieu: {e}")

def send_warning(port, pump_id, warning_type, mabom):
    warning_url = f"http://14.225.192.65/api/warning/{port}/{pump_id}/{warning_type}"
    try:
        response = requests.post(warning_url, json={'mabom': mabom}, timeout=10)
        logging.info(f"Đã gửi cảnh báo cho port {port}, pump ID {pump_id}, loại {warning_type}, mabom {mabom}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Lỗi khi gửi cảnh báo: {e}")

def send_all_disconnected_warning(port):
    warning_url = f"http://14.225.192.65/api/warning/{port}/all/all_disconnection"
    try:
        response = requests.post(warning_url, json={'message': 'Tất cả các vòi đều mất kết nối.'})
        print(f"Đã gửi cảnh báo mất kết nối tất cả cho port {port}")
    except requests.exceptions.RequestException as e:
        print(f"Lỗi khi gửi cảnh báo mất kết nối tất cả: {e}")

# ============================================================
# HÀM BẢO TRÌ HỆ THỐNG (GIỮ NGUYÊN)
# ============================================================

def check_disk_and_clear_logs(threshold=85):
    try:
        output = subprocess.check_output(['df', '-h', '/'], stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()
        for line in lines:
            if line.strip().endswith(' /'):
                parts = line.split()
                if len(parts) >= 5:
                    usage_str = parts[4].replace('%', '')
                    disk_usage_percent = float(usage_str)
                    print(f"Mức sử dụng ổ cứng hiện tại: {disk_usage_percent:.2f}%")
                    logging.info(f"Mức sử dụng ổ cứng hiện tại: {disk_usage_percent:.2f}%")
                    if disk_usage_percent > threshold:
                        print(f"Ổ cứng sử dụng vượt quá {threshold}%. Tiến hành xóa các file log...")
                        logging.info(f"Ổ cứng sử dụng vượt quá {threshold}%. Tiến hành xóa các file log...")
                        try:
                            result1 = subprocess.check_output(
                                "find / -type f -name '*.log' -execdir rm -- '{}' +",
                                shell=True, stderr=subprocess.STDOUT
                            ).decode()
                            print(f"Đã xóa các file log trong toàn bộ hệ thống: {result1}")
                            logging.info(f"Đã xóa các file log trong toàn bộ hệ thống: {result1}")
                            try:
                                result2 = subprocess.check_output(
                                    "find /var/log -type f -name '*.log.*' -exec rm -v {} \\; 2>/dev/null || true",
                                    shell=True, stderr=subprocess.STDOUT
                                ).decode()
                                if result2.strip():
                                    print(f"Đã xóa các file log cũ: {result2}")
                                    logging.info(f"Đã xóa các file log cũ: {result2}")
                                result3 = subprocess.check_output(
                                    "apt-get clean && apt-get autoclean",
                                    shell=True, stderr=subprocess.STDOUT
                                ).decode()
                                logging.info("Đã dọn dẹp cache apt")
                                print("Đã dọn dẹp cache apt")
                                result4 = subprocess.check_output(
                                    "find /tmp -type f -atime +7 -exec rm -v {} \\; 2>/dev/null || true",
                                    shell=True, stderr=subprocess.STDOUT
                                ).decode()
                                if result4.strip():
                                    print(f"Đã xóa file tạm cũ: {result4}")
                                    logging.info(f"Đã xóa file tạm cũ: {result4}")
                            except subprocess.CalledProcessError as e:
                                print(f"Lỗi khi dọn dẹp thêm: {e.output.decode()}")
                                logging.error(f"Lỗi khi dọn dẹp thêm: {e.output.decode()}")
                        except subprocess.CalledProcessError as e:
                            print(f"Lỗi khi xóa file log: {e.output.decode()}")
                            logging.error(f"Lỗi khi xóa file log: {e.output.decode()}")
                        except PermissionError:
                            print("Không đủ quyền để xóa file log. Vui lòng chạy script với quyền sudo.")
                            logging.error("Không đủ quyền để xóa file log. Vui lòng chạy script với quyền sudo.")
                    else:
                        print(f"Ổ cứng sử dụng dưới ngưỡng {threshold}%, không cần xóa file log.")
                        logging.info(f"Ổ cứng sử dụng dưới ngưỡng {threshold}%, không cần xóa file log.")
                break
    except subprocess.CalledProcessError as e:
        print(f"Lỗi khi chạy lệnh df: {e.output.decode()}")
        logging.error(f"Lỗi khi chạy lệnh df: {e.output.decode()}")
    except Exception as e:
        print(f"Lỗi khi kiểm tra ổ cứng: {str(e)}")
        logging.error(f"Lỗi khi kiểm tra ổ cứng: {str(e)}")

# ============================================================
# LOGIC GIÁM SÁT MABOM (GIỮ NGUYÊN)
# ============================================================

lastRestartAll = None
lastNonSequentialRestart = None

def check_mabom(data, mabom_history, file_path, port, connection_status, is_all_disconnect_restart):
    global lastRestartAll, lastNonSequentialRestart
    current_time = datetime.now()
    all_disconnected = True

    try:
        for item in data:
            idcot = item.get('id')
            pump = item.get('pump')
            statusnow = item.get('status')
            mabom_moinhat = item.get('MaBomMoiNhat', {}).get('pump')

            if idcot is None or pump is None:
                continue

            pump_id = str(idcot)
            mabomtiep = pump
            is_disconnected = item.get('isDisconnected', False)

            if not is_disconnected:
                all_disconnected = False

            if pump_id not in connection_status:
                connection_status[pump_id] = {
                    'is_disconnected': is_disconnected,
                    'disconnect_time': current_time if is_disconnected else None,
                    'alert_sent': False,
                    'last_alerted_mabom': None,
                    'mismatch_count': 0,
                    'restart_done': False
                }
            else:
                if is_disconnected:
                    if not connection_status[pump_id]['is_disconnected']:
                        connection_status[pump_id]['is_disconnected'] = True
                        connection_status[pump_id]['disconnect_time'] = current_time
                        connection_status[pump_id]['alert_sent'] = False
                        connection_status[pump_id]['restart_done'] = False
                    else:
                        if current_time - connection_status[pump_id]['disconnect_time'] > timedelta(seconds=65):
                            if not connection_status[pump_id]['alert_sent']:
                                logging.info(f"Pump ID {pump_id} mất kết nối quá 65 giây.")
                                send_warning(port, pump_id, "disconnection", mabomtiep)
                                connection_status[pump_id]['alert_sent'] = True
                else:
                    if connection_status[pump_id]['is_disconnected']:
                        if current_time - connection_status[pump_id]['disconnect_time'] <= timedelta(seconds=65):
                            logging.info(f"Pump ID {pump_id} đã kết nối lại trong vòng 65 giây.")
                        connection_status[pump_id] = {
                            'is_disconnected': False,
                            'disconnect_time': None,
                            'alert_sent': False,
                            'last_alerted_mabom': connection_status[pump_id].get('last_alerted_mabom'),
                            'mismatch_count': connection_status[pump_id].get('mismatch_count', 0),
                            'restart_done': connection_status[pump_id].get('restart_done', False)
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
                    logging.info(f"Mã bơm không khớp lần {connection_status[pump_id]['mismatch_count']} cho pump ID {pump_id}: {mabom_moinhat} != {pump}")

                    if connection_status[pump_id]['mismatch_count'] == 3:
                        if lastNonSequentialRestart is None or (current_time - lastNonSequentialRestart) > timedelta(minutes=10):
                            logging.info(f"Pump ID {pump_id} có mã bơm không khớp 3 lần. Thực hiện restartall.")
                            subprocess.run(['forever', 'restartall'])
                            lastNonSequentialRestart = current_time
                            time.sleep(3)
                            call_daylaidulieu_api(pump_id)
                            send_warning(port, pump_id, "nonsequential", mabomtiep)
                            connection_status[pump_id]['mismatch_count'] = 0
                        else:
                            logging.info("Phát hiện mã bơm không liên tiếp, nhưng đã restartall gần đây. Đợi 10 phút.")
                else:
                    connection_status[pump_id]['mismatch_count'] = 0

                if len(mabom_entries) > 1:
                    previous_mabom = mabom_entries[-2][0]
                    if isinstance(mabomtiep, int) and isinstance(previous_mabom, int):
                        if mabomtiep != previous_mabom + 1:
                            if connection_status[pump_id]['last_alerted_mabom'] != mabomtiep:
                                logging.info(f"Lỗi mã bơm không liên tiếp: Vòi bơm {pump_id} của port {port}.")
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
            if lastRestartAll is None or (current_time - lastRestartAll) > timedelta(minutes=10):
                logging.info("Tất cả các vòi đều mất kết nối. Thực hiện restartall.")
                subprocess.run(['forever', 'restartall'])
                lastRestartAll = current_time
                for conn in connection_status.values():
                    conn['restart_done'] = True
                send_all_disconnected_warning(port)
                is_all_disconnect_restart[0] = True
            else:
                logging.info("Tất cả các vòi mất kết nối, nhưng đã restartall gần đây. Đợi 10 phút.")
        
        if not all_disconnected:
            is_all_disconnect_restart[0] = False

    except Exception as e:
        logging.error(f"Lỗi trong check_mabom: {e}")

# ============================================================
# VÒNG LẶP CHÍNH
# ============================================================

def check_mabom_continuously(port, mabom_file_path, mode, pump_ids):
    if os.path.exists(mabom_file_path):
        try:
            with open(mabom_file_path, 'r') as file:
                mabom_history = json.load(file)
                print(f"Đã tải lịch sử mabom từ {mabom_file_path}")
        except Exception as e:
            print(f"Lỗi khi tải lịch sử mabom: {e}")
            mabom_history = {}
    else:
        mabom_history = {}
        try:
            with open(mabom_file_path, 'w') as file:
                json.dump(mabom_history, file, indent=4)
                print(f"Đã tạo file lịch sử mabom tại {mabom_file_path}")
        except Exception as e:
            print(f"Lỗi khi tạo file lịch sử mabom: {e}")

    connection_status = {}
    is_all_disconnect_restart = [False]

    while True:
        data_from_source = get_pump_data(mode, pump_ids)
        if data_from_source:
            check_mabom(data_from_source, mabom_history, mabom_file_path, port, connection_status, is_all_disconnect_restart)
        else:
            print("Không lấy được dữ liệu từ nguồn")
        time.sleep(2)

def random_sleep_time():
    return random.uniform(4, 8)

_api_fail_count = 0

def send_data_continuously(port, version, mac, mode, pump_ids):
    global _api_fail_count
    while True:
        if check_getdata_status(port, version, mac):
            data_from_source = get_pump_data(mode, pump_ids)
            if data_from_source:
                send_data_to_flask(data_from_source, port)
                print("Dữ liệu đã gửi tới Flask server")
                _api_fail_count = 0
            else:
                _api_fail_count += 1
                source = "Socket 8086" if mode == MODE_8086 else "API 6969"
                print(f"[!] Không kết nối được {source} ({_api_fail_count} lần liên tiếp)")
                # Sau 3 lần thất bại liên tiếp → gửi cảnh báo mất kết nối lên server
                if _api_fail_count >= 3:
                    print(f"[!] Gửi cảnh báo mất kết nối tất cả lên server")
                    send_all_disconnected_warning(port)
                    _api_fail_count = 0
        else:
            print("getdata đang Off")
        
        sleep_duration = random_sleep_time()
        time.sleep(sleep_duration)

# ============================================================
# MAIN
# ============================================================

def main():
    check_disk_and_clear_logs()
    
    # Detect chế độ hoạt động
    mode = detect_mode()
    print(f"========================================")
    print(f"  CHẾ ĐỘ: {'Socket 8086' if mode == MODE_8086 else 'API 6969 (cũ)'}")
    print(f"========================================")
    
    # Lấy danh sách vòi bơm (chỉ cần cho mode 8086)
    pump_ids = None
    if mode == MODE_8086:
        pump_ids = get_pump_ids_from_settings()
        print(f"Danh sách vòi bơm: {pump_ids}")
    
    port = get_port_from_file()
    if not port:
        print("Không tìm thấy port. Thoát.")
        return
    
    mac = get_mac()
    if not mac:
        print("Không tìm thấy MAC. Thoát.")
        return
    
    version = get_version(mode)
    
    print(f"Sử dụng port: {port}")
    print(f"Sử dụng MAC: {mac}")
    print(f"Sử dụng version: {version}")
    
    script_dir = os.path.dirname(os.path.realpath(__file__))
    mabom_file_path = os.path.join(script_dir, 'mabom.json')

    if not os.path.exists(mabom_file_path):
        try:
            with open(mabom_file_path, 'w') as file:
                json.dump({}, file, indent=4)
                print(f"Đã tạo file lịch sử mabom tại {mabom_file_path}")
        except Exception as e:
            print(f"Lỗi khi tạo file lịch sử mabom: {e}")
            return

    mabom_thread = Thread(target=check_mabom_continuously, args=(port, mabom_file_path, mode, pump_ids))
    mabom_thread.start()
    send_data_continuously(port, version, mac, mode, pump_ids)

if __name__ == "__main__":
    main()
