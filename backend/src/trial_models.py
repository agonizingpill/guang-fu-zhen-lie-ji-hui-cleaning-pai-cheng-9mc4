from datetime import date,datetime
from sqlalchemy import String,Float,Integer,ForeignKey,JSON,CheckConstraint,Date,DateTime,Boolean,Text,func
from sqlalchemy.orm import Mapped,mapped_column
from .database import Base

class WaterSavingTrial(Base):
    __tablename__='water_saving_trials'
    __table_args__=(CheckConstraint('reduction_pct>0 AND reduction_pct<100'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    code:Mapped[str]=mapped_column(String(50),unique=True)
    title:Mapped[str]=mapped_column(String(160))
    reduction_pct:Mapped[float]=mapped_column(Float)          # 试验组计划节水百分比
    minutes_per_arm:Mapped[int]=mapped_column(Integer)        # 每组班组工时（分钟）
    work_date:Mapped[date]=mapped_column(Date)
    crew_id:Mapped[int]=mapped_column(ForeignKey('wash_crews.id'))
    seed:Mapped[int]=mapped_column(Integer)                   # 随机分组用种子，保留分组可复现依据
    pairing_basis:Mapped[dict]=mapped_column(JSON)            # 同类配对口径与逐对相似度证据
    randomization:Mapped[dict]=mapped_column(JSON)            # 每个阵列的随机指派与随机数
    state:Mapped[str]=mapped_column(String(24),default='pending')
    conclusion:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    terminate_reason:Mapped[str]=mapped_column(String(500),default='')
    created_by:Mapped[str]=mapped_column(String(120),default='')
    approved_by:Mapped[str]=mapped_column(String(120),default='')
    terminated_by:Mapped[str]=mapped_column(String(120),default='')
    created_at:Mapped[datetime]=mapped_column(DateTime,server_default=func.now())
    approved_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    terminated_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)

class TrialPair(Base):
    __tablename__='trial_pairs'
    id:Mapped[int]=mapped_column(primary_key=True)
    trial_id:Mapped[int]=mapped_column(ForeignKey('water_saving_trials.id'))
    pair_index:Mapped[int]=mapped_column(Integer)
    state:Mapped[str]=mapped_column(String(24),default='planned')
    similarity:Mapped[dict]=mapped_column(JSON)               # 容量/坡度/面积/积灰偏差快照
    exclude_reason:Mapped[str]=mapped_column(String(500),default='')
    excluded_by:Mapped[str]=mapped_column(String(120),default='')
    excluded_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)

class TrialArm(Base):
    __tablename__='trial_arms'
    __table_args__=(CheckConstraint('planned_liters>0 AND reserved_liters>=0 AND consumed_liters>=0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    trial_id:Mapped[int]=mapped_column(ForeignKey('water_saving_trials.id'))
    pair_id:Mapped[int]=mapped_column(ForeignKey('trial_pairs.id'))
    block_id:Mapped[int]=mapped_column(ForeignKey('array_blocks.id'))
    survey_id:Mapped[int]=mapped_column(ForeignKey('soiling_surveys.id'))
    mission_id:Mapped[int|None]=mapped_column(ForeignKey('wash_missions.id'),nullable=True)
    group:Mapped[str]=mapped_column(String(16))               # control 对照标准水量 / treatment 试验节水
    planned_liters:Mapped[float]=mapped_column(Float)         # 该组按方案的计划水量
    baseline_liters:Mapped[float]=mapped_column(Float)        # 标准建议水量（试验组节水前口径）
    reserved_liters:Mapped[float]=mapped_column(Float,default=0)  # 批准时预留水量
    consumed_liters:Mapped[float]=mapped_column(Float,default=0)  # 实际派工扣减水量
    state:Mapped[str]=mapped_column(String(24),default='planned')
    # 校正前后观测条件与误差快照，保留作为结论证据
    evidence:Mapped[dict|None]=mapped_column(JSON,nullable=True)

class CrewReservation(Base):
    __tablename__='crew_reservations'
    __table_args__=(CheckConstraint('minutes>0 AND used_minutes>=0'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    trial_id:Mapped[int]=mapped_column(ForeignKey('water_saving_trials.id'))
    pair_id:Mapped[int]=mapped_column(ForeignKey('trial_pairs.id'))
    crew_id:Mapped[int]=mapped_column(ForeignKey('wash_crews.id'))
    work_date:Mapped[date]=mapped_column(Date)
    minutes:Mapped[int]=mapped_column(Integer)                # 预留工时（两组合计）
    used_minutes:Mapped[int]=mapped_column(Integer,default=0) # 已被试验派工消费
    state:Mapped[str]=mapped_column(String(24),default='held')
