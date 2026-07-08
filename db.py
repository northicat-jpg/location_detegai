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
CONNECTION_MAX_IDLE = 300  # 连接最大空闲时间（秒），超过则丢弃重建

# 连接池：每个元素为 (connection, last_used_timestamp)
_pool = []
_pool_lock = Lock()


def _create_connection():
    """创建新的数据库连接"""
    try:
        conn = pymysql.connect(
            host=MYSQL_URL,
            port=MYSQL_PORT,
            user=MYSQL_USERNAME,
            password=MYSQL_PASSWORD,
            database=MYSQL_NAME,
            charset='utf8mb4',
            autocommit=False,
            # 超时参数
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )
        logger.info(f"创建新的数据库连接 -> {MYSQL_URL}:{MYSQL_PORT}/{MYSQL_NAME}")
        return conn
    except pymysql.err.OperationalError as e:
        logger.error(f"创建数据库连接失败 (OperationalError): {e}")
        return None
    except Exception as e:
        logger.error(f"创建数据库连接失败 (未知错误): {e}")
        return None


def _is_connection_alive(conn):
    """检查连接是否仍然存活"""
    try:
        conn.ping(reconnect=False)  # 仅检查，不自动重连
        return True
    except Exception:
        return False


def get_connection():
    """从连接池获取一个可用连接（线程安全）"""
    now = time.time()
    with _pool_lock:
        # 从池尾向前遍历，移除过期或失效的连接
        for i in range(len(_pool) - 1, -1, -1):
            conn, last_used = _pool[i]
            # 连接空闲太久，直接丢弃（避免使用已被服务端断开的连接）
            if now - last_used > CONNECTION_MAX_IDLE:
                try:
                    conn.close()
                except Exception:
                    pass
                _pool.pop(i)
                logger.debug("丢弃空闲超时的连接")
                continue
            # 检查连接是否存活
            if not _is_connection_alive(conn):
                try:
                    conn.close()
                except Exception:
                    pass
                _pool.pop(i)
                logger.debug("丢弃已断开的连接")
                continue

        # 尝试从池中取一个可用连接
        if _pool:
            conn, _ = _pool.pop()
            logger.debug("从连接池获取连接")
            return conn

        # 池中无可用连接，创建新连接
        return _create_connection()


def return_connection(conn):
    """将连接归还到连接池"""
    if conn is None:
        return
    with _pool_lock:
        # 池已满，直接关闭
        if len(_pool) >= POOL_SIZE:
            try:
                conn.close()
            except Exception:
                pass
            return
        # 检查连接是否存活，存活才放回池中
        if _is_connection_alive(conn):
            _pool.append((conn, time.time()))
        else:
            try:
                conn.close()
            except Exception:
                pass


def save_to_db(sql, params=None):
    """执行 SQL 语句（支持参数化查询，带重试机制）
    
    对 2013 错误（Lost connection）做专门处理：强制丢弃当前连接并重建。
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        conn = None
        cursor = None
        should_discard_conn = False  # 是否需要丢弃连接（不归还池中）
        try:
            conn = get_connection()
            if conn is None:
                logger.error(f"无法获取数据库连接 (尝试 {attempt + 1}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                continue

            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            conn.commit()
            logger.info(f"SQL执行成功: {sql[:80]}{'...' if len(sql) > 80 else ''}")
            return True

        except pymysql.err.OperationalError as e:
            should_discard_conn = True
            last_error = e
            err_code = e.args[0] if e.args else 0
            if err_code == 2013:
                logger.error(f"[错误2013] 与MySQL服务器失去连接 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            else:
                logger.error(f"数据库操作异常 (OperationalError {err_code}, 尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))  # 递增重试间隔

        except pymysql.err.InterfaceError as e:
            should_discard_conn = True
            last_error = e
            logger.error(f"数据库接口错误 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))

        except Exception as e:
            last_error = e
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"SQL执行失败: {sql[:80]}..., 错误: {e}")
            # 非连接类错误，不重试直接返回
            return False

        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            # 只有连接正常时才归还池中
            if conn and not should_discard_conn:
                return_connection(conn)

    logger.error(f"SQL执行最终失败（已重试 {MAX_RETRIES} 次）: {last_error}")
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
