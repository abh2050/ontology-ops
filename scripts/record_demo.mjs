/** Genuine live-browser recording. Credentials/tokens stay in process memory.
 * The output manifest contains public evidence references, never storage state.
 * Login pages are verified before recording and are excluded from the footage.
 */
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const out = JSON.parse(await readFile(path.join(root, "cdk.out/outputs.json"), "utf8")).OntologyOpsStack;
const base = out.OutAppUrl;
let stage = "initialization";
let browser;
async function authenticate(user, password) {
  stage = `${user} Cognito sign-in`;
  const context = await browser.newContext({viewport: {width: 1600, height: 1000}});
  const page = await context.newPage();
  await page.goto(base, {waitUntil: "domcontentloaded"});
  stage = `${user} app sign-in button`;
  await page.getByRole("button", {name: "Sign in with Cognito"}).click();
  stage = `${user} hosted sign-in form`;
  await page.waitForLoadState("domcontentloaded");
  await page.locator('input[name="username"]:visible').fill(user);
  await page.locator('input[name="password"]:visible').fill(password);
  stage = `${user} hosted sign-in submit`;
  await page.locator('input[name="signInSubmitButton"]:visible, button[type="submit"]:visible').first().click();
  stage = `${user} PKCE callback and authorized queue`;
  await page.getByRole("heading", {name: "Late delivery queue"}).waitFor({timeout: 60000});
  const token = await page.evaluate(() => sessionStorage.getItem("ops_access_token"));
  if (!token) throw new Error("No access token after PKCE callback");
  const response = await page.request.get(`${base}/api/me`, {headers: {Authorization: `Bearer ${token}`}});
  const actor = await response.json();
  if (!response.ok() || !actor.provisioned) throw new Error("Provisioned identity check failed");
  console.log(`Verified real Cognito PKCE: ${user}, role ${actor.role}, ${actor.granted_sellers} seller grants`);
  await context.close();
  return {token, role: actor.role};
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function capture(identities) {
  const stamp = new Date().toISOString().replaceAll(/[:.]/g, "-");
  const directory = path.join(root, ".local/demo", `capture-${stamp}`);
  await mkdir(directory, {recursive: true});
  const manifest = {base_url: base, captured_at: new Date().toISOString(), source: "Genuine live AWS browser capture; separate authenticated roles; login excluded", clips: [], observations: {}};
  let chosenOrder, proposalId;
  async function api(user, route, body) {
    const response = await fetch(`${base}${route}`, {method: body ? "POST" : "GET", headers: {Authorization: `Bearer ${identities[user].token}`, "Content-Type": "application/json"}, ...(body ? {body: JSON.stringify(body)} : {})});
    return {status: response.status, body: await response.json()};
  }
  async function clip(name, user, seconds, action) {
    stage = `capture ${name}`;
    const ctx = await browser.newContext({viewport: {width: 1600, height: 900}, recordVideo: {dir: directory, size: {width: 1600, height: 900}}});
    await ctx.addInitScript((token) => sessionStorage.setItem("ops_access_token", token), identities[user].token);
    const page = await ctx.newPage();
    const started = Date.now();
    await page.goto(base, {waitUntil: "domcontentloaded"});
    await page.getByRole("heading", {name: "Late delivery queue"}).waitFor();
    // Video-only privacy redaction: Cognito subjects never appear in footage.
    await page.addStyleTag({content: ".review-grid dl > div:nth-child(2) dd {filter:blur(12px)} .review-grid select {max-width:100%}"});
    await action(page);
    await page.screenshot({path: path.join(directory, `${name}.png`)});
    await wait(Math.max(0, seconds * 1000 - (Date.now() - started)));
    const video = page.video();
    await ctx.close();
    const file = path.join(directory, `${name}.webm`);
    await video.saveAs(file);
    manifest.clips.push({name, user, path: file, wall_seconds: (Date.now() - started) / 1000});
    console.log(`Captured ${name}: ${manifest.clips.at(-1).wall_seconds.toFixed(1)} seconds of real browser footage`);
    await writeFile(path.join(directory, "manifest.json"), JSON.stringify(manifest, null, 2));
  }
  async function openOrder(page) {
    await page.getByRole("button", {name: `Investigate ${chosenOrder}`, exact: true}).click();
    await page.getByRole("heading", {name: /Evidence around order/}).waitFor();
    await page.locator(".cy canvas").first().waitFor();
  }
  async function clickSeller(page) {
    const position = await page.locator(".cy").evaluate((host) => {
      const cy = host._cyreg?.cy;
      const seller = cy?.nodes().filter((n) => n.data("type") === "Seller").first();
      return seller?.renderedPosition();
    });
    if (position) await page.locator(".cy").click({position});
  }
  const queue = (await api("operator_a", "/api/queue?limit=25")).body;
  const cases = (await api("operator_a", "/api/cases")).body.items;
  const cased = new Set(cases.flatMap((c) => c.payload.selected_order_ids || []));
  for (const item of queue.items.filter((item) => !cased.has(item.order_id))) {
    const graph = (await api("operator_a", `/api/graph?root_type=Order&root_id=${item.order_id}`)).body;
    if (graph.totals?.related_late_open_orders >= 2) {chosenOrder = item.order_id;break;}
  }
  if (!chosenOrder) throw new Error("No uncased authorized order on the first queue page");
  manifest.observations.queue_orders = queue.aggregates.late_open_orders;

  await clip("01-queue", "operator_a", 25, async (page) => { await page.mouse.move(1100, 410); });
  await clip("02-relationships", "operator_a", 45, async (page) => {
    await openOrder(page); await wait(2000); await clickSeller(page); await wait(14000);
    await page.getByRole("button", {name: "order_line", exact: true}).first().click();
    await page.locator(".meaning").scrollIntoViewIfNeeded();
  });
  await clip("03-context", "operator_a", 35, async (page) => {
    await openOrder(page); await page.getByLabel("Scenario").selectOption("base-v1");
    await page.getByRole("button", {name: "Apply context"}).click();
    await page.getByText("Synthetic scenario", {exact: true}).first().waitFor();
    await wait(2000); await clickSeller(page); await wait(10000);
    await page.locator(".totals").scrollIntoViewIfNeeded();
  });
  let observedJob;
  await clip("04-proposal", "operator_a", 22, async (page) => {
    await openOrder(page);
    await page.getByLabel("Scenario").selectOption("base-v1");
    await page.getByRole("button", {name: "Apply context"}).click();
    await page.getByText("Synthetic scenario", {exact: true}).first().waitFor();
    const response = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/jobs" && r.request().method() === "POST");
    await page.getByRole("button", {name: "Generate proposal evidence"}).click();
    const submitted = await (await response).json();
    await writeFile(path.join(directory,"continuation.json"),JSON.stringify({job_id:submitted.job_id,target_id:chosenOrder}));
    const deadline = Date.now() + 65000;
    do {
      observedJob = (await api("operator_a", `/api/jobs/${submitted.job_id}`)).body;
      if (!["queued", "running", "validating"].includes(observedJob.state)) break;
      await wait(2000);
    } while (Date.now() < deadline);
    manifest.observations.job_state = observedJob.state;
    manifest.observations.proposal_validation = observedJob.result?.validation?.proposal_state;
    if (observedJob.state !== "ready" || observedJob.result?.validation?.proposal_state !== "pending") {
      await writeFile(path.join(directory, "manifest.json"), JSON.stringify(manifest, null, 2));
      throw new Error("Live output is not approvable; preserve the observed failure");
    }
    const proposed = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith("/proposal"));
    await page.getByRole("button", {name: "Save internal proposal for review"}).click();
    proposalId = (await (await proposed).json()).proposal_id;
    await page.getByRole("navigation").getByRole("button", {name: /Action review/}).click();
    await page.getByLabel("Proposal", {exact: true}).selectOption(proposalId);
    await page.getByText("pending", {exact: true}).waitFor();
  });
  await clip("05-independent-approval", "reviewer", 13, async (page) => {
    await page.getByRole("navigation").getByRole("button", {name: /Action review/}).click();
    await page.getByLabel("Proposal", {exact: true}).selectOption(proposalId);
    await page.getByRole("textbox", {name: "Review note"}).fill("Demo: independently reviewed authorized evidence; cause remains unknown.");
    await page.getByRole("button", {name: "Approve internal case"}).click();
    await page.getByText("executed", {exact: true}).waitFor();
    const current = (await api("reviewer", `/api/proposals/${proposalId}`)).body;
    const duplicate = await api("reviewer", `/api/proposals/${proposalId}/decision`, {decision: "approve", expected_revision: current.revision, reason: "Duplicate execution check"});
    const actualCases = (await api("reviewer", "/api/cases")).body.items.filter((c) => c.proposal_id === proposalId);
    manifest.observations.approval_state = current.state;
    manifest.observations.repeat_approval_status = duplicate.status;
    manifest.observations.cases_created = actualCases.length;
    if (actualCases.length !== 1 || duplicate.status !== 409) throw new Error("Approval invariant failed");
  });
  await clip("06-ungranted-viewer", "viewer", 15, async (page) => {
    await page.getByText("No late open orders are visible within your granted scope.").waitFor();
    manifest.observations.viewer_empty = true;
  });
  await clip("08-measured-evidence", "operator_a", 15, async (page) => {
    await page.getByRole("navigation").getByRole("button", {name: /Evidence/}).click();
    await page.getByRole("heading", {name: "Performance & decision"}).waitFor();
    await page.evaluate(() => window.scrollTo(0, 0));
  });
  await clip("10-recommendation", "operator_a", 10, async (page) => {
    await page.getByRole("navigation").getByRole("button", {name: /Evidence/}).click();
    await page.getByRole("heading", {name: "Ship the deterministic workspace"}).waitFor();
  });
  console.log(`Capture manifest: ${path.relative(root, path.join(directory, "manifest.json"))}`);
}

async function captureDrill(identities) {
  const resumeAt=process.argv.indexOf("--resume-drill");
  const resumeDirectory=resumeAt>=0?path.resolve(process.argv[resumeAt+1]):null;
  const continuation=resumeDirectory?JSON.parse(await readFile(path.join(resumeDirectory,"continuation.json"),"utf8")):null;
  const prior=resumeDirectory?JSON.parse(await readFile(path.join(resumeDirectory,"telemetry.json"),"utf8")).samples:[];
  const directory = path.join(root, ".local/demo", `drill-${new Date().toISOString().replaceAll(/[:.]/g, "-")}`);
  await mkdir(directory, {recursive: true});
  stage = "labelled crash-before-ack capture";
  const ctx = await browser.newContext({viewport: {width:1600,height:900},recordVideo:{dir:directory,size:{width:1600,height:900}}});
  await ctx.addInitScript((token)=>sessionStorage.setItem("ops_access_token",token),identities.operator_a.token);
  const page = await ctx.newPage();
  const api = async (user, route, body) => {
    const r = await fetch(base + route,{method:body?"POST":"GET",headers:{Authorization:`Bearer ${identities[user].token}`,"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});
    return {status:r.status,body:await r.json()};
  };
  const q=(await api("operator_a","/api/queue?limit=25")).body;
  const existing=(await api("operator_a","/api/cases")).body.items;
  const cased=new Set(existing.flatMap((c)=>c.payload.selected_order_ids||[]));
  const oid=continuation?.target_id||q.items.find((o)=>!cased.has(o.order_id))?.order_id;
  if(!oid) throw new Error("No authorized uncased drill target");
  await page.goto(base,{waitUntil:"domcontentloaded"});
  await page.getByRole("button",{name:`Investigate ${oid}`,exact:true}).click();
  await page.getByLabel("Scenario").selectOption("base-v1");
  await page.getByRole("button",{name:"Apply context"}).click();
  await page.getByText("Synthetic scenario",{exact:true}).first().waitFor();
  await page.getByRole("button",{name:"Generate proposal evidence"}).scrollIntoViewIfNeeded();
  await page.evaluate(()=>{
    const overlay=document.createElement("div"); overlay.id="live-drill-annotation";
    overlay.style.cssText="position:fixed;top:12px;right:18px;padding:18px 24px;background:#7f1d1d;color:white;border:2px solid white;border-radius:12px;font:16px system-ui;z-index:99999;max-width:480px;box-shadow:0 10px 30px #0004";
    overlay.textContent="FAULT INJECTION • Live AWS telemetry\nPreparing crash-before-ack drill";
    overlay.style.whiteSpace="pre-line"; document.body.appendChild(overlay);
  });
  const since=continuation?Date.parse("2026-10-18T22:57:15.650Z"):Date.now();
  let jobId=continuation?.job_id;
  if(!jobId) {
    const submission=page.waitForResponse((r)=>new URL(r.url()).pathname==="/api/jobs"&&r.request().method()==="POST");
    await page.getByRole("button",{name:"Generate proposal evidence"}).click();
    jobId=(await (await submission).json()).job_id;
    await writeFile(path.join(directory,"continuation.json"),JSON.stringify({job_id:jobId,target_id:oid}));
  }
  const samples=[...prior]; let readyRevision=prior.find((s)=>s.job_state==="ready")?.job_revision, seenInFlight=prior.some((s)=>s.in_flight>0), zeroCount=0, success=false, finalJob;
  for(let i=0;i<120;i++) {
    const processResult=spawnSync("uv",["run","python","scripts/demo_telemetry.py",String(since)],{cwd:root,encoding:"utf8",timeout:30000});
    if(processResult.status!==0) throw new Error("Live AWS telemetry read failed");
    const t=JSON.parse(processResult.stdout);
    const elapsed=Math.round((Date.now()-since)/1000);
    finalJob=(await api("operator_a",`/api/jobs/${jobId}`)).body;
    if(finalJob.state==="ready" && readyRevision===undefined) readyRevision=finalJob.revision;
    if(t.in_flight>0) seenInFlight=true;
    zeroCount=t.visible===0&&t.in_flight===0?zeroCount+1:0;
    const sample={elapsed_seconds:elapsed,...t,job_state:finalJob.state,job_revision:finalJob.revision}; samples.push(sample);
    await page.evaluate((s)=>{
      document.getElementById("live-drill-annotation").textContent=`FAULT INJECTION • Live AWS telemetry\n${s.resumed?"RECOVERY READBACK • Same recorded job\n":""}Elapsed: ${s.elapsed_seconds} seconds\nJob: ${s.job_state} · revision ${s.job_revision}\nWorker crash log events: ${s.crash_events}\nSQS visible: ${s.visible} · in flight: ${s.in_flight}\nQueue counts are approximate.`;
    },{...sample,resumed:!!continuation});
    await writeFile(path.join(directory,"telemetry.json"),JSON.stringify({source:"Live SQS attributes, worker CloudWatch logs and authenticated API reads",samples},null,2));
    if(elapsed>=190&&seenInFlight&&zeroCount>=2&&t.crash_events>=1&&finalJob.state==="ready") {success=true;break;}
    if(["failed","unknown","blocked","expired"].includes(finalJob.state)) break;
    await wait(5000);
  }
  let approvalState,repeatStatus,casesCreated;
  if(success&&finalJob.result?.validation?.proposal_state==="pending") {
    // Independent pre-approval evidence check, including the newly discovered
    // synthetic-citation requirement, even when filming the preceding release.
    const context=(await api("operator_a",`/api/context?target_type=Order&target_id=${oid}&scenario_id=base-v1`)).body;
    const syntheticRefs=new Set((context.evidence||[]).filter((r)=>r.is_synthetic===true).map((r)=>r.ref));
    const findings=finalJob.result?.analysis?.findings||[];
    if(!findings.length || findings.some((f)=>f.kind==="synthetic_context"&&!f.evidence_refs.some((r)=>syntheticRefs.has(r)))) {
      throw new Error("Independent review rejected unsupported synthetic context");
    }
    const p=(await api("operator_a",`/api/jobs/${jobId}/proposal`,{})).body;
    const d=await api("reviewer",`/api/proposals/${p.proposal_id}/decision`,{decision:"approve",expected_revision:p.revision,reason:"Labelled crash/redelivery demonstration; independent evidence review"});
    const current=(await api("reviewer",`/api/proposals/${p.proposal_id}`)).body;
    repeatStatus=(await api("reviewer",`/api/proposals/${p.proposal_id}/decision`,{decision:"approve",expected_revision:current.revision})).status;
    casesCreated=(await api("reviewer","/api/cases")).body.items.filter((c)=>c.proposal_id===p.proposal_id).length;
    approvalState=d.body.state;
    success=approvalState==="executed"&&repeatStatus===409&&casesCreated===1&&finalJob.revision===readyRevision;
    await page.evaluate((s)=>{document.getElementById("live-drill-annotation").textContent=`FAULT INJECTION • Verified live result\nWorker crash recorded; SQS drained after redelivery\nJob ready · durable revision unchanged\nInternal cases: ${s.casesCreated}\nRepeat approval: HTTP ${s.repeatStatus}\nActual wait shortened in the edited video.`;},{casesCreated,repeatStatus});
  } else success=false;
  await wait(7000); await page.screenshot({path:path.join(directory,"verified-drill.png")});
  const video=page.video(); await ctx.close(); await video.saveAs(path.join(directory,"07-crash-redelivery.webm"));
  const report={source:"Genuine live fault-injection capture with live AWS telemetry annotations",recovery_from:resumeDirectory,interruption_disclosure:continuation?"Original recorder interrupted during rolling release; same job recovered with read-only diagnostic and authenticated readback. Fault-clearing release overlaps the recovery interval.":null,passed:success,elapsed_seconds:samples.at(-1)?.elapsed_seconds,crash_events:samples.at(-1)?.crash_events,seen_in_flight:seenInFlight,drained:zeroCount>=2,revision_unchanged:finalJob?.revision===readyRevision,approval_state:approvalState,repeat_approval_status:repeatStatus,cases_created:casesCreated,video:path.join(directory,"07-crash-redelivery.webm")};
  await writeFile(path.join(directory,"report.json"),JSON.stringify(report,null,2));
  console.log(`Drill recording ${success?"passed":"failed"}; report ${path.relative(root,path.join(directory,"report.json"))}`);
  if(!success) throw new Error("The recorded live drill did not pass");
}

async function captureAux(directory) {
  const clips=[];
  for(const [name,url,seconds] of [
    ["09-architecture",`file://${path.join(root,"docs/architecture.svg")}`,10],
    ["11-static-replay","http://127.0.0.1:4173/evidence/",15],
  ]) {
    stage=`capture ${name}`;
    const ctx=await browser.newContext({viewport:{width:1600,height:900},recordVideo:{dir:directory,size:{width:1600,height:900}}});
    const page=await ctx.newPage(); let apiRequests=0;
    page.on("request",(r)=>{if(new URL(r.url()).pathname.startsWith("/api"))apiRequests++;});
    if(name==="09-architecture") {
      await page.goto("about:blank");
      const png=await readFile(path.join(root,".local/aws-symbols-review.png"));
      await page.setContent(`<html><body style="margin:0;background:#f8fafc;display:flex;align-items:center;justify-content:center;height:100vh"><img src="data:image/png;base64,${png.toString("base64")}" style="max-width:98vw;max-height:96vh"></body></html>`);
    } else {
      await page.goto(url,{waitUntil:"domcontentloaded"});
      await page.getByRole("heading",{name:"Late delivery queue"}).waitFor();
      await wait(4000); await page.getByRole("button",{name:/^Investigate /}).first().click();
    }
    await wait(seconds*1000);
    await page.screenshot({path:path.join(directory,`${name}.png`),timeout:10000}).catch(()=>{});
    const video=page.video();await ctx.close();const file=path.join(directory,`${name}.webm`);await video.saveAs(file);
    clips.push({name,path:file,api_requests:apiRequests,source:name==="09-architecture"?"Repository AWS diagram artifact":"Authored fixture replay; visibly simulated actions"});
    console.log(`Captured ${name}; API requests ${apiRequests}`);
  }
  await writeFile(path.join(directory,"auxiliary-clips.json"),JSON.stringify({clips},null,2));
}

async function finishCapture(identities,directory) {
  const failed=JSON.parse(await readFile(path.join(directory,"continuation.json"),"utf8"));
  const earlier=JSON.parse(await readFile(path.join(root,".local/demo/drill-2026-10-18T22-57-15-650Z/continuation.json"),"utf8"));
  const api=async(user,route,body)=>{
    const r=await fetch(base+route,{method:body?"POST":"GET",headers:{Authorization:`Bearer ${identities[user].token}`,"Content-Type":"application/json"},...(body?{body:JSON.stringify(body)}:{})});
    return {status:r.status,body:await r.json()};
  };
  const failure=(await api("operator_a",`/api/jobs/${failed.job_id}`)).body;
  if(failure.state!=="ready"||failure.result?.validation?.proposal_state!=="none")throw new Error("Expected retained no-proposal outcome");
  const blocked=await api("operator_a",`/api/jobs/${failed.job_id}/proposal`,{});
  if(blocked.status<400)throw new Error("Rejected output unexpectedly produced a proposal");
  const proposals=(await api("reviewer","/api/proposals")).body.items;
  const proposal=proposals.find((p)=>p.job_id===earlier.job_id&&p.state==="executed");
  if(!proposal)throw new Error("Earlier independently checked case is unavailable");
  const repeated=await api("reviewer",`/api/proposals/${proposal.proposal_id}/decision`,{decision:"approve",expected_revision:proposal.revision,reason:"Recorded duplicate execution verification"});
  const count=(await api("reviewer","/api/cases")).body.items.filter((c)=>c.proposal_id===proposal.proposal_id).length;
  if(repeated.status!==409||count!==1)throw new Error("Earlier approval invariant failed");
  const record={model_job_state:failure.state,action_proposed:failure.result.analysis.action!==null,validation:failure.result.validation,save_refused_status:blocked.status,earlier_case_state:proposal.state,earlier_case_count:count,repeat_approval_status:repeated.status,selection:"Earlier independently checked crash-drill case, not the no-action job"};
  await writeFile(path.join(directory,"completion-evidence.json"),JSON.stringify(record,null,2));
  console.log(`Verified actual no-proposal outcome: validation ${record.validation.ok}; save HTTP ${blocked.status}`);
  for(const [name,user,seconds,view] of [
    ["05-independent-approval","reviewer",13,"Action review"],
    ["06-ungranted-viewer","viewer",15,null],
    ["08-measured-evidence","operator_a",15,"Evidence"],
    ["10-recommendation","operator_a",10,"Evidence"],
  ]) {
    stage=`capture ${name}`;
    const ctx=await browser.newContext({viewport:{width:1600,height:900},recordVideo:{dir:directory,size:{width:1600,height:900}}});
    await ctx.addInitScript((token)=>sessionStorage.setItem("ops_access_token",token),identities[user].token);
    const page=await ctx.newPage(); await page.goto(base,{waitUntil:"domcontentloaded"});
    await page.getByRole("heading",{name:"Late delivery queue"}).waitFor();
    await page.addStyleTag({content:".review-grid dl > div:nth-child(2) dd {filter:blur(12px)} .review-grid select {max-width:100%}"});
    if(view)await page.getByRole("navigation").getByRole("button",{name:new RegExp(view)}).click();
    if(name==="05-independent-approval") {
      await page.getByLabel("Proposal",{exact:true}).selectOption(proposal.proposal_id);
      await page.getByText("executed",{exact:true}).waitFor();
    } else if(name==="06-ungranted-viewer") {
      await page.getByText("No late open orders are visible within your granted scope.").waitFor();
    } else if(name==="10-recommendation") {
      await page.getByRole("heading",{name:"Ship the deterministic workspace"}).scrollIntoViewIfNeeded();
    }
    await wait(seconds*1000);await page.screenshot({path:path.join(directory,`${name}.png`)});
    const video=page.video();await ctx.close();await video.saveAs(path.join(directory,`${name}.webm`));
    console.log(`Captured ${name}; actual live readback, no model rerun`);
  }
}

async function main() {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const passwords = JSON.parse(input);
  input = "";
  browser = await chromium.launch({headless: true});
  const identities = {};
  for (const user of ["operator_a", "reviewer", "viewer"]) identities[user] = await authenticate(user, passwords[user]);
  // Capture phases are added only after real sign-in and authorization are verified.
  await mkdir(path.join(root, ".local/demo"), {recursive: true});
  await writeFile(path.join(root, ".local/demo/auth-check.json"), JSON.stringify({base_url: base, verified_at: new Date().toISOString(), authentication: "real Cognito authorization code + PKCE", roles: Object.fromEntries(Object.entries(identities).map(([k,v])=>[k,v.role]))}, null, 2));
  console.log("Browser authentication checks passed; no tokens persisted");
  if (process.argv.includes("--capture")) await capture(identities);
  if (process.argv.includes("--drill")||process.argv.includes("--resume-drill")) await captureDrill(identities);
  if (process.argv.includes("--aux")) await captureAux(path.resolve(process.argv[process.argv.indexOf("--aux")+1]));
  if (process.argv.includes("--finish")) await finishCapture(identities,path.resolve(process.argv[process.argv.indexOf("--finish")+1]));
  await browser.close();
}
main().catch(async (error) => {
  console.error(`Live demo preparation failed at ${stage} (${error.name}); credentials and request payloads withheld`);
  if (browser) await browser.close();
  process.exitCode = 1;
});
