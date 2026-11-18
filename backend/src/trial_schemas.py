from datetime import date
from pydantic import BaseModel,Field,field_validator
from .revisit_schemas import Inputs

class TrialCreate(Inputs):
    title:str=Field(min_length=3,max_length=160)
    block_ids:list[int]=Field(min_length=2)
    reduction_pct:float=Field(gt=0,lt=100)
    minutes_per_arm:int=Field(ge=1,le=1440)
    work_date:date
    crew_id:int
    seed:int=Field(default=42,ge=0,le=2_000_000_000)
    @field_validator('title')
    @classmethod
    def nonempty(cls,v):
        if not v.strip():raise ValueError('不能为空')
        return v.strip()

class ReasonInput(Inputs):
    reason:str=Field(min_length=5,max_length=500)
    @field_validator('reason')
    @classmethod
    def reason_nonempty(cls,v):
        if len(v.strip())<5:raise ValueError('处置依据至少5字')
        return v.strip()
