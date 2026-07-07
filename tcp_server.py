"""TCP 服务器 - 接收 EP-W202 WiFi 串口服务器的连接

EP-W202 配置为 TCP Client 模式, 主动连接本机 TCP Server。
本模块负责:
  1. 监听端口, 接受 EP-W202 连接
  2. 接收串口透传数据 (传感器响应)
  3. 发送串口透传数据 (传感器命令)
"""

import socket
import threading
import time

import db
from protocol import parse_frame, CMD_READ
from config import DISTANCE_THRESHOLD_MM, TCP_BACKLOG


class TCPServer:
    """TCP 服务器, 管理与 EP-W202 的连接和数据收发 (支持多客户端)"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, location_map: dict | None = None):
        self.host = host
        self.port = port
        self._server_sock: socket.socket | None = None
        self._clients: list[dict] = []  # 每个元素: {"sock": socket, "addr": tuple, "buf": bytearray, "location": str}
        self._location_map = location_map or {}
        self._running = False
        self._lock = threading.Lock()

        # 最新距离值 (mm), None 表示无有效数据
        self._distance: int | None = None
        # 距离更新事件 (用于通知等待方)
        self._distance_event = threading.Event()

    @property
    def connected(self) -> bool:
        """是否有 EP-W202 已连接"""
        with self._lock:
            return len(self._clients) > 0

    @property
    def distance(self) -> int | None:
        """最新距离值 (mm)"""
        with self._lock:
            return self._distance

    def start(self):
        """启动 TCP 服务器, 开始监听"""
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(TCP_BACKLOG)  # 连接等待队列大小，可通过 config.json 调整
        self._running = True

        t = threading.Thread(target=self._accept_loop, daemon=True)
        t.start()
        print(f"[TCP] 监听 {self.host}:{self.port}, 等待 EP-W202 连接...")

    def stop(self):
        """停止服务器, 关闭所有连接"""
        self._running = False
        with self._lock:
            for c in self._clients:
                try:
                    c["sock"].close()
                except OSError:
                    pass
            self._clients.clear()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        print("[TCP] 服务器已停止")

    def send(self, data: bytes) -> bool:
        """向所有已连接的 EP-W202 广播数据"""
        with self._lock:
            clients = list(self._clients)
        if not clients:
            print("[TCP] 发送失败: 无 EP-W202 连接")
            return False
        success = False
        for c in clients:
            ip_port = f"{c['addr'][0]}:{c['addr'][1]}"
            loc_tag = f"[{c['location']}] {ip_port}" if c['location'] else f"[{ip_port}]"
            try:
                c["sock"].sendall(data)
                success = True
                print(f"{loc_tag} [发送] {data.hex(' ').upper()} ({len(data)} 字节)")
            except OSError as e:
                print(f"{loc_tag} [发送失败] {e}")
        return success

    def read_distance(self, timeout: float = 2.0) -> int | None:
        """
        主动查询距离: 发送读取命令, 等待响应。

        返回:
            距离值 (mm), 超时或异常返回 None
        """
        with self._lock:
            self._distance = None
        self._distance_event.clear()

        if not self.send(CMD_READ):
            return None

        if self._distance_event.wait(timeout):
            return self.distance
        return None

    # === 内部方法 ===

    def _accept_loop(self):
        """后台线程: 持续接受新的客户端连接"""
        while self._running:
            try:
                self._server_sock.settimeout(1.0)
                client, addr = self._server_sock.accept()
                # 根据客户端 IP:PORT 查找对应的库位编码
                client_key = f"{addr[0]}:{addr[1]}"
                location = self._location_map.get(client_key, "")
                if not location:
                    print(f"[TCP] 警告: 客户端 {client_key} 未配置库位映射, 请在 CLIENT_LOCATION_MAP 中添加")

                with self._lock:
                    client_info = {"sock": client, "addr": addr, "buf": bytearray(), "location": location}
                    self._clients.append(client_info)
                    count = len(self._clients)
                loc_tag = f" [{location}]" if location else ""
                print(f"[TCP] EP-W202 已连接: {addr}{loc_tag} (当前连接数: {count})")
                # 为每个连接启动接收线程
                t = threading.Thread(
                    target=self._recv_loop, args=(client, addr, location), daemon=True
                )
                t.start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    time.sleep(0.1)

    def _recv_loop(self, sock: socket.socket, addr: tuple, location: str = ""):
        """后台线程: 接收并解析传感器数据"""
        ip_port = f"{addr[0]}:{addr[1]}"
        loc_tag = f"[{location}] {ip_port}" if location else f"[{ip_port}]"
        while self._running:
            try:
                sock.settimeout(1.0)
                data = sock.recv(1024)
                if not data:
                    print(f"{loc_tag} EP-W202 断开")
                    break
                self._process_data(data, sock)
            except socket.timeout:
                continue
            except ConnectionResetError:
                print(f"{loc_tag} 连接被重置")
                break
            except OSError:
                break

        # 清理连接状态
        with self._lock:
            self._clients[:] = [c for c in self._clients if c["sock"] is not sock]
            print(f"[TCP] 当前连接数: {len(self._clients)}")

    def _process_data(self, data: bytes, sock: socket.socket):
        """处理接收到的数据, 解析传感器帧, 并更新对应库位的数据库状态"""
        with self._lock:
            # 找到对应的客户端缓冲区
            client_info = None
            for c in self._clients:
                if c["sock"] is sock:
                    client_info = c
                    break
            if client_info is None:
                return
            buf = client_info["buf"]
            location = client_info["location"]
            addr = client_info["addr"]

        # 构建带库位+IP:端口标识的前缀
        ip_port = f"{addr[0]}:{addr[1]}"
        loc_tag = f"[{location}] {ip_port}" if location else f"[{ip_port}]"

        # 打印接收数据（锁外打印，避免阻塞）
        print(f"{loc_tag} [接收] {data.hex(' ').upper()} ({len(data)} 字节)")

        with self._lock:
            buf.extend(data)
            # 尝试解析所有完整帧
            while len(buf) >= 7:
                distance, consumed = parse_frame(buf)
                if consumed > 0:
                    del buf[:consumed]
                else:
                    break  # 数据不足, 等待更多

                if distance is not None:
                    self._distance = distance
                    self._distance_event.set()
                    occupied = "占用" if distance < DISTANCE_THRESHOLD_MM else "空闲"
                    print(f"{loc_tag} [距离] {distance} mm ({distance / 10:.1f} cm) → {occupied}")

                    # 自动更新对应库位的数据库状态
                    if location:
                        db.update_location(occupied, location)
