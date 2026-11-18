export const ROLES={admin:'运维主管',planner:'清洗计划员',viewer:'电站观察员'};
export const SURVEY_STATES={recorded:'待评估',evaluating:'评估中',assessed:'已评估',scheduled:'清洗中',retested:'已复测',closed:'已闭环',blocked:'需重试',stale:'清洗前旧读数'};
export const MISSION_STATES={draft:'待派工',dispatched:'执行中',retested:'待验收',accepted:'已验收',superseded:'旧计划已失效'};
export const TRIAL_STATES={pending:'待批准',approved:'已批准待执行',running:'执行中',terminated:'已终止',completed:'已完成'};
export const PAIR_STATES={planned:'待批准',reserved:'已预留',active:'执行中',excluded:'已退出比较',finished:'已完成比较'};
export const ARM_STATES={planned:'待批准',reserved:'已预留',executing:'清洗中',completed:'已完成',released:'预留已释放'};
export const TRIAL_GROUPS={control:'对照·标准水量',treatment:'试验·节水'};
