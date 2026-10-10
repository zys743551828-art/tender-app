"""施组工作台后端。

分层（依赖只向下）：
    entrypoints / api  →  services（业务用例）  →  repositories / ports（持久化与外部适配）  →  db / config
任务协议（outbox、租约、结果提交）位于 ``bidwb.tasks``，worker 与 API 共用同一套领域服务。
"""

__version__ = "0.1.0"
