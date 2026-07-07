"""Modbus RTU 通信协议 (超声波传感器)

传感器通过 RS485 转 WiFi 串口服务器 (EP-W202) 连接。
使用标准 Modbus RTU 协议读取保持寄存器。

读寄存器命令 (主机→传感器):
  01 03 01 00 00 01 CRC_L CRC_H  (8字节)
  地址: 0x01, 功能码: 0x03, 起始地址: 0x0100, 读取1个寄存器

响应 (传感器→主机):
  01 03 02 HH LL CRC_L CRC_H  (7字节)
  HH LL = 距离值 (mm)

校验: CRC-16 (Modbus), 低字节在前
"""
def _checksum(data: bytes) -> int:
    """计算 Modbus CRC-16 校验值"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc


# === 主机→传感器 命令 ===

CMD_READ = bytes([0x01, 0x03, 0x01, 0x00, 0x00, 0x01, 0x85, 0xF6])
"""主动读取: 发送后传感器返回一次距离"""

CMD_AUTO_START = bytes([0xA5, 0x0E, 0xB7])
"""开启自动上报: 距离变化时传感器自动返回（DYP-A01 模式）"""

CMD_AUTO_STOP = bytes([0xA5, 0x0F, 0xB8])
"""关闭自动上报（DYP-A01 模式）"""


# === 传感器→主机 响应解析 ===

def parse_frame(buf: bytearray) -> tuple[int | None, int]:
    """
    从缓冲区解析一个完整 Modbus RTU 响应帧。

    帧格式: [地址(1)][功能码(1)][数据长度(1)][数据(2)][CRC_L][CRC_H] = 7字节

    返回:
        (distance_mm, consumed_bytes)
        distance_mm: 距离值(mm), None 表示异常或数据不足
        consumed_bytes: 本次消费的字节数
    """
    # 找帧起始字节 (Modbus 地址 0x01)
    start = -1
    for i in range(len(buf)):
        if buf[i] == 0x01:
            start = i
            break

    if start < 0:
        return None, len(buf)

    if start > 0:
        return None, start

    if len(buf) < 7:
        return None, 0

    # CRC 校验
    frame_without_crc = bytes(buf[:5])
    received_crc = (buf[6] << 8) | buf[5]
    calculated_crc = _checksum(frame_without_crc)

    if calculated_crc != received_crc:
        return None, 7  # CRC 校验失败，跳过整帧

    distance = buf[3] * 256 + buf[4]
    return distance, 7
