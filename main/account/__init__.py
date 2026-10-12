# -*- coding: utf-8 -*-
"""积磊账号体系：登录态、会员权益、按次计量与功能门控。

对外主要使用 AccountManager 单例（``get_account()``）。所有网络访问都不抛到
业务调用方——门控一律返回"允许"优先，保证网络抖动永远不阻断正常截图。
"""
from .session import AccountManager, get_account

__all__ = ["AccountManager", "get_account"]
