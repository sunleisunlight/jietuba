# -*- coding: utf-8 -*-
"""积磊账号 / 控制中心接入常量。"""

# 产品 ID 必须与控制中心注册的产品一致。
PRODUCT_ID = "jilei-screenshot"

# 控制中心地址：优先品牌域名 jilei.cc，请求失败时自动故障转移到已上线的
# cc.sunget.top。两者由同一套服务端提供服务，接口合同完全一致。
BASE_URLS = (
    "https://cc.jilei.cc",
    "https://cc.sunget.top",
)

# 鉴权头（与积磊其它桌面客户端一致，字段名不可改）
H_TOKEN = "X-SunGet-Token"
H_PHONE = "X-SunGet-User-Phone"
H_DEVICE = "X-SunGet-Device-ID"

# 本机平台标识
import sys
PLATFORM = "macos" if sys.platform == "darwin" else "windows"

# 游客（未登录设备）备注免费次数；登录后注册赠送次数。两者都由服务端权威发放，
# 这里仅用于离线/弱网时的本地兜底显示，不作为扣费依据。
GUEST_NOTE_UNITS_FALLBACK = 20
REGISTER_GIFT_UNITS_FALLBACK = 1000

# 备注计量动作在服务端的单位数（创建一条备注 = 1 个单位）。
NOTE_UNITS = 1

# 结账页只允许打开的品牌域名（白名单），其它链接不自动外跳。
CHECKOUT_HOST_SUFFIXES = ("jilei.cc", "sunget.top")
