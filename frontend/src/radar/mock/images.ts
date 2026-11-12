// Sample-mode images: small inline SVG figures (no network), used inside the fixture articles.

/** Encode an SVG string as a data URI usable in <img src>. */
function svgUri(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

/** A wide line chart: accuracy of three systems over eight releases. */
export const CHART_IMAGE = svgUri(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 420" font-family="Inter, sans-serif">
<rect width="960" height="420" fill="#f4f5f2"/>
<g stroke="#d7d8d3" stroke-width="1">
<line x1="80" y1="60" x2="920" y2="60"/><line x1="80" y1="140" x2="920" y2="140"/>
<line x1="80" y1="220" x2="920" y2="220"/><line x1="80" y1="300" x2="920" y2="300"/>
<line x1="80" y1="370" x2="920" y2="370" stroke="#9a9c96"/></g>
<g font-size="15" fill="#6b6e68"><text x="30" y="65">90%</text><text x="30" y="145">80%</text>
<text x="30" y="225">70%</text><text x="30" y="305">60%</text>
<text x="80" y="400">v1</text><text x="900" y="400">v8</text></g>
<polyline fill="none" stroke="#2a4bb3" stroke-width="4" points="80,300 200,270 320,250 440,200 560,170 680,130 800,100 920,80"/>
<polyline fill="none" stroke="#8a8f99" stroke-width="3" points="80,320 200,300 320,290 440,265 560,250 680,232 800,220 920,205"/>
<polyline fill="none" stroke="#b9bcc2" stroke-width="3" stroke-dasharray="8 7" points="80,340 200,335 320,322 440,318 560,306 680,300 800,292 920,288"/>
<g font-size="16"><text x="700" y="118" fill="#2a4bb3">New model</text><text x="700" y="248" fill="#6b6e68">Previous</text>
<text x="700" y="320" fill="#8a8d88">Baseline</text></g></svg>`)

/** A simple block diagram: capture, detect, review, report. */
export const DIAGRAM_IMAGE = svgUri(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 260" font-family="Inter, sans-serif">
<rect width="960" height="260" fill="#f4f5f2"/>
<g fill="#ffffff" stroke="#9a9c96" stroke-width="1.5">
<rect x="40" y="90" width="170" height="80" rx="8"/><rect x="280" y="90" width="170" height="80" rx="8"/>
<rect x="520" y="90" width="170" height="80" rx="8" stroke="#2a4bb3" stroke-width="2.5"/><rect x="760" y="90" width="170" height="80" rx="8"/></g>
<g stroke="#6b6e68" stroke-width="2" marker-end="url(#a)"><line x1="212" y1="130" x2="274" y2="130"/>
<line x1="452" y1="130" x2="514" y2="130"/><line x1="692" y1="130" x2="754" y2="130"/></g>
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
<path d="M0 0L10 5L0 10z" fill="#6b6e68"/></marker></defs>
<g font-size="18" fill="#1b1d21" text-anchor="middle"><text x="125" y="136">Video frames</text>
<text x="365" y="136">Detection</text><text x="605" y="136" fill="#2a4bb3">Clinician review</text>
<text x="845" y="136">Report</text></g></svg>`)

/** A dark 16:9 poster used as the sample video frame. */
export const VIDEO_POSTER_HTML = `data:text/html;charset=utf-8,${encodeURIComponent(
  '<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#1b1d21;color:#d0cec7;font:16px Inter,system-ui,sans-serif">' +
    '<div style="text-align:center"><div style="width:64px;height:64px;margin:0 auto 16px;border-radius:50%;border:2px solid #9fb3f3;display:grid;place-items:center">' +
    '<div style="width:0;height:0;border-left:18px solid #9fb3f3;border-top:11px solid transparent;border-bottom:11px solid transparent;margin-left:5px"></div></div>' +
    'Sample video player</div></body></html>',
)}`

/** A placeholder page standing in for the PDF viewer in sample mode. */
export const PDF_PLACEHOLDER_HTML = `data:text/html;charset=utf-8,${encodeURIComponent(
  '<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#e9e9e6;color:#4a4d55;font:15px Inter,system-ui,sans-serif">' +
    '<div style="background:#fff;width:70%;height:80%;padding:48px;box-sizing:border-box;box-shadow:0 1px 3px rgba(0,0,0,.12)">' +
    '<div style="height:18px;width:60%;background:#d9dad6;margin-bottom:24px"></div>' +
    '<div style="height:10px;background:#ecedea;margin-bottom:10px"></div><div style="height:10px;background:#ecedea;margin-bottom:10px"></div>' +
    '<div style="height:10px;width:80%;background:#ecedea;margin-bottom:32px"></div>' +
    '<p>The paper\'s PDF opens here. Sample mode has no PDF to show.</p></div></body></html>',
)}`
