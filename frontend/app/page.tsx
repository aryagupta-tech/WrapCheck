"use client";

import {useEffect,useMemo,useState} from "react";

type Decision="recovered"|"approved_exception"|"needs_review";
type Doc={document_id:string;label:string;filename:string;record_count:number;kind:string;download_url:string};
type Check={scene_take:string;circled:boolean;camera_roll:string;sound_roll:string;video_filename:string;audio_filename:string;video_state:"present"|"missing";audio_state:"present"|"missing";checksum_state:"verified"|"pending"|"failed";verified_video_copies:number;verified_audio_copies:number;video_playback_url:string|null;audio_playback_url:string|null;script_note:string};
type Finding={finding_id:string;issue_type:string;severity:string;title:string;scene_take:string;card_id:string;expected:string;observed:string;evidence:string[];required_action:string;decision:Decision|null};
type Audit={step:string;service:string;status:string;duration_ms:number;summary:string;query?:string};
type Run={run_id:string;mode:"fixture"|"live";mode_disclaimer:string;scenario_id:string;production:string;shoot_day:string;delivery_name:string;camera_cards:string[];source_documents:Doc[];checks:Check[];findings:Finding[];status:string;status_reason:string;released_by:string|null;audit:Audit[]};
type Scenario={scenario_id:string;label:string;description:string};
type Config={mode:"fixture"|"live";live_ready:boolean;scenarios:Scenario[]};
type AssetKind="camera_report"|"sound_report"|"script_notes"|"media_manifest"|"camera_video"|"production_audio";
type UploadTarget={asset:{asset_id:string;filename:string};upload_url:string;required_headers:Record<string,string>};

const API=process.env.NEXT_PUBLIC_API_URL||"http://localhost:8000";
const statusLabel:Record<string,string>={hold_media:"Hold source cards",needs_review:"Needs production review",ready_for_release:"Ready for DIT release",released_by_dit:"Released by DIT"};
const checksumLabel=(state:string)=>state==="verified"?"Two copies verified":state==="failed"?"Hash mismatch":"Second copy pending";
const apiError=(body:any,fallback:string)=>body?.error?.message||body?.detail||fallback;
const absolute=(url:string)=>url.startsWith("http")?url:API+url;

function Step({number,title,children}:{number:string;title:string;children:string}){return <div className="step"><span>{number}</span><div><b>{title}</b><p>{children}</p></div></div>}
function State({value}:{value:string}){return <span className={"state "+value}>{value.replaceAll("_"," ")}</span>}

function inferKind(file:File):AssetKind|null{
  const name=file.name.toLowerCase();
  if(name.includes("camera_report"))return "camera_report";
  if(name.includes("sound_report"))return "sound_report";
  if(name.includes("script_notes"))return "script_notes";
  if(name.includes("manifest"))return "media_manifest";
  if(name.endsWith(".mp4")||name.endsWith(".mov"))return "camera_video";
  if(name.endsWith(".wav"))return "production_audio";
  return null;
}
function contentType(file:File){
  if(file.type)return file.type;
  const ext=file.name.split(".").pop()?.toLowerCase();
  return ext==="csv"?"text/csv":ext==="json"?"application/json":ext==="wav"?"audio/wav":ext==="mov"?"video/quicktime":"video/mp4";
}

export default function Home(){
  const[config,setConfig]=useState<Config|null>(null);
  const[run,setRun]=useState<Run|null>(null);
  const[scenario,setScenario]=useState("missing-media");
  const[busy,setBusy]=useState("");
  const[error,setError]=useState("");
  const[reviewer,setReviewer]=useState("Ari Kapoor · DIT");
  const[selectedTake,setSelectedTake]=useState(2);
  const[uploadStage,setUploadStage]=useState("");

  const runGate=async(next=scenario)=>{
    setBusy("run");setError("");
    try{
      const response=await fetch(`${API}/api/handoff/runs`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({scenario_id:next,production:"The Last Signal",shoot_day:"Day 12 · 25 Aug 2026",delivery_name:"Editorial shuttle 12A"})});
      const body=await response.json();
      if(!response.ok)throw new Error(apiError(body,"Verification failed"));
      setRun(body);setSelectedTake(next==="missing-media"?2:0);
    }catch(reason){setError(reason instanceof Error?reason.message:"Verification failed")}finally{setBusy("")}
  };
  useEffect(()=>{fetch(`${API}/api/handoff/config`).then(response=>response.ok?response.json():Promise.reject(new Error("Backend unavailable"))).then((value:Config)=>{setConfig(value);void runGate("missing-media")}).catch(reason=>setError(reason.message))},[]);

  const runProblem=()=>{setScenario("missing-media");void runGate("missing-media");window.setTimeout(()=>document.getElementById("dashboard")?.scrollIntoView({behavior:"smooth"}),120)};
  const runRecovered=()=>{setScenario("clean-handoff");void runGate("clean-handoff");window.setTimeout(()=>document.getElementById("dashboard")?.scrollIntoView({behavior:"smooth"}),120)};
  const decide=async(findingId:string,decision:Decision)=>{
    setBusy(findingId);setError("");
    try{const response=await fetch(`${API}/api/handoff/findings/${findingId}/decision`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({decision,reviewer,note:decision==="recovered"?"Recovery confirmed against the new manifest.":"Reviewed during media handoff."})});const body=await response.json();if(!response.ok)throw new Error(apiError(body,"Decision failed"));setRun(body)}catch(reason){setError(reason instanceof Error?reason.message:"Decision failed")}finally{setBusy("")}
  };
  const release=async()=>{
    if(!run)return;setBusy("release");setError("");
    try{const response=await fetch(`${API}/api/handoff/runs/${run.run_id}/release`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({reviewer,note:"Two-copy verification and discrepancy review complete."})});const body=await response.json();if(!response.ok)throw new Error(apiError(body,"Release failed"));setRun(body)}catch(reason){setError(reason instanceof Error?reason.message:"Release failed")}finally{setBusy("")}
  };

  const uploadDelivery=async(files:File[])=>{
    const accepted=files.map(file=>({file,kind:inferKind(file)})).filter((item):item is {file:File;kind:AssetKind}=>Boolean(item.kind));
    if(accepted.length!==files.length||!accepted.length){setError("Select unpacked camera_report, sound_report, script_notes, manifest, MP4/MOV and WAV files.");return}
    setBusy("upload");setError("");setUploadStage("Creating private delivery…");
    try{
      let response=await fetch(`${API}/api/deliveries`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({production:"Uploaded production",shoot_day:"Current shoot day",delivery_name:"Operator upload"})});
      let body=await response.json();if(!response.ok)throw new Error(apiError(body,"Could not create delivery"));const deliveryId=body.delivery_id;
      setUploadStage(`Registering ${accepted.length} files…`);
      response=await fetch(`${API}/api/deliveries/${deliveryId}/upload-targets`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({assets:accepted.map(({file,kind})=>({kind,filename:file.name,content_type:contentType(file),size_bytes:file.size}))})});
      body=await response.json();if(!response.ok)throw new Error(apiError(body,"Could not create upload targets"));
      const targets:UploadTarget[]=body.targets;
      for(let index=0;index<targets.length;index++){
        const target=targets[index];const source=accepted.find(item=>item.file.name===target.asset.filename);
        if(!source)throw new Error(`Upload target mismatch for ${target.asset.filename}`);
        setUploadStage(`Uploading ${index+1}/${targets.length}: ${source.file.name}`);
        const uploadResponse=await fetch(absolute(target.upload_url),{method:"PUT",headers:target.required_headers,body:source.file});
        if(!uploadResponse.ok){const uploadBody=await uploadResponse.json().catch(()=>null);throw new Error(apiError(uploadBody,`Upload failed for ${source.file.name}`))}
      }
      setUploadStage("Reconciling delivery…");
      response=await fetch(`${API}/api/deliveries/${deliveryId}/ingestions`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({idempotency_key:`browser-${crypto.randomUUID()}`})});
      body=await response.json();if(!response.ok)throw new Error(apiError(body,"Could not start ingestion"));
      let job=body;
      for(let attempt=0;attempt<60&&job.status!=="complete";attempt++){
        if(job.status==="failed")throw new Error(job.error||"Ingestion failed");
        await new Promise(resolve=>window.setTimeout(resolve,500));
        const jobResponse=await fetch(`${API}/api/ingestions/${job.job_id}`);job=await jobResponse.json();
        setUploadStage(`${job.stage.replaceAll("_"," ")} · ${job.progress}%`);
      }
      if(job.status!=="complete"||!job.run_id)throw new Error("Ingestion timed out");
      const runResponse=await fetch(`${API}/api/handoff/runs/${job.run_id}`);const uploadedRun=await runResponse.json();if(!runResponse.ok)throw new Error(apiError(uploadedRun,"Run unavailable"));
      setRun(uploadedRun);setSelectedTake(0);setUploadStage("Upload reconciled successfully");document.getElementById("reconciliation")?.scrollIntoView({behavior:"smooth"});
    }catch(reason){setError(reason instanceof Error?reason.message:"Upload failed");setUploadStage("")}finally{setBusy("")}
  };

  const unresolved=useMemo(()=>run?.findings.filter(item=>!item.decision).length||0,[run]);
  const recovered=useMemo(()=>run?.findings.filter(item=>item.decision==="recovered").length||0,[run]);
  const evidence=run?.checks[Math.min(selectedTake,Math.max(0,(run?.checks.length||1)-1))];

  return <div className="shell">
    <nav className="floating-nav" aria-label="Primary navigation"><a className="brand" href="#top" aria-label="WrapCheck home"><i>W</i><div><b>WrapCheck</b><small>Media handoff gate</small></div></a><div className="nav-links"><a href="#evidence">Evidence</a><a href="#reconciliation">Reconciliation</a><a href="#recovery">Recovery</a></div><div className="nav-actions"><span className={"mode "+config?.mode}>{config?.mode==="live"?"Live agent":"Original demo media"}</span><button onClick={runProblem}>Run check <span>↗</span></button></div></nav>

    <header className="cinematic-hero" id="top"><div className="ambient ambient-one"/><div className="ambient ambient-two"/><div className="hero-copy"><div className="announcement"><span>Real delivery</span><b>Original camera + production sound</b><i>›</i></div><p className="eyebrow">Before anyone erases a source card</p><h1>Every take. Every file.<br/><em>Accounted for.</em></h1><p className="hero-lede">WrapCheck reconciles camera, sound, script and two-destination checksum records—then tells the DIT exactly what is missing before media leaves set.</p><div className="hero-actions"><button className="primary" onClick={runProblem}>{busy==="run"?"Reconciling…":"Load problem delivery"} <span>↗</span></button><a href={`${API}/api/demo-packages/problem`}><i>↓</i> Download sample delivery</a><button className="quiet-action" onClick={runRecovered}>Load recovered delivery</button></div></div><div className="halo-scene" aria-hidden="true"><div className="halo-glow"/><div className="planet"/></div>
      <section className={"release-preview "+(run?.status||"idle")} aria-label="Current media release status"><div className="preview-top"><div><span className="preview-mark">W</span><b>Delivery control</b></div><nav><span>Overview</span><span>Evidence</span><span>Recovery</span></nav><em><i/> Deterministic gate</em></div><div className="preview-content"><div className="preview-title"><small>The Last Signal · Day 12</small><h2>{run?statusLabel[run.status]:"Checking delivery…"}</h2><p>{run?.status_reason||"Loading camera, sound, script and checksum records."}</p></div><div className="preview-metrics"><div><small>Reported takes</small><b>{run?.checks.length||"—"}</b></div><div><small>Blocking issues</small><b>{unresolved}</b></div><div><small>Protected card</small><b>{run?.camera_cards[0]||"—"}</b></div><div className="gate"><small>Gate state</small><State value={run?.status||"checking"}/></div></div></div></section>
    </header>

    <main className="dashboard" id="dashboard">
      <section className="dashboard-intro"><div><span className="eyebrow">Operational workspace</span><h2>One delivery truth, grounded in production records.</h2></div><div className="scenario-control"><label htmlFor="scenario">Demo scenario</label><select id="scenario" value={scenario} onChange={event=>setScenario(event.target.value)}>{config?.scenarios.map(item=><option value={item.scenario_id} key={item.scenario_id}>{item.label}</option>)}</select><button onClick={()=>runGate()} disabled={!config||busy==="run"}>{busy==="run"?"Reconciling records…":"Run media handoff check"} <span>↗</span></button></div></section>
      <section className="upload-panel"><div><b>Use your own unpacked delivery</b><p>Select the four reports plus MP4/MOV and WAV files. Files are validated, hashed and reconciled through the real ingestion API.</p></div><label className={busy==="upload"?"disabled":""}>Choose delivery files<input type="file" multiple disabled={busy==="upload"} onChange={event=>{const files=Array.from(event.target.files||[]);if(files.length)void uploadDelivery(files)}}/></label>{uploadStage&&<span>{uploadStage}</span>}</section>
      <section className="how"><Step number="01" title="Reports define the expected set">Camera, sound and script logs say which take files should exist.</Step><Step number="02" title="Two copies prove delivery">Matching hashes on primary and secondary destinations establish safe backup.</Step><Step number="03" title="A person releases the cards">WrapCheck identifies gaps; a named DIT controls the final decision.</Step></section>
      {error&&<div className="error" role="alert">{error}</div>}{run&&<div className="truth"><b>{run.mode==="live"?"Live evidence path":"Honest demo mode"}</b><span>{run.mode_disclaimer}</span></div>}

      <section className="sources glass-panel" id="evidence"><header><div><small>01 · Evidence package</small><h2>Four records. One delivery truth.</h2></div><span>{run?.source_documents.reduce((total,item)=>total+item.record_count,0)||0} records loaded</span></header><div className="docgrid">{run?.source_documents.map(doc=><a key={doc.document_id} href={absolute(doc.download_url)} target="_blank"><i>{doc.kind==="camera_report"?"CAM":doc.kind==="sound_report"?"SND":doc.kind==="script_notes"?"SCR":"SHA"}</i><div><b>{doc.label}</b><small>{doc.filename}</small></div><em>{doc.record_count} rows ↗</em></a>)}</div></section>

      <section className="matrix glass-panel" id="reconciliation"><header><div><small>02 · Reconciliation matrix</small><h2>Every reported take, matched to two backups.</h2></div><div className="legend"><State value="present"/><State value="missing"/><State value="verified"/></div></header><div className="tablewrap"><table><thead><tr><th>Scene / take</th><th>Editorial note</th><th>Camera file</th><th>Sound file</th><th>Backup proof</th></tr></thead><tbody>{run?.checks.map((check,index)=><tr key={check.scene_take} className={(check.circled?"circled ":"")+(selectedTake===index?"selected":"")} onClick={()=>setSelectedTake(index)}><td><b>{check.scene_take}</b>{check.circled&&<em>○ circled</em>}</td><td>{check.script_note}</td><td><span>{check.video_filename}</span><State value={check.video_state}/><small>{check.verified_video_copies}/2 verified copies</small></td><td><span>{check.audio_filename}</span><State value={check.audio_state}/><small>{check.verified_audio_copies}/2 verified copies</small></td><td><b>{checksumLabel(check.checksum_state)}</b><State value={check.checksum_state}/></td></tr>)}</tbody></table></div>
        {evidence&&<div className="media-evidence"><div className="evidence-copy"><small>Playable evidence · {evidence.scene_take}</small><h3>{evidence.video_filename}</h3><p>Select any take row to inspect the real source camera clip and its separate production WAV.</p><div><State value={evidence.video_state}/><span>{evidence.verified_video_copies}/2 camera copies</span><State value={evidence.audio_state}/><span>{evidence.verified_audio_copies}/2 sound copies</span></div></div><div className="players">{evidence.video_playback_url?<video key={evidence.video_playback_url} controls preload="metadata" src={absolute(evidence.video_playback_url)}/>:<div className="missing-player">Camera clip missing</div>}{evidence.audio_playback_url?<audio key={evidence.audio_playback_url} controls preload="metadata" src={absolute(evidence.audio_playback_url)}/>:<div className="missing-player">Production WAV missing for this take</div>}</div></div>}
      </section>

      <div className="workspace" id="recovery"><section className="issues glass-panel"><header><div><small>03 · Recovery queue</small><h2>{run?.findings.length?run.findings.length+" issues need an answer":"No delivery discrepancies"}</h2></div>{run&&<b className="count">{unresolved} unresolved</b>}</header>{run?.findings.map((finding,index)=><article key={finding.finding_id}><div className="issuehead"><i>{String(index+1).padStart(2,"0")}</i><div><span>{finding.issue_type.replaceAll("_"," ")} · {finding.card_id}</span><h3>{finding.title}</h3><p>{finding.scene_take}</p></div><State value={finding.decision||"blocking"}/></div><div className="compare"><div><small>Expected</small><p>{finding.expected}</p></div><div><small>Found</small><p>{finding.observed}</p></div></div><div className="action"><small>Exact recovery action</small><b>{finding.required_action}</b></div><ul>{finding.evidence.map(item=><li key={item}>{item}</li>)}</ul><div className="actions"><button className={finding.decision==="recovered"?"active":""} disabled={busy===finding.finding_id||!!run.released_by} onClick={()=>decide(finding.finding_id,"recovered")}>✓ Mark recovered</button><button className={finding.decision==="approved_exception"?"active amber":""} disabled={busy===finding.finding_id||!!run.released_by} onClick={()=>decide(finding.finding_id,"approved_exception")}>Approve exception</button><button className={finding.decision==="needs_review"?"active red":""} disabled={busy===finding.finding_id||!!run.released_by} onClick={()=>decide(finding.finding_id,"needs_review")}>Escalate</button></div></article>)}{run&&run.findings.length===0&&<div className="allclear"><i>✓</i><h3>All reported takes are accounted for.</h3><p>Camera, production sound and two verified backup copies reconcile. A DIT still controls final release.</p></div>}</section>
        <aside className="release"><div className="release-orbit"/><small>Human-controlled release</small><h2>{run?statusLabel[run.status]:"Awaiting verification"}</h2><p>{run?.status_reason}</p><dl><div><dt>Reported takes</dt><dd>{run?.checks.length||0}</dd></div><div><dt>Unresolved</dt><dd>{unresolved}</dd></div><div><dt>Recovered</dt><dd>{recovered}</dd></div></dl><label>DIT / data manager<input value={reviewer} onChange={event=>setReviewer(event.target.value)}/></label><button className="releasebtn" disabled={run?.status!=="ready_for_release"||busy==="release"} onClick={release}>{run?.status==="released_by_dit"?"Delivery released":"Release cards and delivery"} <span>↗</span></button>{run&&<a className="report" href={`${API}/api/handoff/runs/${run.run_id}/report`} target="_blank">Open editorial release report ↗</a>}<details><summary>60-second live demo <span>+</span></summary><ol><li>Play circled Take 7 camera evidence.</li><li>Show its separate production WAV is missing.</li><li>Show A017 has only one verified copy.</li><li>Mark both items recovered.</li><li>Release as the DIT and open the report.</li></ol></details>{run&&<details><summary>Real agent and SQL trace <span>+</span></summary>{run.audit.map(item=><div className="audit" key={item.step}><i className={item.status}/><div><b>{item.step.replaceAll("_"," ")}</b><small>{item.service} · {item.duration_ms} ms</small><p>{item.summary}</p>{item.query&&<pre>{item.query}</pre>}</div></div>)}</details>}</aside>
      </div>
      <footer><a className="brand footer-brand" href="#top"><i>W</i><div><b>WrapCheck</b><small>Every take. Every file. Accounted for.</small></div></a><p>Human decisions remain authoritative. Never erase source media from an AI recommendation.</p><a href={`${API}/api/demo-packages/problem`}>Download demo delivery ↗</a></footer>
    </main>
  </div>;
}
