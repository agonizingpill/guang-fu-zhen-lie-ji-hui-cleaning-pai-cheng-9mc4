import {field,sync} from '../store.js';import {request,identity} from '../api.js';import {lead} from '../components/field.js';import {safe,fixed,dataFrom,message} from '../utils.js';import {TRIAL_STATES,PAIR_STATES,ARM_STATES,TRIAL_GROUPS} from '../constants.js';
const tb=id=>field.arrays.find(a=>a.id===id);
const tbadge=v=>`<span class="badge ${safe(v)}">${safe(TRIAL_STATES[v]||v)}</span>`;
const pbadge=v=>`<span class="badge ${safe(v)}">${safe(PAIR_STATES[v]||v)}</span>`;
const abadge=v=>`<span class="badge ${safe(v)}">${safe(ARM_STATES[v]||v)}</span>`;

export function render(){
  const admin=identity().role==='admin',edit=identity().role!=='viewer';
  const t=field.trials.find(x=>x.id==field.selectedTrial)||field.trials[0];
  const eligible=field.arrays.filter(b=>b.cleaning_state!=='washing'&&field.surveys.some(s=>s.block_id===b.id&&s.state==='assessed'&&!field.missions.some(m=>m.survey_id===s.id)));
  return lead('RANDOMIZED WATER TRIAL','用同类阵列随机配对，回答少用水是否牺牲清洁收益','固定水量系数无法证明节水代价。试验把同容量/坡度/面积/积灰的阵列随机分为对照（标准水量）与试验（节水）组，以清洁功率预测校正前后观测条件，并保留模型误差与随机分组依据。')
  +`<div class="mission-layout"><aside class="mission-list">${field.trials.length?field.trials.map(x=>`<button data-trial="${x.id}" class="${x.id===t?.id?'selected':''}"><span class="code">${safe(x.code)}</span><h3>${safe(x.title)}</h3>${tbadge(x.state)}</button>`).join(''):'<div class="empty">尚无节水试验<br>选择已评估的同类阵列发起。</div>'}</aside>
  <section class="surface">
  <h2>发起随机节水试验</h2>
  <form id="trial-form">
   <label>试验名称<input name="title" required minlength="3" maxlength="160" placeholder="南坡节水20%随机试验"></label>
   <label>同类阵列（须偶数，按容量/坡度/面积/积灰自动配对）<select name="block_ids" multiple size="4" required>${eligible.map(b=>`<option value="${b.id}">${safe(b.code)} · ${safe(b.name)} · 余水${fixed(b.water_liters,0)}L</option>`).join('')}</select></label>
   <div class="cols two"><label>节水比例 %<input name="reduction_pct" type="number" min="1" max="99" step="1" value="20" required></label><label>随机种子<input name="seed" type="number" min="0" value="42" required></label></div>
   <div class="cols two"><label>作业日期<input name="work_date" type="date" value="${new Date().toISOString().slice(0,10)}" required></label><label>承担班组<select name="crew_id">${field.crews.filter(c=>c.active).map(c=>`<option value="${c.id}">${safe(c.code)} · ${c.max_daily_minutes}分钟/天</option>`).join('')}</select></label></div>
   <label>每组工时 / 分钟<input name="minutes_per_arm" type="number" min="1" max="1440" value="120" required></label>
   <button class="primary" ${edit?'':'disabled'}>生成配对并提交待批准</button>
  </form>
  <div class="rule">批准时整组预留水额与班组工时：任一资源不足整组不生效；普通派工与许可签发均不得抢占。允许分批执行、中途终止（只释放未执行预留，已耗水量保留，重试不重复返还）。</div>
  ${t?detail(t,admin):'<div class="empty">选择左侧试验查看配对、资源去向与节水结论。</div>'}
  </section></div>`;
}

function detail(t,admin){
  const d=field.trialDetails[t.id];if(!d)return '';
  const arms=pid=>d.arms.filter(a=>a.pair_id===pid);
  const con=t.conclusion;
  return `<div class="sectionline"><h2>${safe(t.code)} ${tbadge(t.state)}</h2><span class="note">节水 ${fixed(t.reduction_pct,0)}% · 种子 ${t.seed}</span></div>
  <div class="actionbar">
   <button class="primary" data-approve="${t.id}" ${admin&&t.state==='pending'?'':'disabled'}>主管整组批准（预留水额+工时）</button>
   <button data-terminate="${t.id}" ${admin&&['approved','running'].includes(t.state)?'':'disabled'}>中途终止（仅释放未执行预留）</button>
  </div>
  <h3>配对依据与随机分组</h3>
  <p class="note">${safe(t.pairing_basis.rule)}；相似度阈值 distance≤0.35。${t.pairing_basis.unpaired?.length?'未配对：'+safe(t.pairing_basis.unpaired.join('、')):'全部阵列完成配对'}。</p>
  ${d.pairs.map(p=>`<article class="surface followup"><div class="sectionline"><h3>配对 ${p.pair_index} ${pbadge(p.state)}</h3><span class="note">相似度 ${fixed(p.similarity.distance,3)}（容量${fixed(p.similarity.parts.capacity_pct,3)} / 坡度${fixed(p.similarity.parts.slope_pct,3)} / 面积${fixed(p.similarity.parts.area_pct,3)} / 积灰${fixed(p.similarity.parts.dust_pct,3)}）</span></div>
   ${arms(p.id).map(a=>armCard(a,t)).join('')}
   ${p.exclude_reason?`<p class="note">退出原因：${safe(p.exclude_reason)}（${safe(p.excluded_by||'')}）</p>`:''}
   <div class="actionbar"><button data-exclude="${p.id}" data-trial="${t.id}" ${admin&&['reserved','active'].includes(p.state)?'':'disabled'}>紧急运维：该配对退出比较并放行</button></div>
  </article>`).join('')}
  <h3>资源去向核对</h3>
  <div class="tablewrap"><table><thead><tr><th>分组</th><th>阵列</th><th>标准水量L</th><th>计划L</th><th>预留L</th><th>实耗L</th><th>状态</th></tr></thead><tbody>
  ${d.arms.map(a=>`<tr><td>${safe(TRIAL_GROUPS[a.group])}</td><td>${safe(tb(a.block_id)?.code)}</td><td>${fixed(a.baseline_liters,1)}</td><td>${fixed(a.planned_liters,1)}</td><td>${fixed(a.reserved_liters,1)}</td><td>${fixed(a.consumed_liters,1)}</td><td>${abadge(a.state)}</td></tr>`).join('')}
  </tbody></table></div>
  <p class="note">班组工时预留：${d.crew_reservations.map(r=>`${fixed(r.minutes,0)}分钟（已用${fixed(r.used_minutes,0)}，${r.state==='held'?'生效中':'已释放/消费'}）`).join('；')}</p>
  ${conclusion(con)}
  <p class="note">创建 ${safe(t.created_by)} · 批准 ${safe(t.approved_by||'—')}${t.terminate_reason?'<br>终止原因：'+safe(t.terminate_reason):''}</p>`;
}

function armCard(a,t){
  const e=a.evidence||{};
  const canExec=admin&&['approved','running'].includes(t.state)&&a.state==='reserved';
  return `<div class="blockrow"><div><span class="code">${safe(TRIAL_GROUPS[a.group])} · ${safe(tb(a.block_id)?.code)} ${abadge(a.state)}</span>
   <p class="note">巡测 ${safe(e.survey_code)} · 辐照${fixed(e.irradiance,0)}W/m² · 实测${fixed(e.observed_kw,1)}kW / 清洁预测${fixed(e.predicted_clean_kw,2)}kW（留出MAE ${fixed(e.model_holdout_mae_kw,3)}kW）<br>
   ${e.normalized_kw?`洗后归一化${fixed(e.normalized_kw,2)}kW · 增益${fixed(e.verified_gain_kw,2)}kW · 清洗前欠损${fixed(e.pre_deficit_pct,2)}% / 洗后残余${fixed(e.post_residual_pct,2)}%`:'待执行，校正口径：洗后功率×原辐照÷复测辐照'}</p></div>
   <button class="warm" data-exec="${a.id}" data-trial="${t.id}" ${canExec?'':'disabled'}>执行该分组</button></div>`;
}

function conclusion(con){
  if(!con)return '<div class="empty">试验进行中，完成后给出节水结论。</div>';
  const map={water_saving_supported:'支持节水结论：节水组在模型误差预算内非劣',inconclusive:'证据不足，不出节水结论'};
  const rows=con.pairs||[];
  return `<div class="rule"><strong>${safe(map[con.verdict]||con.verdict)}</strong><br>${safe(con.reason||'')}<br>
   可比较配对 ${con.comparable_pairs} 个 · 非劣边际（模型留出MAE）${fixed(con.noninferior_margin_kw,3)}kW · 累计节水 ${fixed(con.total_saved_liters,1)}L（${fixed(con.saved_pct,2)}%）
   ${con.released_unexecuted_liters!=null?`<br>终止释放未执行水额 ${fixed(con.released_unexecuted_liters,1)}L / 工时${con.released_minutes}分钟，已耗 ${fixed(con.consumed_liters,1)}L 保留`:''}</div>
   ${rows.length?`<div class="tablewrap"><table><thead><tr><th>配对</th><th>对照用水L</th><th>试验用水L</th><th>节水L</th><th>残余差kW</th><th>非劣</th></tr></thead><tbody>
   ${rows.map(p=>`<tr><td>${p.pair_id}</td><td>${fixed(p.control_liters,1)}</td><td>${fixed(p.treatment_liters,1)}</td><td>${fixed(p.saved_liters,1)}</td><td>${fixed(p.residual_delta_kw,3)}</td><td>${p.noninferior?'是':'否'}</td></tr>`).join('')}
   </tbody></table></div>`:''}`;
}

export function bind(rerender){
  async function act(path,body,method='POST'){try{await request(path,method,body);await sync();rerender();message('操作已记录');}catch(e){message(e.message);}}
  const form=document.querySelector('#trial-form');
  if(form)form.onsubmit=e=>{e.preventDefault();const b=dataFrom(e.target);b.block_ids=[...e.target.elements.block_ids.selectedOptions].map(o=>Number(o.value));for(const k of ['reduction_pct','seed','crew_id','minutes_per_arm'])b[k]=Number(b[k]);act('/trials',b);};
  document.querySelectorAll('aside.mission-list [data-trial]').forEach(btn=>btn.onclick=()=>{field.selectedTrial=Number(btn.dataset.trial);rerender();});
  document.querySelectorAll('[data-approve]').forEach(b=>b.onclick=()=>act('/trials/'+b.dataset.approve+'/approve'));
  document.querySelectorAll('[data-terminate]').forEach(b=>b.onclick=()=>{const reason=prompt('请填写中途终止原因（至少5字）');if(reason&&reason.trim().length>=5)act('/trials/'+b.dataset.terminate+'/terminate',{reason:reason.trim()});else if(reason)message('终止原因至少5字');});
  document.querySelectorAll('[data-exclude]').forEach(b=>b.onclick=()=>{const reason=prompt('请填写退出比较/紧急运维原因（至少5字）');if(reason&&reason.trim().length>=5)act(`/trials/${b.dataset.trial}/pairs/${b.dataset.exclude}/exclude`,{reason:reason.trim()});else if(reason)message('原因至少5字');});
  document.querySelectorAll('[data-exec]').forEach(b=>b.onclick=()=>act(`/trials/${b.dataset.trial}/arms/${b.dataset.exec}/execute`));
}
