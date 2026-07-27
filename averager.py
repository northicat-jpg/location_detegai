"""传感器数据采集与去极值平均模块

工作流程:
  1. 持续接收传感器距离值
  2. 累积到 N 个样本后, 去掉最大值和最小值
  3. 对剩余数据求平均
  4. 检查距上次发送是否达到间隔时间
  5. 满足条件则写入数据库, 否则丢弃本轮结果

所有参数通过 config.json 的 avg_sample_count / avg_send_interval 设置
"""

import time
from config import AVG_SAMPLE_COUNT, AVG_SEND_INTERVAL


class Averager:
    """采集 N 次 → 去极值平均 → 间隔发送"""

    def __init__(self, sample_count: int | None = None, send_interval: float | None = None):
        self.sample_count = max(sample_count or AVG_SAMPLE_COUNT, 3)
        """每组采集次数, 至少 3 次才能去极值"""

        self.send_interval = send_interval or AVG_SEND_INTERVAL
        """数据库写入最小间隔（秒）"""

        self._readings: list[int] = []
        self._last_raw_readings: list[int] = []  # 最近一轮的原始数据，供终端显示
        self._last_send_time: float = 0.0

    @property
    def last_raw_readings(self) -> list[int]:
        """最近一轮参与去极值平均的原始数据"""
        return list(self._last_raw_readings)

    def add_reading(self, distance: int) -> int | None:
        """
        添加一次采集数据。

        返回:
            距离值 (mm): 满足发送条件时返回去极值平均结果
            None: 数据不足或发送间隔未到
        """
        self._readings.append(distance)

        # 样本不足, 继续收集
        if len(self._readings) < self.sample_count:
            return None

        # 排序后去掉最小和最大值, 对剩余数据求平均
        self._last_raw_readings = list(self._readings)  # 保存原始数据供终端显示
        sorted_r = sorted(self._readings)
        trimmed = sorted_r[1:-1]  # 去除极值
        avg = round(sum(trimmed) / len(trimmed))
        self._readings.clear()

        # 检查发送间隔
        now = time.time()
        if now - self._last_send_time < self.send_interval:
            return None

        self._last_send_time = now
        return avg
