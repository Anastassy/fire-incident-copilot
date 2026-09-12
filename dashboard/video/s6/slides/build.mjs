import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';

// Runtime locations are explicit so this source is portable across workstations.
function requiredPath(name){
  const value=process.env[name];
  if(!value || !path.isAbsolute(value)) throw new Error(`${name} must be an absolute path`);
  return value;
}
const workspaceDir=requiredPath('FIREWATCH_OUTPUT_DIR');
const outputDir=path.join(workspaceDir,'slides');
const revision=process.argv[2]||'v3';
if(!/^[A-Za-z0-9_-]+$/.test(revision)) throw new Error('Revision must use letters, numbers, underscores or hyphens');
const buildDir=path.join(workspaceDir,'.build');
const skill=requiredPath('PRESENTATIONS_SKILL_DIR');
const python=requiredPath('RUNTIME_PYTHON');
const runtimeModules=requiredPath('RUNTIME_NODE_MODULES');
const runtimeRequire=createRequire(path.join(runtimeModules,'package.json'));
const {Presentation, PresentationFile, FileBlob}=await import(pathToFileURL(runtimeRequire.resolve('@oai/artifact-tool')));
const {resolvePresentationFont,finalizePresentation}=await import(pathToFileURL(path.join(skill,'container_tools/artifact_tool_utils.mjs')));
const font=resolvePresentationFont();
const colors={bg:'#14191c',white:'#f5f4ef',orange:'#ed995c',muted:'#a6afb3',line:'#51616a',node:'#1c252a'};
const presentation=Presentation.create({slideSize:{width:1920,height:1080}});
const cues=[['B01',0,5],['B02',5,11],['B03',11,15],['B04',15,22],['B05',22,25],['T01',90,95],['T02',95,100],['T03',100,105],['F01',105,110],['F02',110,115],['F03',115,120]];
const placements=[];
const scriptPath='dashboard/VIDEO_SCRIPT.md';
const report='https://www.csb.gov/assets/1/20/chevron_final_investigation_report_2015-01-28.pdf';

function text(slide,value,x,y,w,h,size=48,color=colors.white,bold=false,alignment='left'){
  const shape=slide.shapes.add({geometry:'textbox',name:value.replaceAll('\n',' ').slice(0,90),
    position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
  shape.text=value;shape.text.style={typeface:font,fontSize:size,color,bold,alignment,
    verticalAlignment:'middle',autoFit:'none',wrap:true,insets:{top:0,right:0,bottom:0,left:0}};
  placements.push({slide:slide.id,text:value,x,y,w,h});
  return shape;
}
function makeSlide(code,notes){
  const slide=presentation.slides.add();slide.background.fill=colors.bg;
  const cue=cues.find(c=>c[0]===code);
  slide.speakerNotes.textFrame.setText(`${code}. Video timeline ${cue[1]}–${cue[2]} seconds.\nSource: VIDEO_SCRIPT.md, revision S6, September 12, 2026.\n${scriptPath}\n${notes}\nBottom 180 px remain clear for the video subtitle track.`);
  return slide;
}
function node(slide,label,x,y,w=280,h=125,color=colors.orange){
  const shape=slide.shapes.add({geometry:'rect',name:label,
    position:{left:x,top:y,width:w,height:h},fill:colors.node,line:{fill:color,width:2}});
  shape.text=label;shape.text.style={typeface:font,fontSize:38,bold:true,color:colors.white,
    alignment:'center',verticalAlignment:'middle',autoFit:'none',insets:{left:10,right:10,top:5,bottom:5}};
  placements.push({slide:slide.id,text:label,x,y,w,h});return shape;
}
function flow(slide,{y=510,uiY=285}={}){
  const state=node(slide,'State',115,y,265);
  const bridge=node(slide,'Gateway\nbridge',530,y,265);
  const platform=node(slide,'Data\nPlatform',945,y,300);
  const agent=node(slide,'Agent',1395,y,300);
  const ui=node(slide,'Operator UI',1395,uiY,300,125,colors.muted);
  const link=(a,b,fromSide='right',toSide='left',fill=colors.orange,kind='straight')=>slide.shapes.connect(a,b,{fromSide,toSide,kind,
    line:{fill,width:3},tail:{type:'arrow',width:'med',length:'med'}});
  link(state,bridge);link(bridge,platform);link(platform,agent);
  link(agent,ui,'top','bottom');
  link(state,ui,'top','left',colors.muted,'elbow');
  text(slide,'Direct source view',650,uiY+26,560,55,32,colors.muted);
  text(slide,'Evidence import and agent checks',532,y+148,1160,60,34,colors.orange);
}

{
  const s=makeSlide('B01','Problem and audience statement from project context. Source names are illustrative categories, not a live application or simulated measurements.');
  text(s,'FIREWATCH',115,83,700,50,32,colors.orange,true);
  text(s,'Supporting fire\nincident command.',115,210,1180,272,108,colors.white,true);
  text(s,'Many sources.\nOne picture to piece together.',119,552,1170,151,48,colors.muted);
  ['Cameras','Sensors','Radio','Power & connectivity','Access'].forEach((label,i)=>text(s,label,1390,239+i*103,430,70,label.length>16?35:43,i===2?colors.orange:colors.white));
}
{
  const s=makeSlide('B02',`Historical investigation evidence, E1. Pipe temperature, not ambient temperature. Some firefighters believed the pipe was near 130°F; actual temperature approached 640°F. Rounded Celsius conversions are 54°C and 338°C. These are not competing sensor values or product results.\nCSB, Chevron Richmond Refinery Pipe Rupture and Fire, January 2015, section 5.3.2, printed p. 93.\n${report}`);
  text(s,'Chevron Richmond, 2012',115,94,1680,86,54,colors.white,true);
  text(s,'Some firefighters\nbelieved',115,252,770,140,47,colors.muted);
  text(s,'Actual pipe\ntemperature',1040,252,770,140,47,colors.muted);
  text(s,'≈130°F',105,400,815,190,150,colors.white,true);
  text(s,'≈640°F',1028,400,815,190,150,colors.orange,true);
  text(s,'54°C',117,615,700,75,59,colors.muted);
  text(s,'338°C',1042,615,700,75,59,colors.muted);
  text(s,'Pipe temperature, not ambient temperature',115,746,1660,57,33,colors.muted);
  text(s,'CSB investigation  §5.3.2, p. 93',115,818,1660,45,29,colors.muted);
}
{
  const s=makeSlide('B03','General information problem. This is an illustrative information flow, not a claim about the sole cause of Chevron or live measurements.');
  text(s,'Which information\nstill reflects reality?',115,240,1690,260,110,colors.white,true);
  text(s,'Different sources',115,661,510,76,39,colors.muted);
  text(s,'Different update times',677,661,600,76,39,colors.orange);
  text(s,'Missing evidence',1332,661,510,76,39,colors.muted);
  text(s,'Illustrative information flow',115,816,1660,47,29,colors.muted);
}
{
  const s=makeSlide('B04','Product concept, not a fabricated application screen. The three labels describe the intended evidence picture.');
  text(s,'Fire Incident Copilot',115,96,1640,79,48,colors.orange,true);
  text(s,'Build a picture\nyou can verify.',115,235,1680,268,112,colors.white,true);
  text(s,'Confirmed',115,652,470,82,49,colors.white,true);
  text(s,'Still unknown',690,652,535,82,49,colors.orange,true);
  text(s,'Supporting sources',1285,652,565,82,43,colors.white,true);
  text(s,'Product concept',115,816,1660,47,29,colors.muted);
}
{
  const s=makeSlide('B05','Title-only transition. Existing interface footage begins at 25 seconds. No historical event reconstruction.');
  text(s,'Let’s see it in action.',115,285,1690,177,112,colors.white,true);
  text(s,'Next: a training simulation',119,504,1690,90,50,colors.orange);
}
{
  const s=makeSlide('T01','Actual connection topology required by S6/G4: State directly supplies the UI. Separately, State supplies the gateway bridge, which imports data into Data Platform. Agent queries platform evidence and returns results to the UI. The UI is not exclusively downstream of Platform.');
  text(s,'One traceable evidence flow',115,96,1690,124,88,colors.white,true);
  flow(s,{y:510,uiY:285});
  text(s,'Source, time and run identity remain attached to the evidence',115,811,1690,61,34,colors.muted);
}
{
  const s=makeSlide('T02','Design goals. World Model: known + unknown. Active Sensing: next evidence to check. These concepts are not claims of full implementation. Diagram retains the actual component topology.');
  text(s,'Design goals',115,85,1680,101,88,colors.orange,true);
  text(s,'World Model',115,214,720,83,55,colors.white,true);
  text(s,'known + unknown',115,301,790,63,42,colors.muted);
  text(s,'Active Sensing',1030,214,790,83,55,colors.white,true);
  text(s,'next evidence to check',1030,301,790,63,42,colors.muted);
  flow(s,{y:604,uiY:409});
}
{
  const s=makeSlide('T03','S6/G4 integration statement requires the actual end-to-end trace. Volume refers to a previously accepted replay, not a count of LLM analyses or throughput.\nSource: dashboard/live/VALIDATION.md in the project repository.');
  text(s,'Replay connected to evidence',115,94,1690,123,87,colors.white,true);
  text(s,'Shared run, time and source IDs',115,248,1690,90,47,colors.muted);
  text(s,'811',104,380,790,198,171,colors.orange,true);
  text(s,'43',1023,380,790,198,171,colors.orange,true);
  text(s,'observations',118,599,780,78,50,colors.white);
  text(s,'transcript entries',1036,599,780,78,50,colors.white);
  text(s,'Validated replay',115,723,1680,59,35,colors.white,true);
  text(s,'Replay volume, not LLM analyses or throughput',115,789,1680,45,30,colors.muted);
  text(s,'Source: live/VALIDATION.md',115,843,1680,42,28,colors.muted);
}
{
  const s=makeSlide('F01','Target pilot partner profile, not an existing customer. Intended value is a correct evidence-backed command briefing.');
  text(s,'A correct briefing,\nwith supporting evidence.',115,173,1690,269,98,colors.white,true);
  text(s,'Target pilot',119,535,1680,65,37,colors.orange,true);
  text(s,'Industrial command centres',115,621,1690,102,66,colors.white,true);
  text(s,'Sites with their own fire service',119,741,1690,75,44,colors.muted);
}
{
  const s=makeSlide('F02','Pilot target from BUSINESS_CASE. At least 30 percent less time to a correct answer, with no increase in errors. Not yet measured, not an achieved business outcome. Correctness and mistakes must be measured in the pilot. LLM latency is not the business metric.');
  text(s,'Pilot target',115,96,1690,77,50,colors.orange,true);
  text(s,'≥30%',105,214,1690,252,214,colors.white,true);
  text(s,'less time to a correct answer',115,498,1690,111,79,colors.white,true);
  text(s,'No increase in errors',119,657,1680,83,49,colors.muted);
  text(s,'Not yet measured',119,787,1680,63,39,colors.orange,true);
}
{
  const s=makeSlide('F03','One requested next step: seeking an industrial training partner. No claimed ROI, customer, safety certification or business result.');
  text(s,'Firewatch',115,105,1690,170,130,colors.orange,true);
  text(s,'Brief command\nwith evidence.',115,314,1690,277,116,colors.white,true);
  text(s,'Seeking an industrial training partner',119,747,1690,87,48,colors.white);
}

await fs.mkdir(buildDir,{recursive:true});await fs.mkdir(outputDir,{recursive:true});
for(const box of placements)if(box.y+box.h>900)throw new Error(`Subtitle safe area violation: ${box.text}`);
const candidate=path.join(buildDir,'candidate.pptx');
await(await PresentationFile.exportPptx(presentation)).save(candidate);
const finalPath=path.join(outputDir,`Firewatch-120s-S6-${revision}.pptx`);
await finalizePresentation({workspaceDir,candidatePath:candidate,finalPath,
  explicitTotalSlideCount:11,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
  pythonExecutable:python,integrityValidatorPath:path.join(skill,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath:path.join(skill,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs:['--expected-slide-size-emu','18288000,10287000','--validate-bullet-geometry','--validate-heading-fit'],
  fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,
  receiptPath:path.join(buildDir,`${revision}-validation.json`)});
const final=await PresentationFile.importPptx(await FileBlob.load(finalPath));
for(let i=0;i<cues.length;i++){
  const slide=final.slides.items[i];
  const image=await final.export({slide,format:'png',scale:1});
  await fs.writeFile(path.join(outputDir,`${cues[i][0]}.png`),new Uint8Array(await image.arrayBuffer()));
  const layout=await slide.export({format:'layout'});
  await fs.writeFile(path.join(buildDir,`${cues[i][0]}.layout.json`),await layout.text());
  console.log(`Rendered ${cues[i][0]}`);
}
await fs.writeFile(path.join(outputDir,'slides.json'),JSON.stringify({width:1920,height:1080,subtitle_safe_top:900,font,
  deck:path.basename(finalPath),slides:cues.map(([id,start_s,end_s])=>({id,start_s,end_s,png:`${id}.png`}))},null,2));
await fs.writeFile(path.join(buildDir,'placements.json'),JSON.stringify(placements,null,2));
console.log(JSON.stringify({finalPath,font,slides:cues.length}));
