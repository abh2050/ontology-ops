// Build local presentation assets; no API credentials or paid calls.
// Run from the repository root while `docs/` is served at CASE_STUDY_BASE.
import {chromium} from '../frontend/node_modules/playwright/index.mjs';
import {execFileSync} from 'node:child_process';
import {existsSync,readFileSync,writeFileSync} from 'node:fs';
const base=process.env.CASE_STUDY_BASE||'http://127.0.0.1:4176/ontology-ops/';
const destination='docs/assets/case-study';
const browser=await chromium.launch({headless:true});
try{
  const page=await browser.newPage();
  await page.goto(base+'diagrams/aws-deployment.svg');
  const icons=await page.evaluate(async()=>{
    const xml=new DOMParser().parseFromString(await (await fetch('aws-deployment.drawio')).text(),'text/xml');
    return ['cloudfront','fargate','rds','sqs','bedrock'].map(name=>{
      const cell=[...xml.querySelectorAll('mxCell')].find(cell=>cell.getAttribute('style')?.includes('resIcon=mxgraph.aws4.'+name+';'));
      if(!cell)throw Error('Missing official draw.io symbol: '+name);
      const shape=document.querySelector(`[data-cell-id="${cell.id}"] > g`),box=shape.getBBox(),clone=shape.cloneNode(true);
      clone.removeAttribute('transform');
      clone.querySelectorAll('[style]').forEach(element=>element.removeAttribute('style'));
      return {name,svg:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="${box.x} ${box.y} ${box.width} ${box.height}" width="56" height="56"><!-- Official mxgraph.aws4.${name}; extracted from docs/diagrams/aws-deployment.svg -->${clone.outerHTML}</svg>\n`};
    });
  });
  for(const {name,svg}of icons){const path=`${destination}/${name}.svg`;if(existsSync(path))execFileSync('apply_patch',[],{input:`*** Begin Patch\n*** Delete File: ${path}\n*** End Patch\n`});execFileSync('apply_patch',[],{input:`*** Begin Patch\n*** Add File: ${path}\n+${svg.trim()}\n*** End Patch\n`});}
  for(const name of ['queue','graph','review']){
    const source=`brag-output-2026-10-19-134102/composition/assets/${name}.png`;
    if(!existsSync(source)){
      if(existsSync(`${destination}/${name}.webp`)){console.log('Kept committed capture: '+name);continue;}
      throw Error('Original authored UI capture not found: '+source);
    }
    const encoded=await page.evaluate(async source=>{
      const image=new Image();image.src=source;await image.decode();
      const canvas=document.createElementNS('http://www.w3.org/1999/xhtml','canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;
      canvas.getContext('2d').drawImage(image,0,0);return canvas.toDataURL('image/webp',.87).split(',')[1];
    },'data:image/png;base64,'+readFileSync(source).toString('base64'));
    writeFileSync(`${destination}/${name}.webp`,Buffer.from(encoded,'base64'));
  }
  const artSource=existsSync('.local/case-study/higgsfield-illustration.png')?'.local/case-study/higgsfield-illustration.png':destination+'/higgsfield-illustration.png';
  if(existsSync(artSource)){
    const encoded=await page.evaluate(async source=>{
      const image=new Image();image.src=source;await image.decode();
      const canvas=document.createElementNS('http://www.w3.org/1999/xhtml','canvas');canvas.width=1920;canvas.height=Math.round(image.naturalHeight*1920/image.naturalWidth);
      canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);return canvas.toDataURL('image/webp',.88).split(',')[1];
    },'data:image/png;base64,'+readFileSync(artSource).toString('base64'));
    writeFileSync(destination+'/higgsfield-illustration.webp',Buffer.from(encoded,'base64'));
  }
  await page.setViewportSize({width:1200,height:630});
  await page.goto(base+'assets/case-study/social.svg');
  await page.screenshot({path:destination+'/social.png'});
  console.log('Built five native AWS icons, optimized real UI captures and available illustration, and a 1200×630 social image.');
}finally{await browser.close()}
