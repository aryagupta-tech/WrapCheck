from html import escape

from .models import ReviewSnapshot, WrapRun


DECISION_LABELS = {
    "confirmed_error": "Confirmed error",
    "intentional_change": "Intentional change",
    "needs_review": "Needs review",
    None: "Unreviewed",
}


def render_text_report(snapshot: ReviewSnapshot) -> str:
    lines = [
        "WRAPCHECK CONTINUITY REPORT",
        f"Production: {snapshot.production.title}",
        f"Scene: {snapshot.production.scene_heading}",
        f"Recommendation: {snapshot.recommendation.replace('_', ' ').upper()}",
        "",
        "PICKUP CHECKLIST",
    ]
    for conflict in snapshot.conflicts:
        lines.append(
            f"- [{conflict.decision or 'unreviewed'}] {conflict.entity_name} / {conflict.attribute}: "
            f"{conflict.reference_value} -> {conflict.current_value}"
        )
    lines += [
        "",
        "EDITOR HANDOFF",
        snapshot.recommendation_reason,
        "",
        "Mode: Demo fixtures; no live Gemini or MCP calls.",
    ]
    return "\n".join(lines)


def render_html_report(snapshot: ReviewSnapshot) -> str:
    recommendation = snapshot.recommendation
    status_label = recommendation.replace("_", " ").title()
    blocking = sum(
        1
        for conflict in snapshot.conflicts
        if conflict.severity == "blocking" and conflict.decision != "intentional_change"
    )
    reviewed = sum(conflict.decision is not None for conflict in snapshot.conflicts)
    rows = []
    for index, conflict in enumerate(snapshot.conflicts, start=1):
        decision = conflict.decision.value if conflict.decision else None
        rows.append(
            f"""
            <article class="item">
              <div class="item-number">{index:02}</div>
              <div class="item-content">
                <div class="item-topline">
                  <div>
                    <span class="severity {escape(conflict.severity)}">{escape(conflict.severity)}</span>
                    <span class="category">{escape(conflict.entity_type)}</span>
                    <h2>{escape(conflict.entity_name)} <small>/ {escape(conflict.attribute.replace('_', ' '))}</small></h2>
                  </div>
                  <div class="confidence">{round(conflict.confidence * 100)}%<small>confidence</small></div>
                </div>
                <div class="comparison">
                  <div>
                    <label>Reference</label>
                    <strong>{escape(conflict.reference_value)}</strong>
                    <p>{escape(conflict.reference_evidence)}</p>
                  </div>
                  <div class="arrow">→</div>
                  <div>
                    <label>Current take</label>
                    <strong>{escape(conflict.current_value)}</strong>
                    <p>{escape(conflict.current_evidence)}</p>
                  </div>
                </div>
                <div class="decision {escape(decision or 'unreviewed')}">
                  <span>Human decision</span>{escape(DECISION_LABELS[decision])}
                </div>
              </div>
            </article>"""
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Continuity report · {escape(snapshot.production.title)}</title>
  <style>
    :root {{ --bg:#090b0d; --panel:#111519; --line:#293036; --ink:#eef1ed; --muted:#89949a;
      --cyan:#67d8ce; --amber:#e8a94b; --red:#ed735f; --green:#76bd8a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 Arial,sans-serif; }}
    .page {{ max-width:1120px; margin:auto; padding:42px 28px 72px; }}
    .toolbar {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:28px; }}
    .brand {{ display:flex; gap:12px; align-items:center; letter-spacing:.16em; font-weight:800; }}
    .mark {{ display:grid; place-items:center; width:35px; height:35px; background:var(--cyan); color:#07100f; }}
    .toolbar nav {{ display:flex; gap:8px; }}
    .toolbar a,.toolbar button {{ border:1px solid #3a4248; background:#14191c; color:var(--ink); padding:9px 13px;
      text-decoration:none; cursor:pointer; font:700 10px Arial; letter-spacing:.08em; text-transform:uppercase; }}
    .toolbar a.primary {{ background:var(--cyan); color:#06100f; border-color:var(--cyan); }}
    .hero {{ border:1px solid var(--line); border-top:3px solid var(--amber); background:var(--panel); padding:30px; }}
    .eyebrow,label {{ color:var(--muted); font-size:9px; letter-spacing:.15em; text-transform:uppercase; }}
    h1 {{ font:400 39px Georgia,serif; margin:8px 0 5px; }}
    .scene {{ color:#aeb6b7; margin:0; }}
    .status-row {{ display:grid; grid-template-columns:2fr 1fr 1fr 1fr; gap:1px; background:var(--line); margin-top:28px; }}
    .metric {{ background:#0d1113; padding:17px; }} .metric strong {{ display:block; font-size:20px; margin-top:5px; }}
    .metric.status strong {{ color:var(--amber); text-transform:uppercase; letter-spacing:.05em; }}
    .metric.status.safe_to_wrap strong {{ color:var(--green); }} .metric.status.do_not_wrap strong {{ color:var(--red); }}
    .summary {{ display:grid; grid-template-columns:1fr 310px; gap:16px; margin:17px 0 30px; }}
    .summary > div {{ padding:18px 20px; border:1px solid var(--line); background:#0e1215; }}
    .summary p {{ margin:7px 0 0; color:#bcc3c3; }}
    .section-title {{ display:flex; align-items:end; justify-content:space-between; border-bottom:1px solid var(--line); padding-bottom:12px; }}
    .section-title h2 {{ margin:5px 0 0; font:400 25px Georgia,serif; }} .section-title b {{ color:var(--cyan); }}
    .item {{ display:grid; grid-template-columns:54px 1fr; border:1px solid var(--line); border-top:0; background:var(--panel); }}
    .item-number {{ padding:21px 14px; color:#596269; font:12px monospace; border-right:1px solid var(--line); }}
    .item-content {{ padding:20px; }} .item-topline {{ display:flex; justify-content:space-between; gap:20px; }}
    .severity,.category {{ display:inline-block; text-transform:uppercase; font-size:8px; font-weight:800; letter-spacing:.13em; margin-right:9px; }}
    .severity {{ color:var(--red); }} .severity.review {{ color:var(--amber); }} .category {{ color:var(--muted); }}
    .item h2 {{ margin:7px 0 0; font-size:16px; }} .item h2 small {{ color:var(--muted); font-weight:400; }}
    .confidence {{ color:var(--amber); font:18px monospace; text-align:right; }} .confidence small {{ display:block; color:var(--muted); font:8px Arial; text-transform:uppercase; }}
    .comparison {{ display:grid; grid-template-columns:1fr 28px 1fr; align-items:center; margin:16px 0; }}
    .comparison > div:not(.arrow) {{ background:#0b0f11; border-left:2px solid #485158; padding:12px; min-height:96px; }}
    .comparison > div:last-child {{ border-color:var(--amber); }} .comparison strong {{ display:block; margin:5px 0; text-transform:capitalize; }}
    .comparison p {{ margin:0; color:#929c9f; font-size:11px; }} .arrow {{ text-align:center; color:#5c666b; }}
    .decision {{ display:inline-flex; gap:9px; border:1px solid #3b4348; padding:7px 10px; font-size:10px; text-transform:uppercase; font-weight:800; }}
    .decision span {{ color:var(--muted); font-weight:400; }} .decision.confirmed_error {{ color:var(--red); border-color:#63352e; }}
    .decision.intentional_change {{ color:var(--green); border-color:#31513a; }} .decision.needs_review,.decision.unreviewed {{ color:var(--amber); border-color:#604923; }}
    footer {{ display:flex; justify-content:space-between; gap:20px; margin-top:25px; padding-top:17px; border-top:1px solid var(--line); color:var(--muted); font-size:10px; }}
    @media(max-width:700px) {{ .page {{ padding:20px 12px; }} .toolbar {{ align-items:flex-start; gap:15px; }} .toolbar nav {{ flex-direction:column; }}
      h1 {{ font-size:30px; }} .status-row {{ grid-template-columns:1fr 1fr; }} .summary {{ grid-template-columns:1fr; }} .comparison {{ grid-template-columns:1fr; gap:6px; }} .arrow {{ transform:rotate(90deg); }} }}
    @media print {{ :root {{ --bg:#fff; --panel:#fff; --line:#c9ced0; --ink:#111; --muted:#555; }}
      body {{ background:#fff; }} .page {{ max-width:none; padding:0; }} .toolbar nav {{ display:none; }} .hero,.item,.summary>div {{ break-inside:avoid; }} }}
  </style>
</head>
<body>
  <main class="page">
    <header class="toolbar">
      <div class="brand"><span class="mark">W</span> WRAPCHECK <span class="eyebrow">Continuity report</span></div>
      <nav><button onclick="window.print()">Print / PDF</button><a class="primary" href="/api/report?format=txt">Download text</a></nav>
    </header>
    <section class="hero">
      <span class="eyebrow">Production continuity · Demo mode</span>
      <h1>{escape(snapshot.production.title)}</h1>
      <p class="scene">{escape(snapshot.production.scene_heading)}</p>
      <div class="status-row">
        <div class="metric status {escape(recommendation)}"><label>Wrap recommendation</label><strong>{escape(status_label)}</strong></div>
        <div class="metric"><label>Differences</label><strong>{len(snapshot.conflicts)}</strong></div>
        <div class="metric"><label>Reviewed</label><strong>{reviewed}/{len(snapshot.conflicts)}</strong></div>
        <div class="metric"><label>Blocking</label><strong>{blocking}</strong></div>
      </div>
    </section>
    <section class="summary">
      <div><span class="eyebrow">Editor handoff</span><p>{escape(snapshot.recommendation_reason)}</p></div>
      <div><span class="eyebrow">Script reference</span><p>{escape(snapshot.production.script_excerpt)}</p></div>
    </section>
    <section>
      <div class="section-title"><div><span class="eyebrow">Evidence review</span><h2>Pickup checklist</h2></div><b>{blocking} blocking</b></div>
      {''.join(rows)}
    </section>
    <footer><span>Generated by WrapCheck · Human decisions remain authoritative</span><span>Demo fixtures · No live Gemini or MCP calls</span></footer>
  </main>
</body>
</html>"""


def render_wrap_text_report(run: WrapRun) -> str:
    lines = [
        "WRAPCHECK SETUP RELEASE HANDOFF",
        f"Production: {run.brief.production_title}",
        f"Scene / setup: {run.brief.scene_heading} / {run.brief.setup_id}",
        f"Approved reference: {run.reference_asset.label}",
        f"Candidate: {run.candidate_asset.label}",
        f"Gate status: {run.status.value.replace('_', ' ').upper()}",
        f"Supervisor: {run.cleared_by or 'Not yet cleared'}",
        "",
        "PICKUP LIST",
    ]
    pickups = [item for item in run.findings if item.decision == "pickup"]
    if not pickups:
        lines.append("- No pickups have been added.")
    for item in pickups:
        lines += [
            f"- {item.label}: {item.recommended_action}",
            f"  Expected: {item.expected_value}",
            f"  Observed: {item.observed_value}",
            f"  Evidence: {item.candidate_evidence}",
        ]
    lines += ["", "RESOLVED EXCEPTIONS"]
    exceptions = [item for item in run.findings if item.decision == "intentional_change"]
    if not exceptions:
        lines.append("- None.")
    for item in exceptions:
        lines.append(f"- {item.label}: intentional change. {item.reviewer_note}".rstrip())
    lines += [
        "", "REQUIRED DIALOGUE", run.brief.required_dialogue, "",
        f"Evidence mode: {run.mode.upper()} — {run.mode_disclaimer}",
        "Human clearance remains authoritative.",
    ]
    return "\n".join(lines)


def render_wrap_html_report(run: WrapRun) -> str:
    status = run.status.value.replace("_", " ").title()
    findings = "".join(
        f"""<article><div><b>{escape(item.label)}</b><span>{escape(item.severity)}</span></div>
        <p><strong>Expected:</strong> {escape(item.expected_value)}<br>
        <strong>Observed:</strong> {escape(item.observed_value)}</p>
        <p>{escape(item.recommended_action)}</p>
        <small>Decision: {escape(item.decision.value if item.decision else "unreviewed")}</small></article>"""
        for item in run.findings
    ) or "<article><b>No actionable differences detected.</b></article>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Setup release handoff · {escape(run.brief.production_title)}</title>
    <style>
    :root{{--ink:#18201e;--muted:#66716e;--line:#d9dfdc;--accent:#107c6d;--hold:#a63d2f}}
    *{{box-sizing:border-box}}body{{margin:0;background:#f5f6f3;color:var(--ink);font:14px/1.55 Arial,sans-serif}}
    main{{max-width:920px;margin:40px auto;padding:34px;background:white;border:1px solid var(--line)}}
    header{{display:flex;justify-content:space-between;gap:24px;border-bottom:3px solid var(--accent);padding-bottom:24px}}
    h1{{font:36px Georgia,serif;margin:4px 0}}.eyebrow,small{{color:var(--muted);font-size:10px;letter-spacing:.1em;text-transform:uppercase}}
    .status{{text-align:right}}.status b{{display:block;color:var(--hold);font-size:18px;margin-top:5px}}
    .meta{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);margin:22px 0}}
    .meta div{{background:#fafbf9;padding:14px}}.meta b{{display:block;margin-top:4px}}
    article{{border:1px solid var(--line);padding:18px;margin-top:10px}}article>div{{display:flex;justify-content:space-between}}
    article span{{color:var(--hold);text-transform:uppercase;font-size:10px;font-weight:bold}}article p{{color:#45504d}}
    footer{{border-top:1px solid var(--line);margin-top:26px;padding-top:16px;color:var(--muted)}}
    @media print{{body{{background:white}}main{{margin:0;border:0;max-width:none}}}}
    </style></head><body><main>
    <header><div><span class="eyebrow">WrapCheck · setup release handoff</span>
    <h1>{escape(run.brief.production_title)}</h1><p>{escape(run.brief.scene_heading)} · {escape(run.brief.setup_id)}</p></div>
    <div class="status"><small>Gate status</small><b>{escape(status)}</b></div></header>
    <section class="meta"><div><small>Reference</small><b>{escape(run.reference_asset.label)}</b></div>
    <div><small>Candidate</small><b>{escape(run.candidate_asset.label)}</b></div>
    <div><small>Supervisor</small><b>{escape(run.cleared_by or "Not yet cleared")}</b></div></section>
    <h2>Pickup and exception record</h2>{findings}
    <footer>{escape(run.mode_disclaimer)} Human clearance remains authoritative.</footer>
    </main></body></html>"""
