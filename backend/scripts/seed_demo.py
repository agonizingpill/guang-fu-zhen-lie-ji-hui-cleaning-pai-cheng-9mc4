from datetime import datetime,timedelta
from sqlalchemy import select,func
from src.database import Base,engine,Session
from src.models import User,ArrayBlock,SoilingSurvey,WashMission
from src.revisit_models import WaterDelivery,FollowupSurvey
from src.auth import hash_password
from src.operations_models import WashCrew
from src.trial_models import WaterSavingTrial,TrialPair,TrialArm
from src.trial_constants import TrialState,PairState,ArmState

def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ['admin','planner','viewer']:
            email=role+'@qingling.test'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password=hash_password('Solar2026!'),role=role))
        for code,minutes in [('CREW-SOUTH',480),('CREW-RIDGE',360)]:
            if not db.scalar(select(WashCrew).where(WashCrew.code==code)):db.add(WashCrew(code=code,max_daily_minutes=minutes))
        blocks=[('SL-A01','南坡一号','南坡',150,23,780,1500),('SL-A02','南坡二号','南坡',120,25,630,1200),('SL-B01','脊线一号','脊线',100,18,520,900),('SL-C01','西坡一号','西坡',80,30,420,600)]
        for code,name,sector,cap,slope,area,water in blocks:
            if not db.scalar(select(ArrayBlock).where(ArrayBlock.code==code)):db.add(ArrayBlock(code=code,name=name,sector=sector,capacity_kw=cap,slope=slope,area_m2=area,water_liters=water))
        db.flush();rows=db.scalars(select(ArrayBlock).order_by(ArrayBlock.id)).all()
        measurements=[('SV-1117-A01',rows[0],800,35,18,3.2,88),('SV-1117-A02',rows[1],820,33,12,2.1,76),('SV-CLOUD-01',rows[2],240,23,8,1.2,18)]
        for code,block,irr,temp,rain,dust,power in measurements:
            if not db.scalar(select(SoilingSurvey).where(SoilingSurvey.code==code)):db.add(SoilingSurvey(code=code,block_id=block.id,capacity_kw=block.capacity_kw,slope=block.slope,irradiance=irr,module_temp=temp,rain_days=rain,dust=dust,observed_kw=power,state='recorded'))
        db.flush()
        block=db.scalar(select(ArrayBlock).where(ArrayBlock.code=='SL-C01'))
        if not db.scalar(select(WaterDelivery).where(WaterDelivery.delivery_code=='WD-DEMO-01')):
            db.add(WaterDelivery(block_id=block.id,delivery_code='WD-DEMO-01',liters=500,source='西坡蓄水池 / 水车02'))
        historical=db.scalar(select(SoilingSurvey).where(SoilingSurvey.code=='SV-DEMO-CLEAN'))
        if not historical:
            historical=SoilingSurvey(code='SV-DEMO-CLEAN',block_id=block.id,capacity_kw=block.capacity_kw,slope=block.slope,irradiance=800,module_temp=35,rain_days=15,dust=2,observed_kw=50,clean_kw=62,predicted_loss=12,recommended_water=100,state='closed')
            db.add(historical);db.flush()
        mission=db.scalar(select(WashMission).where(WashMission.survey_id==historical.id))
        if not mission:
            mission=WashMission(survey_id=historical.id,water_liters=100,available_liters=700,status='accepted',post_kw=62,post_irradiance=800,normalized_kw=62,verified_gain=12,dispatched_at=datetime.utcnow()-timedelta(days=7),accepted_at=datetime.utcnow()-timedelta(days=7))
            db.add(mission);db.flush()
        if not db.scalar(select(FollowupSurvey).where(FollowupSurvey.mission_id==mission.id,FollowupSurvey.days_after==2)):
            db.add(FollowupSurvey(mission_id=mission.id,days_after=2,irradiance=800,observed_kw=61,normalized_kw=61,normalized_loss=100/62,state='stable',baseline_snapshot={'post_kw':62,'post_irradiance':800,'accepted_at':mission.accepted_at.isoformat(),'block_id':block.id,'block_code':block.code,'survey_id':historical.id,'survey_code':historical.code,'threshold_pct':5}))
        seed_trial(db)
        db.commit();print({key:db.scalar(select(func.count()).select_from(model)) for key,model in [('users',User),('blocks',ArrayBlock),('surveys',SoilingSurvey)]})

def seed_trial(db):
    """第四轮扩展：随机节水试验演示。仅建待批准试验，资源在主管批准时才整组预留。"""
    import random as _random
    if db.scalar(select(WaterSavingTrial).where(WaterSavingTrial.code=='WST-DEMO-01')):return
    b1=db.scalar(select(ArrayBlock).where(ArrayBlock.code=='SL-A01'))
    b2=db.scalar(select(ArrayBlock).where(ArrayBlock.code=='SL-A02'))
    crew=db.scalar(select(WashCrew).where(WashCrew.code=='CREW-SOUTH'))
    if not (b1 and b2 and crew):return
    s1=db.scalar(select(SoilingSurvey).where(SoilingSurvey.block_id==b1.id).order_by(SoilingSurvey.id.desc()))
    s2=db.scalar(select(SoilingSurvey).where(SoilingSurvey.block_id==b2.id).order_by(SoilingSurvey.id.desc()))
    if not (s1 and s2):return
    base1=round(b1.area_m2*.6*(1+.1*s1.dust),1);base2=round(b2.area_m2*.6*(1+.1*s2.dust),1)
    trial=WaterSavingTrial(code='WST-DEMO-01',title='南坡同类阵列节水20%随机试验',reduction_pct=20,minutes_per_arm=120,work_date=datetime.utcnow().date()+timedelta(days=1),crew_id=crew.id,seed=42,state=TrialState.PENDING,created_by='planner@qingling.test',
        pairing_basis={'rule':'容量/坡度/面积/目测积灰归一化偏差贪心配对','pairs':[{'blocks':[b1.code,b2.code],'distance':0.2,'parts':{'capacity_pct':0.2,'slope_pct':0.1,'area_pct':0.3,'dust_pct':0.2}}],'unpaired':[],'similarity_threshold':'distance<=0.35'},
        randomization={'seed':42,'assignment':{}})
    db.add(trial);db.flush()
    pair=TrialPair(trial_id=trial.id,pair_index=1,state=PairState.PLANNED,similarity=trial.pairing_basis['pairs'][0]);db.add(pair);db.flush()
    rng=_random.Random(42);r1,r2=rng.random(),rng.random()
    treatment=b1.id if r1<=r2 else b2.id
    assignment={}
    for b,s,base,r in ((b1,s1,base1,r1),(b2,s2,base2,r2)):
        group='treatment' if b.id==treatment else 'control'
        planned=round(base*.8,3) if group=='treatment' else round(base,3)
        db.add(TrialArm(trial_id=trial.id,pair_id=pair.id,block_id=b.id,survey_id=s.id,group=group,planned_liters=planned,baseline_liters=base,state=ArmState.PLANNED,
            evidence={'block_code':b.code,'survey_code':s.code,'irradiance':s.irradiance,'module_temp':s.module_temp,'observed_kw':s.observed_kw,'predicted_clean_kw':s.clean_kw,'predicted_loss_kw':s.predicted_loss,'model_holdout_mae_kw':(s.model_evidence or {}).get('holdout_mae_kw'),'model_reference_sha256':(s.model_evidence or {}).get('sha256')}))
        assignment[b.code]={'group':group,'random_value':round(r,6),'rule':'Random(seed).random()，较小者入试验组'}
    trial.randomization={'seed':42,'assignment':assignment}
if __name__=='__main__':seed()
