#!/usr/bin/python
# -*- coding:utf-8 -*-

from enum import Enum


class LocationStatus(Enum):
    # 空闲 
	IDLE = "0"
	# 无货 
	EMPTY = "2"
	# 有货 
	STOCK = "4"
	# 取货锁定: 有货不能出库 
	PICK_LOCK = "6"
	# 放货预留: 入库预留库位 
	DROP_LOCK = "8"
	# 库位锁定: 无货不能放货 
	INSTOCK_RESERVED = "10"
	# 出库预留： 出库预留库位 
	OUTSTOCK_RESERVED = "12"
	# 空托盘 
	PALLET = "14"
