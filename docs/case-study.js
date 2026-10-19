'use strict';
const repo = 'https://github.com/abh2050/ontology-ops/blob/main/';
const setText = (id,value) => { document.getElementById(id).textContent = value; };
const views = {
  queue: {title:'Start with the exceptions that need attention.', kicker:'Find relevant work', window:'Late delivery queue', copy:'Choose the batch and historical date, then browse the authorized queue of late, undelivered orders. The sort is a heuristic: days overdue, line value and order ID.', points:['Late-order queue with dataset-local context','Consistent sorting and pagination','A direct path into the investigation view'], alt:'Actual authored-fixture exception queue showing overdue orders, source context and investigate controls.'},
  graph: {title:'See the issue in context.', kicker:'Understand the relationships', window:'Connected investigation', copy:'Open an order and explore the sellers and related orders connected to it. The detail panel explains each business relationship and shows exact seller exposure.', points:['Connected order and seller graph','Exact totals alongside the bounded graph','Evidence tied to a selected historical date'], alt:'Actual authored investigation UI with a connected order and seller graph, a relationship detail drawer and exact scoped totals.'},
  review: {title:'Give the reviewer an evidence-backed case.', kicker:'Make the decision reviewable', window:'Internal action review', copy:'Inspect the proposal, its supporting evidence and review state. In the backend, a different reviewer with the right scope approves before the application creates the internal case.', points:['A proposal with explicit evidence references','Revision-aware review and case state','A durable record of the approved action'], alt:'Actual static action-review UI after a simulated approval of an authored internal investigation case.'}
};
function chooseView(name,focus=false) {
  const data=views[name];
  document.querySelectorAll('.product-tab').forEach(button=>{const active=button.dataset.view===name;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
  document.getElementById('product-panel').setAttribute('aria-labelledby','product-tab-'+name);
  const image=document.getElementById('product-image');image.src='assets/case-study/'+name+'.webp';image.alt=data.alt;
  document.getElementById('product-full-image').href=image.src;
  setText('product-title',data.title);setText('product-kicker',data.kicker);setText('product-copy',data.copy);setText('product-window-title',data.window);
  document.getElementById('product-points').replaceChildren(...data.points.map(text=>{const item=document.createElement('li');item.textContent=text;return item;}));
  if(focus)document.getElementById('product-tab-'+name).focus();
}
function tabKeys(event,index,length,choose) {
  let next=index;
  if(event.key==='ArrowDown'||event.key==='ArrowRight')next=(index+1)%length;
  else if(event.key==='ArrowUp'||event.key==='ArrowLeft')next=(index+length-1)%length;
  else if(event.key==='Home')next=0;
  else if(event.key==='End')next=length-1;
  else return;
  event.preventDefault();choose(next);
}
const viewNames=['queue','graph','review'];
document.querySelectorAll('.product-tab').forEach((button,index)=>{button.addEventListener('click',()=>chooseView(button.dataset.view));button.addEventListener('keydown',event=>tabKeys(event,index,viewNames.length,next=>chooseView(viewNames[next],true)));});
const stages=[
  {kind:'Data engineering / deterministic',title:'Start with a traceable source.',copy:'Import all five Olist files, validate their headers and preserve source provenance. Invalid rows are quarantined with reason codes. Historical timestamps and integer-centavo money values keep the investigation reproducible.',input:'Complete orders, order items, customers, sellers and products files.',output:'A validated, immutable batch with a documented quarantine.',source:'backend/ops/data/importer.py'},
  {kind:'Application queries / deterministic',title:'Give each operator a relevant queue.',copy:'The selected as_of reconstructs the facts known at that time. Late open means 1–30 days past the estimated delivery date with no delivery known. Explicit seller grants define the operator’s visible orders before totals or graphs are built.',input:'Actor permissions, batch and historical as_of.',output:'Authorized delivery exceptions and consistent, scoped totals.',source:'backend/ops/queries/scope.py'},
  {kind:'Ontology tools / deterministic',title:'Connect the records around the question.',copy:'Typed relationships connect an order to its customer, lines, sellers and products. Purpose-built tools return related late orders and exact seller-level exposure. A seller relationship describes fulfillment, not the cause of delay.',input:'A selected order or seller inside the actor’s scope.',output:'Linked business evidence, distinct counts and exact money values.',source:'backend/ops/queries/tools.py'},
  {kind:'Bedrock / planner and analyst',title:'Prepare an evidence-linked recommendation.',copy:'The planner selects from allowlisted tools; the worker executes them and checkpoints the results. The analyst interprets that evidence and returns structured findings. Live policy bounds the job to two model calls and at most three tools.',input:'The question, ontology contract and authorized tool evidence.',output:'A typed plan and analyst response with evidence references.',source:'backend/ops/jobs/consumer.py'},
  {kind:'Evidence validation / deterministic',title:'Check the proposal against its evidence.',copy:'Strict Pydantic contracts and deterministic checks verify identifiers, references, arithmetic, action eligibility and synthetic citations. Unsupported causal language receives a needs_review state; invalid JSON ends the job without a repair loop.',input:'The analyst response and its authorized evidence bundle.',output:'Validated findings, an eligible proposal or an explicit review/failure state.',source:'backend/ops/agents/validator.py'},
  {kind:'Independent review / transaction',title:'Record the approved internal case.',copy:'A different reviewer must hold scope over every target. Execution rechecks revision, current evidence, ontology version and equivalent-case uniqueness. The case and audit event are written transactionally.',input:'Pending proposal, scoped reviewer and expected revision.',output:'One internal investigation case with a durable approval record.',source:'backend/ops/commands/proposals.py'}
];
function chooseStage(index,focus=false) {
  const data=stages[index];
  document.querySelectorAll('.stage').forEach((button,i)=>{button.setAttribute('aria-selected',String(i===index));button.tabIndex=i===index?0:-1;});
  document.getElementById('stage-panel').setAttribute('aria-labelledby','stage-'+index);
  ['kind','title','copy','input','output'].forEach(key=>setText('stage-'+key,data[key]));
  document.getElementById('stage-source').href=repo+data.source;
  if(focus)document.getElementById('stage-'+index).focus();
}
document.querySelectorAll('.stage').forEach((button,index)=>{button.addEventListener('click',()=>chooseStage(index));button.addEventListener('keydown',event=>tabKeys(event,index,stages.length,next=>chooseStage(next,true)));});
const nodes={
  edge:{kind:'Delivery / web entry',title:'CloudFront + ALB',copy:'CloudFront delivers the browser entry point and forwards uncached requests through the Application Load Balancer to the API task.',why:'Serve the UI and API from one browser origin.',detail:'Browser TLS terminates at CloudFront. The historical demo used HTTP on the origin leg; that tradeoff is disclosed in the deployment details.',source:'infra/stack.py#L123'},
  api:{kind:'Application / access control',title:'FastAPI / Fargate',copy:'FastAPI serves the React workspace and resolves the operator’s seller permissions before building queries, totals and graphs. It also owns the independent-review execution path.',why:'Keep the workspace responsive and apply one consistent authorization contract.',detail:'Cognito establishes identity. Current database grants establish scope. The API’s runtime role is separate from the model-calling worker.',source:'backend/ops/queries/scope.py'},
  database:{kind:'Persistence / source of truth',title:'PostgreSQL 16',copy:'RDS holds commerce batches, seller grants, jobs, tool checkpoints, proposals, cases and audit events. The database is private and encrypted, and application connections require TLS.',why:'Keep business facts and workflow state under transactional constraints.',detail:'Case uniqueness, evidence freshness and review revisions are checked at execution. The historical instance was single-AZ.',source:'infra/stack.py#L99'},
  queue:{kind:'Orchestration / durable jobs',title:'SQS + DLQ',copy:'The worker relays committed PostgreSQL outbox rows to SQS, then consumes jobs. Messages that exhaust the receive limit move to the dead-letter queue.',why:'Decouple model work from interactive requests and provide an inspectable recovery path.',detail:'180-second visibility timeout; four-day source retention; fourteen-day DLQ retention; five receives before dead-lettering.',source:'infra/stack.py#L115'},
  worker:{kind:'Orchestration / execution state',title:'Fargate worker',copy:'The worker owns outbox relay, queue consumption, evidence tools, checkpoints, model calls and deterministic validation. It writes the result back to PostgreSQL for the API to read.',why:'Run bounded AI work with durable progress alongside the interactive workspace.',detail:'Eligible checkpoints support redelivery recovery. Current scope is checked before resuming work. Approval remains in the application review path.',source:'backend/ops/jobs/consumer.py#L262'},
  model:{kind:'Inference / structured assistance',title:'Amazon Bedrock',copy:'boto3 Converse runs the planner and analyst stages with configured Nova models from us-east-2. Each response is checked against a strict Pydantic contract.',why:'Test the value of typed business evidence in investigation recommendations.',detail:'The evaluation compares two Nova generations. Model calls, token budgets and tools are bounded; model substitution and automatic JSON repair are not used.',source:'configs/policy.yaml'}
};
document.querySelectorAll('.arch-node').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('.arch-node').forEach(other=>other.setAttribute('aria-pressed',String(other===button)));const data=nodes[button.dataset.node];['kind','title','copy','why'].forEach(key=>setText('arch-'+key,data[key]));setText('arch-detail-copy',data.detail);document.getElementById('arch-source').href=repo+data.source;}));
const gates={
  valid:{steps:['Authorized context','Structured model response','Evidence validation','Independent review'],blocked:-1,state:'READY FOR INDEPENDENT REVIEW',copy:'A validated proposal can enter review. The application creates the internal case after a different, scoped reviewer approves it and execution checks pass.'},
  cause:{steps:['Authorized context','Structured model response','Causal language flagged','Reviewer needs an evidence-supported proposal'],blocked:2,state:'NEEDS_REVIEW',copy:'A relationship does not establish a delay’s cause. The validator flags unsupported causal language, and the proposal remains in a non-approvable review state.'},
  invented:{steps:['Authorized context','Structured model response','Identifier checked against evidence','Executable selection requires support'],blocked:2,state:'EVIDENCE MEMBERSHIP CHECK',copy:'Every selected identifier must be supported by the supplied authorized evidence. Unsupported identifiers prevent an executable proposal.'},
  timeout:{steps:['Job admitted','Model call started','Response outcome unknown','Record preserved on hold'],blocked:2,state:'UNKNOWN OUTCOME / HOLD',copy:'A timeout leaves the paid outcome uncertain. The job is held for inspection rather than repeating a potentially paid call automatically.'},
  self:{steps:['Authorized context','Validated proposal','Reviewer identity checked','Different reviewer required'],blocked:2,state:'INDEPENDENT REVIEW CHECK',copy:'Approval requires a reviewer distinct from the proposer, with independent scope over every target. A self-approval attempt is refused.'}
};
document.getElementById('gate-scenario').addEventListener('change',event=>{const data=gates[event.target.value];document.getElementById('gate-steps').replaceChildren(...data.steps.map((text,index)=>{const item=document.createElement('li');item.textContent=text;item.className=data.blocked<0||index<data.blocked?'passed':index===data.blocked?'blocked':'';return item;}));setText('gate-state',data.state);setText('gate-copy',data.copy);});
const cells={nova2:{real:{flat:55.8,candidate:58.1,recall:'.114'},scenario:{flat:41.7,candidate:41.7,recall:'.066'}},nova1:{real:{flat:27.9,candidate:32.6,recall:'.530'},scenario:{flat:25.0,candidate:46.7,recall:'.491'}}};
function compare() {
  const data=cells[document.getElementById('model-select').value][document.getElementById('mode-select').value];
  setText('flat-value',data.flat.toFixed(1)+'%');setText('candidate-value',data.candidate.toFixed(1)+'%');
  document.getElementById('flat-bar').style.width=data.flat+'%';document.getElementById('candidate-bar').style.width=data.candidate+'%';
  setText('chart-summary','Typed evidence: +'+(data.candidate-data.flat).toFixed(1)+' percentage points vs flat evidence. Candidate relationship recall: 0'+data.recall+'.');
}
['model-select','mode-select'].forEach(id=>document.getElementById(id).addEventListener('change',compare));
const menu=document.querySelector('.menu'),links=document.getElementById('nav-links');
function closeMenu() { menu.setAttribute('aria-expanded','false');links.classList.remove('open');menu.textContent='Menu +'; }
menu.addEventListener('click',()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));links.classList.toggle('open',open);menu.textContent=open?'Close −':'Menu +';});
links.querySelectorAll('a').forEach(link=>link.addEventListener('click',closeMenu));
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&menu.getAttribute('aria-expanded')==='true'){closeMenu();menu.focus();}});
const sectionLinks=[...document.querySelectorAll('.nav-links a[href^="#"]')];
let scheduled=false;
function updateProgress() {
  const total=document.documentElement.scrollHeight-innerHeight;
  document.querySelector('.progress').style.width=(total>0?scrollY/total*100:0)+'%';
  const current=[...sectionLinks].reverse().find(link=>document.querySelector(link.hash).getBoundingClientRect().top<innerHeight*.38);
  sectionLinks.forEach(link=>{if(link===current)link.setAttribute('aria-current','location');else link.removeAttribute('aria-current');});scheduled=false;
}
addEventListener('scroll',()=>{if(!scheduled){scheduled=true;requestAnimationFrame(updateProgress);}},{passive:true});
addEventListener('resize',updateProgress);document.querySelectorAll('details').forEach(detail=>detail.addEventListener('toggle',updateProgress));updateProgress();
