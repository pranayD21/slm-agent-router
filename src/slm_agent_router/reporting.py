from __future__ import annotations

import html
import json
from pathlib import Path

from .metrics import summarize

STYLE = '\nbody{margin:0;background:#f8fafc;color:#111827;font:14px/1.5 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}\nmain{max-width:1180px;margin:0 auto;padding:24px}\nheader{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;border-bottom:1px solid #cbd5e1;padding-bottom:14px;margin-bottom:18px}\nh1{font-size:24px;line-height:1.2;margin:0 0 6px}\nh2{font-size:17px;margin:24px 0 10px}\n.muted{color:#475569}\n.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}\n.card{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:12px}\n.metric{font-size:22px;font-weight:700;color:#0f172a}\ntable{width:100%;border-collapse:collapse;background:#fff;border:1px solid #cbd5e1;border-radius:8px;overflow:hidden}\nth,td{padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:left;vertical-align:top}\nth{background:#e2e8f0;font-size:12px;text-transform:uppercase;letter-spacing:.02em;color:#334155}\ntr:hover td{background:#f1f5f9}\ncode,pre{font-family:"SFMono-Regular",Consolas,monospace}\npre{white-space:pre-wrap;background:#0f172a;color:#e2e8f0;border-radius:8px;padding:12px;overflow:auto}\n.badge{display:inline-block;border-radius:999px;padding:2px 8px;font-size:12px;font-weight:600;border:1px solid #94a3b8;background:#f8fafc}\n.ok{color:#166534}.warn{color:#92400e}.bad{color:#991b1b}\n.split{display:grid;grid-template-columns:1fr 1fr;gap:12px}\nbutton,select{min-height:36px;border:1px solid #94a3b8;background:#fff;border-radius:6px;padding:6px 10px}\nbutton:focus,select:focus,a:focus{outline:3px solid #22c55e;outline-offset:2px}\n@media(max-width:760px){main{padding:14px}.split{grid-template-columns:1fr}header{display:block}}\n'


def esc(value) -> str:
    return html.escape(str(value))


def write_report(run_path: str | Path, output: str | Path) -> Path:
    rows_data = [json.loads(line) for line in Path(run_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    metrics = summarize(rows_data)
    cards = ''.join(f"<div class='card'><div class='muted'>{esc(k)}</div><div class='metric'>{esc(v)}</div></div>" for k, v in metrics.items())
    rows = ''.join(f"<tr><td>{esc(r['task_id'])}</td><td>{r['success']}</td><td>{r['handled_locally']}</td><td>{r['escalated']}</td><td>{esc(', '.join(r['escalation_reasons']))}</td></tr>" for r in rows_data)
    doc = f"<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>SLM Agent Router</title><style>{STYLE}</style><main><header><div><h1>Agent-step routing report</h1><p class='muted'>Local-first routing with confidence, schema, and tool-argument escalation.</p></div></header><section class='grid'>{cards}</section><h2>Steps</h2><table><thead><tr><th>Task</th><th>Success</th><th>Local</th><th>Escalated</th><th>Reasons</th></tr></thead><tbody>{rows}</tbody></table></main></html>"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(doc, encoding="utf-8")
    return output
