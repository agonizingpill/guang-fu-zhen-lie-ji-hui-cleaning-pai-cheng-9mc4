from enum import StrEnum

class TrialState(StrEnum):
    PENDING='pending'        # 待批准：尚未预留资源
    APPROVED='approved'      # 已批准：整组水额与工时已预留
    RUNNING='running'        # 执行中：至少一个配对已派工
    TERMINATED='terminated'  # 已终止：仅释放未执行预留
    COMPLETED='completed'    # 已完成：形成节水结论或证据不足结论

class PairState(StrEnum):
    PLANNED='planned'        # 配对已建立，等待整组批准
    RESERVED='reserved'      # 该配对两组资源已预留
    ACTIVE='active'          # 至少一组已派工
    EXCLUDED='excluded'      # 退出效果比较（如对照阵列紧急运维提前清洗）
    FINISHED='finished'      # 两组均已验收，可进入效果比较

class ArmState(StrEnum):
    PLANNED='planned'
    RESERVED='reserved'      # 水额已预留
    EXECUTING='executing'    # 已派工，清洗中
    COMPLETED='completed'    # 清洗任务已验收
    RELEASED='released'      # 预留被释放（终止或退出比较），未执行

class ReservationState(StrEnum):
    HELD='held'              # 生效预留，普通派工不可抢占
    CONSUMED='consumed'      # 已被试验派工消费（水已实扣/工时已占用）
    RELEASED='released'      # 终止或退出比较时释放
