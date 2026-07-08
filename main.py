"""超声波库位检测系统 - 主程序

硬件连接:
  DYP-A01 超声波传感器 --[RS485]--> EP-W202 WiFi串口服务器 --[WiFi/TCP]--> 电脑

使用方式:
  python main.py              # 默认配置启动
  python main.py --port 9000  # 指定端口
  python main.py --once       # 单次测距后退出
"""

import argparse
import time
import sys
import db

from tcp_server import TCPServer
from config import TCP_HOST, TCP_PORT, MEASURE_INTERVAL, QUERY_INTERVAL, DISTANCE_THRESHOLD_MM, CLIENT_LOCATION_MAP



def wait_connection(server: TCPServer) -> bool:
    """等待 EP-W202 连接, 返回是否成功"""
    print("等待 EP-W202 连接... (请确认模块已上电并配置好)")
    try:
        while not server.connected:
            time.sleep(0.5)
        return True
    except KeyboardInterrupt:
        return False


def mode_single(server: TCPServer):
    """单次测距模式: 读取一次距离后退出"""
    dist = server.read_distance()
    if dist is not None:
        print(f"距离: {dist} mm ({dist / 10:.1f} cm)")
    else:
        print("测距失败")
        sys.exit(1)

def mode_continuous(server: TCPServer, interval: float):
    """连续测距模式: 持续读取并显示"""
    print(f"连续测距中 (间隔 {interval}s, Ctrl+C 退出)\n")
    count = 0
    try:
        
        while True:
            dist = server.read_distance()
            count += 1
            if dist is not None:
                occupied = "占用" if dist < DISTANCE_THRESHOLD_MM else "空闲"

                print(
                    f"  [{count:>4}] {dist:>5} mm ({dist / 10:>6.1f} cm)  [{occupied}]"
                )
            else:
                print(f"  [{count:>4}] 读取失败")
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n共测量 {count} 次")


def mode_monitor(server: TCPServer, interval: float):
    """监控模式: 自动上报, 仅打印变化"""
    from protocol import CMD_AUTO_START, CMD_AUTO_STOP

    print("开启自动上报模式 (Ctrl+C 退出)\n")
    server.send(CMD_AUTO_START)
    last_dist = None
    try:
        while True:
            time.sleep(interval)
            dist = server.distance
            if dist is not None and dist != last_dist:
                occupied = "占用" if dist < DISTANCE_THRESHOLD_MM else "空闲"
                print(f"  距离变化: {dist} mm ({dist / 10:.1f} cm)  [{occupied}]")
                last_dist = dist
    except KeyboardInterrupt:
        server.send(CMD_AUTO_STOP)
        print("\n已关闭自动上报")


def main():
    parser = argparse.ArgumentParser(description="超声波库位检测系统")
    parser.add_argument("--host", default=TCP_HOST, help=f"监听地址 (默认 {TCP_HOST})")
    parser.add_argument("--port", type=int, default=TCP_PORT, help=f"监听端口 (默认 {TCP_PORT})")
    parser.add_argument("--interval", type=float, default=QUERY_INTERVAL, help=f"查询+SQL更新间隔秒数 (默认 {QUERY_INTERVAL}s)")
    parser.add_argument("--once", action="store_true", help="单次测距后退出")
    parser.add_argument("--monitor", action="store_true", help="自动上报监控模式")
    args = parser.parse_args()

    server = TCPServer(host=args.host, port=args.port, location_map=CLIENT_LOCATION_MAP)
    server.start()

    try:
        if not wait_connection(server):
            return

        if args.once:
            mode_single(server)
        elif args.monitor:
            mode_monitor(server, args.interval)
        else:
            mode_continuous(server, args.interval)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
    # db.update_location("占用", "H1J-ZSJ06-01")

