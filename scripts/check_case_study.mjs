// Read-only browser QA for the buildless portfolio; screenshots stay gitignored.
import {chromium,expect} from '../frontend/node_modules/@playwright/test/index.mjs';
import {mkdirSync,existsSync} from 'node:fs';
const base=process.env.CASE_STUDY_BASE||'http://127.0.0.1:4176/ontology-ops/';
const folder='.local/case-study/hero-media/review';mkdirSync(folder,{recursive:true});
const browser=await chromium.launch({headless:true});
let apiRequests=0;const errors=[],failed=[],reducedMotionVideoRequests=[];
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(new URL(request.url()).pathname.includes('/api/'))apiRequests++;if(request.url().endsWith('connected-operations.mp4'))reducedMotionVideoRequests.push(request.url());});
  page.on('response',response=>{if(response.status()>=400)failed.push(`${response.status()} ${response.url()}`)});
  await page.goto(base,{waitUntil:'networkidle'});
  await expect(page).toHaveTitle('Ontology Ops — Delivery investigations, connected');
  await expect(page.locator('h1')).toHaveCount(1);
  await expect(page.locator('h1')).toHaveText('Turn late deliveries into focused investigations.');
  await expect(page.locator('#hero-motion')).toHaveJSProperty('paused',true);
  await expect(page.locator('#hero-motion')).not.toHaveAttribute('src');
  await expect(page.locator('#motion-toggle')).toHaveAttribute('aria-pressed','false');
  for(const view of ['queue','graph','review']){
    await page.locator(`[data-view="${view}"]`).click();
    await expect(page.locator('#product-panel')).toHaveAttribute('aria-labelledby','product-tab-'+view);
    await expect(page.locator('#product-image')).toHaveAttribute('src','assets/case-study/'+view+'.webp');
    await page.locator('#product-image').evaluate(image=>image.decode());
  }
  await page.locator('#product-tab-queue').focus();await page.keyboard.press('End');await expect(page.locator('#product-tab-review')).toBeFocused();await page.keyboard.press('Home');await expect(page.locator('#product-tab-queue')).toBeFocused();
  await page.locator('[data-view="graph"]').click();
  const links=await page.locator('a[href]').evaluateAll(anchors=>anchors.map(anchor=>anchor.getAttribute('href')));
  for(const href of new Set(links)){
    if(href.startsWith('#')){await expect(page.locator(href)).toHaveCount(1);continue}
    if(href.startsWith('https://github.com/abh2050/ontology-ops/')){
      const path=href.replace(/^https:\/\/github.com\/abh2050\/ontology-ops\/(?:blob|tree)\/main\//,'').split('#')[0];
      if(!existsSync(path))throw Error('Repository source link does not resolve locally: '+href);
    }else if(!href.startsWith('https:')){
      const response=await page.request.get(new URL(href,base).href);if(!response.ok())throw Error('Broken local link: '+href);
    }
  }
  for(const image of await page.locator('img').all()){await image.scrollIntoViewIfNeeded();await expect(image).toHaveJSProperty('complete',true);await expect(image).not.toHaveJSProperty('naturalWidth',0)}
  await page.locator('#workflow-detail > summary').click();
  for(let index=0;index<6;index++){
    await page.locator(`[data-stage="${index}"]`).click();
    await expect(page.locator('#stage-panel')).toHaveAttribute('aria-labelledby','stage-'+index);
    await expect(page.locator(`[data-stage="${index}"]`)).toHaveAttribute('aria-selected','true');
    const href=await page.locator('#stage-source').getAttribute('href');if(!existsSync(href.split('/blob/main/')[1]))throw Error('Broken stage source: '+href);
  }
  await page.locator('#stage-0').focus();await page.keyboard.press('End');await expect(page.locator('#stage-5')).toBeFocused();await page.keyboard.press('Home');await expect(page.locator('#stage-0')).toBeFocused();await page.keyboard.press('ArrowDown');await expect(page.locator('#stage-1')).toBeFocused();
  for(const button of await page.locator('.arch-node').all()){await button.click();await expect(button).toHaveAttribute('aria-pressed','true');await expect(page.locator('#arch-title')).not.toBeEmpty()}
  await page.locator('#policy-detail > summary').click();
  for(const value of ['cause','invented','timeout','self','valid']){await page.selectOption('#gate-scenario',value);await expect(page.locator('#gate-state')).not.toBeEmpty();await expect(page.locator('#gate-steps li')).toHaveCount(4)}
  await page.locator('#comparison-detail > summary').click();
  for(const [model,mode,value]of [['nova1','real','32.6%'],['nova1','scenario','46.7%'],['nova2','scenario','41.7%'],['nova2','real','58.1%']]){await page.selectOption('#model-select',model);await page.selectOption('#mode-select',mode);await expect(page.locator('#candidate-value')).toHaveText(value)}
  await page.locator('#stage-0').click();await page.locator('[data-node="api"]').click();
  for(const id of ['workflow-detail','policy-detail','comparison-detail'])await page.locator('#'+id+' > summary').click();
  for(const width of [1440,1024,768,390,320]){
    await page.setViewportSize({width,height:1000});await page.evaluate(()=>scrollTo(0,0));
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow){const elements=await page.locator('body *').evaluateAll(elements=>elements.filter(element=>element.getBoundingClientRect().right>innerWidth+.01||element.scrollWidth>element.clientWidth+1).slice(0,20).map(element=>({tag:element.tagName,class:element.className,right:element.getBoundingClientRect().right,scrollWidth:element.scrollWidth,clientWidth:element.clientWidth})));await page.screenshot({path:`${folder}/${width}-overflow.png`});throw Error('Horizontal overflow at '+width+'px: '+JSON.stringify(elements));}
    if(width===390){await page.getByRole('button',{name:'Menu +',exact:true}).click();await expect(page.locator('.menu')).toHaveAttribute('aria-expanded','true');await page.keyboard.press('Escape');await expect(page.locator('.menu')).toHaveAttribute('aria-expanded','false')}
    if(width===1440||width===390){await page.screenshot({path:`${folder}/${width}-hero.png`});for(const id of ['problem','architecture','evaluation','product']){await page.locator('#'+id).evaluate(element=>element.scrollIntoView({block:'start',behavior:'instant'}));await page.screenshot({path:`${folder}/${width}-${id}.png`})}}
  }
  await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:`${folder}/desktop-full.png`,fullPage:true});
  if(apiRequests||errors.length||failed.length||reducedMotionVideoRequests.length)throw Error(JSON.stringify({apiRequests,errors,failed,reducedMotionVideoRequests}));
  const motionPage=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'no-preference'});
  motionPage.on('pageerror',error=>errors.push(error.message));
  await motionPage.goto(base,{waitUntil:'networkidle'});
  await expect(motionPage.locator('#hero-motion')).toHaveJSProperty('paused',false,{timeout:15000});
  await expect(motionPage.locator('#hero-motion')).toHaveJSProperty('muted',true);
  await motionPage.locator('#product').evaluate(element=>element.scrollIntoView({behavior:'instant'}));
  await expect(motionPage.locator('#hero-motion')).toHaveJSProperty('paused',true);
  await motionPage.evaluate(()=>scrollTo(0,0));
  await expect(motionPage.locator('#hero-motion')).toHaveJSProperty('paused',false);
  await motionPage.getByRole('button',{name:'Pause animation',exact:true}).click();
  await expect(motionPage.locator('#hero-motion')).toHaveJSProperty('paused',true);
  await motionPage.locator('#product').evaluate(element=>element.scrollIntoView({behavior:'instant'}));
  await motionPage.evaluate(()=>scrollTo(0,0));
  await expect(motionPage.locator('#hero-motion')).toHaveJSProperty('paused',true);
  await motionPage.getByRole('button',{name:'Play animation',exact:true}).click();
  await expect(motionPage.locator('#hero-motion')).toHaveJSProperty('paused',false);
  await motionPage.emulateMedia({reducedMotion:'reduce'});
  await expect(motionPage.locator('#hero-motion')).toHaveJSProperty('paused',true);
  await expect(motionPage.locator('#concept-stage')).not.toHaveClass(/motion-ready/);
  await motionPage.evaluate(()=>document.getElementById('hero-motion').dispatchEvent(new Event('error')));
  await expect(motionPage.locator('#motion-toggle')).toBeDisabled();
  await expect(motionPage.locator('.concept-poster')).toBeVisible();
  await motionPage.close();
  const savingPage=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'no-preference'});
  await savingPage.addInitScript(()=>{const connection=new EventTarget();connection.saveData=true;Object.defineProperty(navigator,'connection',{value:connection});});
  await savingPage.goto(base,{waitUntil:'networkidle'});
  await expect(savingPage.locator('#hero-motion')).not.toHaveAttribute('src');
  await expect(savingPage.locator('#hero-motion')).toHaveJSProperty('paused',true);
  await savingPage.close();
  const noJS=await browser.newPage({javaScriptEnabled:false,viewport:{width:390,height:844}});await noJS.goto(base);await expect(noJS.locator('noscript')).toBeVisible();await expect(noJS.locator('h1')).toBeVisible();await expect(noJS.locator('.concept-poster')).toBeVisible();await expect(noJS.locator('#hero-motion')).not.toHaveAttribute('src');await noJS.close();
  if(errors.length)throw Error(JSON.stringify(errors));
  console.log(JSON.stringify({result:'PASS',responsive_widths:[1440,1024,768,390,320],product_views:3,product_and_workflow_keyboard_tabs:'pass',mobile_menu:'pass',architecture_components:6,policy_paths:5,comparison_cells:4,local_and_source_links:'pass',images:'pass',javascript_errors:errors,failed_requests:failed,api_requests:apiRequests,reduced_motion:'still poster; zero video requests',motion:'muted autoplay, explicit pause/play, preference changes and error fallback passed',save_data:'still poster; video source not attached',no_javascript:'poster and default content available',screenshots:folder},null,2));
}finally{await browser.close()}
