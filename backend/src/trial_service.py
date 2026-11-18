import random
from datetime import datetime
from sqlalchemy import select,func
from fastapi import HTTPException
from .models import ArrayBlock,SoilingSurvey,WashMission
from .operations_models import WashCrew,WorkPermit
from .trial_models import WaterSavingTrial,TrialPair,TrialArm,CrewReservation
from .trial_constants import TrialState,PairState,ArmState,ReservationState
from .field_service import require,audit
from .power_model import train_reference

# ---- 预留口径：普通派工与试验派工共用同一套资源视图，held 预留不可抢占 ----
def held_water_map(db,block_ids):
    if not block_ids:return {}
    rows=db.execute(select(TrialArm.block_id,func.coalesce(func.sum(TrialArm.reserved_liters),0)).where(TrialArm.block_id.in_(block_ids),TrialArm.state==ArmState.RESERVED).group_by(TrialArm.block_id)).all()
    return {bid:float(total) for bid,total in rows}

def held_crew_minutes(db,crew_id,work_date):
    # 已释放行净额为0，须在 SQL 层 COALESCE 保留，避免 Python 端 or 0 吞掉整组求和
    return int(db.scalar(select(func.coalesce(func.sum(CrewReservation.minutes-CrewReservation.used_minutes),0)).where(CrewReservation.crew_id==crew_id,CrewReservation.work_date==work_date,CrewReservation.state==ReservationState.HELD)))

def held_arm_for_survey(db,survey_id):
    return db.scalar(select(TrialArm).where(TrialArm.survey_id==survey_id,TrialArm.state.in_([ArmState.RESERVED,ArmState.EXECUTING])))

def guard_normal_dispatch(db,mission):
    """普通（非试验）派工不得消费试验预留水额、工时，也不能顶替试验组。"""
    arm=held_arm_for_survey(db,mission.survey_id)
    if arm:raise HTTPException(409,'该巡测属于已批准节水试验分组，普通派工不能抢占试验预留；如需紧急运维，请先在试验页将配对退出比较')

def _latest_assessed_survey(db,block_id):
    return db.scalar(select(SoilingSurvey).where(SoilingSurvey.block_id==block_id,SoilingSurvey.state=='assessed').order_by(SoilingSurvey.id.desc()))

def _pair_blocks(block_ids,blocks,surveys):
    """同类阵列贪心配对：容量、坡度、面积、积灰偏差最小者优先。"""
    remaining=list(block_ids);pairs=[];basis=[]
    def metric(bid):
        s=surveys[bid];b=blocks[bid]
        return (b.capacity_kw,b.slope,b.area_m2,s.dust)
    cap_span=max(1.0,max(blocks[i].capacity_kw for i in block_ids)-min(blocks[i].capacity_kw for i in block_ids))
    slope_span=max(1.0,max(blocks[i].slope for i in block_ids)-min(blocks[i].slope for i in block_ids))
    area_span=max(1.0,max(blocks[i].area_m2 for i in block_ids)-min(blocks[i].area_m2 for i in block_ids))
    dust_span=max(0.1,max(surveys[i].dust for i in block_ids)-min(surveys[i].dust for i in block_ids))
    def distance(x,y):
        bx,by=blocks[x],blocks[y];sx,sy=surveys[x],surveys[y]
        parts={'capacity_pct':abs(bx.capacity_kw-by.capacity_kw)/cap_span,'slope_pct':abs(bx.slope-by.slope)/slope_span,'area_pct':abs(bx.area_m2-by.area_m2)/area_span,'dust_pct':abs(sx.dust-sy.dust)/dust_span}
        score=sum(parts.values())/4
        return score,parts
    while len(remaining)>=2:
        remaining.sort(key=metric)
        x=remaining[0];best=None
        for y in remaining[1:]:
            score,parts=distance(x,y)
            if best is None or score<best[0]:best=(score,y,parts)
        score,y,parts=best
        pairs.append((x,y))
        basis.append({'blocks':[blocks[x].code,blocks[y].code],'distance':round(score,4),'parts':{k:round(v,4) for k,v in parts.items()}})
        remaining.remove(x);remaining.remove(y)
    unpaired=[blocks[i].code for i in remaining]
    return pairs,basis,unpaired

def create_trial(db,body,user):
    ids=list(dict.fromkeys(body.block_ids))
    if len(ids)<2:raise HTTPException(409,'至少选择两个同类阵列才能配对')
    if len(ids)%2==1:raise HTTPException(409,'参与阵列须为偶数，最后一个无同类配对的阵列不能入组')
    crew=require(db,WashCrew,body.crew_id)
    if not crew.active:raise HTTPException(409,'班组已停用，不能承担试验')
    blocks={};surveys={}
    for bid in ids:
        block=require(db,ArrayBlock,bid,True)
        if block.cleaning_state=='washing':raise HTTPException(409,f'{block.code} 清洗执行中，不能纳入试验')
        survey=_latest_assessed_survey(db,bid)
        if not survey:raise HTTPException(409,f'{block.code} 没有已评估巡测，无法按相同观测条件入组')
        if survey.predicted_loss is None or survey.predicted_loss<=0:raise HTTPException(409,f'{block.code} 巡测未见积灰损失，不应安排清洗试验')
        existing=held_arm_for_survey(db,survey.id)
        if existing:raise HTTPException(409,f'{block.code} 已在生效试验中，不能重复入组')
        if db.scalar(select(WashMission).where(WashMission.survey_id==survey.id)):raise HTTPException(409,f'{block.code} 该巡测已有清洗任务，不能再编入试验')
        blocks[bid]=block;surveys[bid]=survey
    pairs,basis,unpaired=_pair_blocks(ids,blocks,surveys)
    code='WST-'+datetime.utcnow().strftime('%m%d')+'-'+str(body.seed)
    n=db.scalar(select(func.count()).select_from(WaterSavingTrial)) or 0
    while db.scalar(select(WaterSavingTrial).where(WaterSavingTrial.code==code)):
        n+=1;code=f'WST-{datetime.utcnow().strftime("%m%d")}-{body.seed}-{n}'
    trial=WaterSavingTrial(code=code,title=body.title,reduction_pct=body.reduction_pct,minutes_per_arm=body.minutes_per_arm,work_date=body.work_date,crew_id=body.crew_id,seed=body.seed,state=TrialState.PENDING,created_by=user.email,
        pairing_basis={'rule':'容量/坡度/面积/目测积灰归一化偏差贪心配对','pairs':basis,'unpaired':unpaired,'similarity_threshold':'distance<=0.35'},randomization={})
    db.add(trial);db.flush()
    rng=random.Random(body.seed);randomization={}
    for idx,(x,y) in enumerate(pairs,start=1):
        pair=TrialPair(trial_id=trial.id,pair_index=idx,state=PairState.PLANNED,similarity=basis[idx-1])
        db.add(pair);db.flush()
        rx,ry=rng.random(),rng.random()
        # 随机数较小者进入试验（节水）组，另一组为对照（标准水量）
        treatment_id=x if rx<=ry else y;control_id=y if treatment_id==x else x
        for bid in (x,y):
            survey=surveys[bid];block=blocks[bid]
            baseline=float(survey.recommended_water)
            if baseline is None or baseline<=0:raise HTTPException(409,f'{block.code} 缺少标准建议水量，无法确定节水口径')
            group='treatment' if bid==treatment_id else 'control'
            planned=round(baseline*(1-body.reduction_pct/100.0),3) if group=='treatment' else round(baseline,3)
            if planned<=0:raise HTTPException(409,f'{block.code} 节水后水量为0，请降低节水比例')
            arm=TrialArm(trial_id=trial.id,pair_id=pair.id,block_id=bid,survey_id=survey.id,group=group,planned_liters=planned,baseline_liters=round(baseline,3),state=ArmState.PLANNED,
                evidence={'block_code':block.code,'survey_code':survey.code,'irradiance':survey.irradiance,'module_temp':survey.module_temp,'observed_kw':survey.observed_kw,'predicted_clean_kw':survey.clean_kw,'predicted_loss_kw':survey.predicted_loss,'model_holdout_mae_kw':(survey.model_evidence or {}).get('holdout_mae_kw'),'model_reference_sha256':(survey.model_evidence or {}).get('sha256')})
            db.add(arm)
            randomization[block.code]={'group':group,'random_value':round(rx if bid==x else ry,6),'rule':'Random(seed).random()，较小者入试验组'}
        pair.similarity={**basis[idx-1],'treatment_block':blocks[treatment_id].code,'control_block':blocks[control_id].code}
    trial.randomization={'seed':body.seed,'assignment':randomization}
    audit(db,user,f'创建节水试验 {code}：{len(pairs)}个同类配对，节水{body.reduction_pct}%，待批准');db.commit();return trial

def approve(db,key,user):
    trial=require(db,WaterSavingTrial,key,True)
    if trial.state!=TrialState.PENDING:raise HTTPException(409,'仅待批准试验可以整组批准')
    arms=db.scalars(select(TrialArm).where(TrialArm.trial_id==trial.id).with_for_update()).all()
    pairs=db.scalars(select(TrialPair).where(TrialPair.trial_id==trial.id)).all()
    block_ids=sorted({a.block_id for a in arms})
    blocks={bid:require(db,ArrayBlock,bid,True) for bid in block_ids}
    crew=require(db,WashCrew,trial.crew_id,True)
    if not crew.active:raise HTTPException(409,'班组已停用，不能批准试验')
    # 整组校验：任一阵列水额不足，整组不生效
    held=held_water_map(db,block_ids)
    need_by_block={}
    for a in arms:need_by_block[a.block_id]=need_by_block.get(a.block_id,0)+a.planned_liters
    for bid,need in need_by_block.items():
        block=blocks[bid]
        if block.cleaning_state=='washing':raise HTTPException(409,f'{block.code} 清洗执行中，整组预留不生效')
        available=block.water_liters-held.get(bid,0)
        if need>available+1e-6:raise HTTPException(409,f'{block.code} 扣除既有试验预留后余水{available:.1f}L，不足试验预留{need:.1f}L，整组不生效')
    # 整组校验：班组工时不足，整组不生效（普通派工经许可占用的容量同样不可抢占）
    permit_used=db.scalar(select(func.coalesce(func.sum(WorkPermit.minutes),0)).where(WorkPermit.crew_id==crew.id,WorkPermit.work_date==trial.work_date,WorkPermit.state.in_(['signed','used']))) or 0
    trial_need=trial.minutes_per_arm*len(arms)
    if int(permit_used)+held_crew_minutes(db,crew.id,trial.work_date)+trial_need>crew.max_daily_minutes:
        raise HTTPException(409,'班组当日工时容量不足，整组预留不生效')
    for a in arms:
        a.reserved_liters=a.planned_liters;a.state=ArmState.RESERVED
    for p in pairs:
        p.state=PairState.RESERVED
        db.add(CrewReservation(trial_id=trial.id,pair_id=p.id,crew_id=crew.id,work_date=trial.work_date,minutes=trial.minutes_per_arm*2,state=ReservationState.HELD))
    trial.state=TrialState.APPROVED;trial.approved_by=user.email;trial.approved_at=datetime.utcnow()
    audit(db,user,f'批准节水试验 {trial.code}：整组预留水额{sum(need_by_block.values()):.1f}L、工时{trial_need}分钟');db.commit();return trial

def execute_arm(db,trial_key,arm_key,user):
    trial=require(db,WaterSavingTrial,trial_key,True)
    if trial.state not in [TrialState.APPROVED,TrialState.RUNNING]:raise HTTPException(409,'试验未批准或已终止/完成，不能派工')
    arm=require(db,TrialArm,arm_key,True)
    if arm.trial_id!=trial.id:raise HTTPException(409,'分组不属于该试验')
    if arm.state!=ArmState.RESERVED:raise HTTPException(409,'该分组未处于已预留状态（可能已派工或预留已释放）')
    survey=require(db,SoilingSurvey,arm.survey_id,True)
    if survey.state!='assessed':raise HTTPException(409,'巡测已失效或已有清洗排程，不能执行该分组')
    block=require(db,ArrayBlock,arm.block_id,True)
    if block.cleaning_state=='washing':raise HTTPException(409,'同阵列已有执行中的清洗任务')
    if db.scalar(select(WashMission).where(WashMission.survey_id==survey.id)):raise HTTPException(409,'该巡测已有清洗任务')
    # 预留阶段不动账面；实扣时该阵列账面须仍覆盖本分组计划水量，
    # 其余 held 预留（同阵列至多一个生效分组）已在批准与普通派工两侧共同保护
    if arm.planned_liters>block.water_liters:raise HTTPException(409,f'{block.code} 水车余量{block.water_liters:.1f}L不足{arm.planned_liters:.1f}L，请先补水')
    mission=WashMission(survey_id=survey.id,water_liters=arm.planned_liters,available_liters=block.water_liters)
    db.add(mission);db.flush()
    block.water_liters=round(block.water_liters-arm.planned_liters,3);block.cleaning_state='washing'
    mission.status='dispatched';mission.dispatched_at=datetime.utcnow();survey.state='scheduled'
    arm.mission_id=mission.id;arm.state=ArmState.EXECUTING;arm.consumed_liters=arm.planned_liters;arm.reserved_liters=0
    reservation=db.scalar(select(CrewReservation).where(CrewReservation.pair_id==arm.pair_id,CrewReservation.state==ReservationState.HELD).with_for_update())
    if reservation:reservation.used_minutes+=trial.minutes_per_arm
    pair=require(db,TrialPair,arm.pair_id,True)
    if pair.state==PairState.RESERVED:pair.state=PairState.ACTIVE
    if trial.state==TrialState.APPROVED:trial.state=TrialState.RUNNING
    audit(db,user,f'试验 {trial.code} 派工 {block.code}（{arm.group}），扣减{arm.planned_liters}L');db.commit();return mission

def _refresh_after_arm(db,trial):
    arms=db.scalars(select(TrialArm).where(TrialArm.trial_id==trial.id)).all()
    pairs={p.id:p for p in db.scalars(select(TrialPair).where(TrialPair.trial_id==trial.id)).all()}
    if any(a.state==ArmState.EXECUTING for a in arms):trial.state=TrialState.RUNNING;return
    live=[a for a in arms if pairs[a.pair_id].state!=PairState.EXCLUDED]
    # 一个配对两组均验收后置为 finished
    for pid,p in pairs.items():
        members=[a for a in arms if a.pair_id==pid]
        if p.state in [PairState.ACTIVE,PairState.RESERVED] and members and all(a.state==ArmState.COMPLETED for a in members):
            p.state=PairState.FINISHED
    if not live:
        # 配对全部退出或释放，缺组、证据不足，不出节水结论
        if not any(a.state==ArmState.EXECUTING for a in arms) and trial.state in [TrialState.APPROVED,TrialState.RUNNING]:
            trial.conclusion={'verdict':'inconclusive','reason':'配对均已退出效果比较或缺组，证据不足，不出节水结论','comparable_pairs':0,'holdout_mae_kw':train_reference()[1].get('holdout_mae_kw')}
            trial.state=TrialState.COMPLETED;trial.completed_at=datetime.utcnow()
        return
    if all(a.state==ArmState.COMPLETED for a in live):
        _conclude(db,trial,arms,pairs)

def on_mission_accepted(db,mission):
    arm=db.scalar(select(TrialArm).where(TrialArm.mission_id==mission.id))
    if not arm or arm.state!=ArmState.EXECUTING:return
    survey=db.get(SoilingSurvey,mission.survey_id);block=db.get(ArrayBlock,survey.block_id)
    holdout=(survey.model_evidence or {}).get('holdout_mae_kw')
    arm.state=ArmState.COMPLETED
    arm.evidence={**(arm.evidence or {}),'mission_id':mission.id,'post_kw':mission.post_kw,'post_irradiance':mission.post_irradiance,'normalized_kw':mission.normalized_kw,'verified_gain_kw':mission.verified_gain,'consumed_liters':mission.water_liters,
        'pre_deficit_pct':round(100*(survey.clean_kw-survey.observed_kw)/survey.clean_kw,4) if survey.clean_kw else None,
        'post_residual_pct':round(100*(survey.clean_kw-mission.normalized_kw)/survey.clean_kw,4) if survey.clean_kw else None,
        'recovery_pct':round(100*mission.verified_gain/max(survey.clean_kw-survey.observed_kw,1e-9),4),
        'correction':'以清洁功率预测校正前后观测：清洗前清洁预测clean_kw来自同特征随机森林；清洗后归一化功率=post_kw×原辐照/复测辐照','holdout_mae_kw':holdout}
    trial=db.get(WaterSavingTrial,arm.trial_id)
    _refresh_after_arm(db,trial)

def _conclude(db,trial,arms,pairs):
    # 非劣边际直接采用清洁功率模型的独立留出 MAE（kW），即结论证据中保留的预测误差预算
    model_mae=float(train_reference()[1].get('holdout_mae_kw'))
    by_pair={}
    for a in arms:
        if pairs[a.pair_id].state==PairState.EXCLUDED or a.state!=ArmState.COMPLETED:continue
        by_pair.setdefault(a.pair_id,{})[a.group]=a
    pair_results=[];comparable=0
    for pid,groups in by_pair.items():
        if 'control' not in groups or 'treatment' not in groups:continue
        c,t=groups['control'],groups['treatment'];comparable+=1
        saved=round(c.consumed_liters-t.consumed_liters,3)
        saved_pct=round(100*saved/max(c.consumed_liters,1e-9),3)
        # 清洗后残余积灰功率差（kW）：清洁预测 − 同辐照归一化后功率，越小越干净
        rc=round(c.evidence['predicted_clean_kw']-c.evidence['normalized_kw'],4)
        rt=round(t.evidence['predicted_clean_kw']-t.evidence['normalized_kw'],4)
        delta=round(rt-rc,4)  # >0 表示节水组清洗后残余更多
        noninferior=delta<=model_mae
        pair_results.append({'pair_id':pid,'control_arm':c.id,'treatment_arm':t.id,'control_liters':c.consumed_liters,'treatment_liters':t.consumed_liters,'saved_liters':saved,'saved_pct':saved_pct,'control_residual_kw':rc,'treatment_residual_kw':rt,'residual_delta_kw':delta,'control_recovery_pct':c.evidence['recovery_pct'],'treatment_recovery_pct':t.evidence['recovery_pct'],'noninferior_margin_kw':round(model_mae,4),'noninferior':noninferior})
    total_control=sum(p['control_liters'] for p in pair_results);total_treatment=sum(p['treatment_liters'] for p in pair_results)
    total_saved=round(total_control-total_treatment,3)
    if not comparable:
        conclusion={'verdict':'inconclusive','reason':'缺组或配对已退出比较，没有可对照的同类配对，不出节水结论','comparable_pairs':0,'holdout_mae_kw':model_mae}
    else:
        mean_delta=round(sum(p['residual_delta_kw'] for p in pair_results)/comparable,4)
        ok_pairs=sum(1 for p in pair_results if p['noninferior'])
        # 总体非劣（平均残余差不超过模型误差预算）且至少80%配对各自非劣，才支持节水结论
        aggregate_ok=mean_delta<=model_mae
        pair_ok=ok_pairs/comparable>=0.8
        verdict='water_saving_supported' if aggregate_ok and pair_ok else 'inconclusive'
        conclusion={'verdict':verdict,'reason':'' if verdict=='water_saving_supported' else '节水组清洗后残余功率差超出模型留出误差预算，或证据不足，不出节水结论','comparable_pairs':comparable,'excluded_pairs':sum(1 for p in pairs.values() if p.state==PairState.EXCLUDED),'total_saved_liters':total_saved,'saved_pct':round(100*total_saved/max(total_control,1e-9),3),'mean_residual_delta_kw':mean_delta,'noninferior_margin_kw':round(model_mae,4),'pairs_noninferior':ok_pairs,'holdout_mae_kw':model_mae,'pairs':pair_results}
    trial.conclusion=conclusion;trial.state=TrialState.COMPLETED;trial.completed_at=datetime.utcnow()
    actor=type('Actor',(),{'email':trial.approved_by or 'system'})()
    audit(db,actor,f'试验 {trial.code} 完成：{conclusion["verdict"]}，可比较配对{comparable}个')

def terminate(db,key,body,user):
    trial=require(db,WaterSavingTrial,key,True)
    if trial.state not in [TrialState.APPROVED,TrialState.RUNNING]:raise HTTPException(409,'仅已批准或执行中的试验可以终止')
    arms=db.scalars(select(TrialArm).where(TrialArm.trial_id==trial.id).with_for_update()).all()
    if any(a.state==ArmState.EXECUTING for a in arms):raise HTTPException(409,'存在清洗执行中的分组，请待其复测验收后再终止；已耗水量保留不返还')
    released_water=0;released_minutes=0
    for a in arms:
        if a.state==ArmState.RESERVED:
            released_water+=a.reserved_liters;a.reserved_liters=0;a.state=ArmState.RELEASED
    for r in db.scalars(select(CrewReservation).where(CrewReservation.trial_id==trial.id,CrewReservation.state==ReservationState.HELD).with_for_update()).all():
        free=r.minutes-r.used_minutes
        if free>0:released_minutes+=free
        r.state=ReservationState.RELEASED
    for p in db.scalars(select(TrialPair).where(TrialPair.trial_id==trial.id)).all():
        if p.state in [PairState.RESERVED,PairState.ACTIVE]:p.state=PairState.EXCLUDED;p.exclude_reason='试验中途终止，未执行配对释放'
    trial.state=TrialState.TERMINATED;trial.terminate_reason=body.reason;trial.terminated_by=user.email;trial.terminated_at=datetime.utcnow()
    trial.conclusion={'verdict':'inconclusive','reason':'试验中途终止，不出节水结论','released_unexecuted_liters':round(released_water,3),'released_minutes':released_minutes,'consumed_liters':round(sum(a.consumed_liters for a in arms),3)}
    audit(db,user,f'终止试验 {trial.code}：释放未执行预留{released_water:.1f}L/{released_minutes}分钟，已耗水量保留');db.commit();return trial

def exclude_pair(db,key,pair_key,body,user):
    trial=require(db,WaterSavingTrial,key,True)
    if trial.state not in [TrialState.APPROVED,TrialState.RUNNING]:raise HTTPException(409,'试验未生效或已结束，不能退出配对')
    pair=require(db,TrialPair,pair_key,True)
    if pair.trial_id!=trial.id:raise HTTPException(409,'配对不属于该试验')
    if pair.state==PairState.EXCLUDED:raise HTTPException(409,'该配对已退出效果比较，不能重复操作')
    if pair.state==PairState.FINISHED:raise HTTPException(409,'配对已完成效果比较，不能再退出')
    arms=db.scalars(select(TrialArm).where(TrialArm.pair_id==pair.id).with_for_update()).all()
    released=0
    for a in arms:
        if a.state==ArmState.RESERVED:
            released+=a.reserved_liters;a.reserved_liters=0;a.state=ArmState.RELEASED
    r=db.scalar(select(CrewReservation).where(CrewReservation.pair_id==pair.id,CrewReservation.state==ReservationState.HELD).with_for_update())
    freed_minutes=(r.minutes-r.used_minutes) if r else 0
    if r:r.state=ReservationState.RELEASED
    pair.state=PairState.EXCLUDED;pair.exclude_reason=body.reason;pair.excluded_by=user.email;pair.excluded_at=datetime.utcnow()
    audit(db,user,f'试验 {trial.code} 配对{pair.pair_index}退出比较（{body.reason}），释放未执行预留{released:.1f}L/{freed_minutes}分钟，放行紧急运维')
    _refresh_after_arm(db,trial);db.commit();return pair
