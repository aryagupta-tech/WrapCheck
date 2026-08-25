from html import escape

from .handoff_models import HandoffRun


def render_handoff_text(run: HandoffRun) -> str:
    lines = [
        "WRAPCHECK MEDIA DELIVERY RELEASE",
        f"Production: {run.production}", f"Shoot day: {run.shoot_day}",
        f"Delivery: {run.delivery_name}", f"Cards: {', '.join(run.camera_cards)}",
        f"Status: {run.status.value.replace('_', ' ').upper()}",
        f"Released by: {run.released_by or 'Not released'}", "", "DISCREPANCIES",
    ]
    if not run.findings:
        lines.append("- No discrepancies found.")
    for item in run.findings:
        lines += [
            f"- {item.title} · {item.scene_take}", f"  Card: {item.card_id}",
            f"  Decision: {item.decision.value if item.decision else 'unresolved'}",
            f"  Action: {item.required_action}",
        ]
    lines += ["", "TAKE RECONCILIATION"]
    for item in run.checks:
        lines.append(f"- {item.scene_take}: video={item.video_state}; audio={item.audio_state}; checksum={item.checksum_state.value}")
    lines += ["", run.mode_disclaimer, "Source cards must only be erased after human DIT release."]
    return "\n".join(lines)


def render_handoff_html(run: HandoffRun) -> str:
    rows = "".join(
        f"<tr><td>{escape(item.scene_take)}</td><td>{escape(item.video_state)}</td><td>{escape(item.audio_state)}</td><td>{escape(item.checksum_state.value)}</td></tr>"
        for item in run.checks
    )
    issues = "".join(
        f"<article><b>{escape(item.title)}</b><span>{escape(item.scene_take)} · {escape(item.card_id)}</span><p>{escape(item.required_action)}</p><small>Decision: {escape(item.decision.value if item.decision else 'unresolved')}</small></article>"
        for item in run.findings
    ) or "<article><b>No discrepancies found.</b></article>"
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Media delivery release</title><style>
    body{{margin:0;background:#f2f4f1;color:#15201d;font:14px Arial}}main{{max-width:940px;margin:35px auto;background:white;padding:36px;border:1px solid #d8ded9}}header{{display:flex;justify-content:space-between;border-bottom:4px solid #176b5b;padding-bottom:20px}}h1{{margin:5px 0;font:36px Georgia}}small,span{{color:#66736f}}.status{{color:#a43b2c;font-size:19px;font-weight:bold;text-align:right}}article{{border:1px solid #d8ded9;padding:16px;margin:10px 0}}article b,article span{{display:block;margin-bottom:6px}}table{{width:100%;border-collapse:collapse;margin-top:20px}}th,td{{padding:11px;border-bottom:1px solid #d8ded9;text-align:left}}th{{font-size:10px;text-transform:uppercase;color:#66736f}}footer{{margin-top:25px;border-top:1px solid #d8ded9;padding-top:15px;color:#66736f}}@media print{{body{{background:white}}main{{border:0;margin:0;max-width:none}}}}</style></head><body><main>
    <header><div><small>WrapCheck · media delivery gate</small><h1>{escape(run.production)}</h1><span>{escape(run.shoot_day)} · {escape(run.delivery_name)}</span></div><div><small>Release status</small><div class='status'>{escape(run.status.value.replace('_',' ').title())}</div></div></header>
    <h2>Discrepancies and recovery record</h2>{issues}<h2>Take reconciliation</h2><table><thead><tr><th>Scene / take</th><th>Video</th><th>Audio</th><th>Checksum</th></tr></thead><tbody>{rows}</tbody></table>
    <footer>Released by: {escape(run.released_by or 'Not released')} · {escape(run.mode_disclaimer)}</footer></main></body></html>"""
