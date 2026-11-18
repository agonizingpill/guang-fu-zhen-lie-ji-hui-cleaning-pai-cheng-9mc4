import {request} from './api.js';
export const field={arrays:[],surveys:[],missions:[],deliveries:[],followups:[],crews:[],permits:[],wastewater:[],settlements:[],trials:[],trialDetails:{},selectedBlock:null,selectedSurvey:null,selectedMission:null,selectedTrial:null};
export async function sync(){[field.arrays,field.surveys,field.missions,field.deliveries,field.followups,field.crews,field.permits,field.wastewater,field.settlements,field.trials]=await Promise.all([request('/arrays'),request('/surveys'),request('/missions'),request('/deliveries'),request('/followups'),request('/crews'),request('/permits'),request('/wastewater'),request('/settlements'),request('/trials')]);
  field.trialDetails={};
  await Promise.all(field.trials.map(async t=>{field.trialDetails[t.id]=await request('/trials/'+t.id+'/detail');}));}
