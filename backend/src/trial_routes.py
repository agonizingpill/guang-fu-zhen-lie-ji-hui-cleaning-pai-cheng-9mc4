from fastapi import APIRouter,Depends
from sqlalchemy import select
from .database import session
from .auth import current,editor,admin
from .trial_models import WaterSavingTrial,TrialPair,TrialArm,CrewReservation
from .trial_schemas import TrialCreate,ReasonInput
from .field_service import audit
from . import trial_service
router=APIRouter(prefix='/trials')

@router.get('')
def trials(u=Depends(current),db=Depends(session)):return db.scalars(select(WaterSavingTrial).order_by(WaterSavingTrial.id.desc())).all()

@router.get('/{key}/detail')
def detail(key:int,u=Depends(current),db=Depends(session)):
    return {'trial':db.get(WaterSavingTrial,key),
            'pairs':db.scalars(select(TrialPair).where(TrialPair.trial_id==key).order_by(TrialPair.pair_index)).all(),
            'arms':db.scalars(select(TrialArm).where(TrialArm.trial_id==key).order_by(TrialArm.id)).all(),
            'crew_reservations':db.scalars(select(CrewReservation).where(CrewReservation.trial_id==key)).all()}

@router.post('')
def create(body:TrialCreate,u=Depends(editor),db=Depends(session)):return trial_service.create_trial(db,body,u)

@router.post('/{key}/approve')
def approve(key:int,u=Depends(admin),db=Depends(session)):return trial_service.approve(db,key,u)

@router.post('/{key}/terminate')
def terminate(key:int,body:ReasonInput,u=Depends(admin),db=Depends(session)):return trial_service.terminate(db,key,body,u)

@router.post('/{key}/pairs/{pair_key}/exclude')
def exclude(key:int,pair_key:int,body:ReasonInput,u=Depends(admin),db=Depends(session)):return trial_service.exclude_pair(db,key,pair_key,body,u)

@router.post('/{key}/arms/{arm_key}/execute')
def execute(key:int,arm_key:int,u=Depends(admin),db=Depends(session)):return trial_service.execute_arm(db,key,arm_key,u)
