"""数据库操作模块 - 库位状态记录"""
import logging
import time
import pymysql
from pymysql.cursors import DictCursor
from datetime import datetime
from threading import Lock

from config import MYSQL_URL, MYSQL_PORT, MYSQL_USERNAME, MYSQL_PASSWORD, MYSQL_NAME, DB_POOL_SIZE
from const import LocationStatus

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 连接池配置
# POOL_SIZE 从 config.json 的 db_pool_size 读取，建议 ≥ (客户端数 × 端口数) × 1.5
POOL_SIZE = DB_POOL_SIZE
MAX_RETRIES = 3        # 执行失败最大重试次数
RETRY_DELAY = 1.0      # 重试间隔（秒）

# 连接池
_pool = []
_pool_lock = Lock()


def _create_connection():
    """创建新的数据库连接"""
    return pymysql.Connect(
        host=MYSQL_URL,
        port=MYSQL_PORT,
        user=MYSQL_USERNAME,
        password=MYSQL_PASSWORD,
        database=MYSQL_NAME,
        charset='utf8mb4',
        autocommit=False,
        # 关键：设置连接超时和自动重连参数
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
    )


def get_connection():
    """从连接池获取一个可用连接（线程安全）"""
    with _pool_lock:
        # 尝试从池中取一个可用连接
        for i in range(len(_pool) - 1, -1, -1):
            conn = _pool[i]
            try:
                conn.ping(reconnect=True)
                # ping 成功，从池中取出返回
                _pool.pop(i)
                return conn
            except Exception:
                # 连接已失效，从池中移除
                try:
                    conn.close()
                except Exception:
                    pass
                _pool.pop(i)

        # 池中无可用连接，创建新连接
        try:
            conn = _create_connection()
            logger.info("创建新的数据库连接")
            return conn
        except Exception as e:
            logger.error(f"创建数据库连接失败: {e}")
            return None


def return_connection(conn):
    """将连接归还到连接池"""
    if conn is None:
        return
    with _pool_lock:
        try:
            # 归还前检查连接是否仍然存活
            conn.ping(reconnect=True)
            if len(_pool) < POOL_SIZE:
                _pool.append(conn)
            else:
                conn.close()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


def save_to_db(sql, params=None):
    """执行 SQL 语句（支持参数化查询，带重试机制）"""
    for attempt in range(MAX_RETRIES):
        conn = None
        cursor = None
        operational_error = False
        try:
            conn = get_connection()
            if conn is None:
                logger.error(f"无法执行SQL: 数据库未连接 (尝试 {attempt + 1}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                continue

            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            conn.commit()
            logger.info(f"SQL执行成功: {sql}")
            return True

        except pymysql.err.OperationalError as e:
            # 连接断开类错误，需要重连
            operational_error = True
            logger.error(f"数据库连接异常 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            # 连接失效后不归还到池中，下次循环会创建新连接

        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"SQL执行失败: {sql}, 错误: {e}")
            return False

        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            # 只有非 OperationalError 时才归还连接
            if conn and not operational_error:
                return_connection(conn)

    logger.error(f"SQL执行最终失败（已重试 {MAX_RETRIES} 次）: {sql}")
    return False


def save_location_data(code, value):
    """保存库位状态数据（使用参数化查询防SQL注入）"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 传感器只更新有货、无货、托盘、未知 4种状态
    sql = "UPDATE lms_location SET status=%s,update_time=%s,material = '货物' WHERE del_flag = '0' and code=%s and status in ('0','2','4','14')"
    return save_to_db(sql, (value.value, current_time, code))


def update_location(occupied, location):
    """更新库位状态"""
    if occupied == "占用":
        return save_location_data(location, LocationStatus.STOCK)
    else:
        return save_location_data(location, LocationStatus.EMPTY)
