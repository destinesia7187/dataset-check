const sourcePoints = [
  [37, 64], [67, 85], [106, 58], [143, 79], [47, 119], [90, 109],
  [127, 122], [158, 107], [33, 157], [72, 148], [111, 165], [151, 151],
  [54, 193], [98, 204], [138, 190],
];

const findingRows = [64, 88, 112, 136, 160];
const findingColumns = [390, 413, 436, 459, 482, 505];

export default function WorkspaceHero() {
  return <>
    <section className="workspace-hero">
      <div className="hero-copy">
        <div className="eyebrow">DATA QUALITY / FIELD WORKSPACE</div>
        <h1>Check your data before analysis</h1>
        <p>Find missing values, duplicates, and values that break your rules.</p>
        <div className="hero-caption"><span className="specimen-mark"/>Original values. Explicit rules. Traceable results.</div>
      </div>
      <div className="hero-plot">
        <svg viewBox="0 0 560 300" aria-hidden="true" focusable="false" fill="none">
          <path className="plot-guide" d="M24 43H532M24 226H532M184 43v183M354 43v183M269 43v183M24 134h508"/>
          <path className="hero-axis" d="M24 51v175h508M20 64h8m-8 48h8m-8 48h8m-8 48h8M47 222v8m48-8v8m48-8v8m48-8v8m48-8v8m48-8v8m48-8v8m48-8v8m48-8v8m48-8v8m48-8v8"/>

          <text className="plot-label" x="30" y="28">[ RAW RECORDS ]</text>
          <text className="plot-label" x="218" y="28">[ EXPLICIT RULES ]</text>
          <text className="plot-label" x="386" y="28">[ FINDINGS ]</text>

          <path className="plot-connector" d="M164 79c41 0 35 48 79 48M166 149c36 0 39-22 77-22M151 192c49 0 52-65 92-65M295 127c44 0 32-63 83-63M295 127c44 0 38-15 83-15M295 127c44 0 32 33 83 33"/>
          <path className="plot-connector" d="m235 123 8 4-8 4m135-71 8 4-8 4m0 40 8 4-8 4m0 40 8 4-8 4"/>

          {sourcePoints.map(([x, y], index) => <g key={`${x}-${y}`}>
            <circle className={index === 2 || index === 7 || index === 10 ? 'plot-point plot-highlight' : 'plot-point'} cx={x} cy={y} r={index === 2 || index === 7 ? 4 : 3}/>
            {index === 2 || index === 10 ? <path className="plot-guide" d={`M${x - 9} ${y}h-5m14-9v-5m9 14h5m-14 9v5`}/> : null}
          </g>)}

          <g className="plot-checkpoint">
            <rect className="plot-point" x="243" y="101" width="52" height="52" rx="2"/>
            <circle className="plot-point" cx="269" cy="127" r="16"/>
            <path className="plot-highlight" d="m261 127 5 5 11-12" fill="none"/>
            <path className="hero-axis" d="M269 95v6m0 52v6m-32-32h6m52 0h6"/>
          </g>

          {findingRows.map((y, row) => <g key={y}>
            <path className="hero-axis" d={`M376 ${y - 6}h-4v12h4M519 ${y - 6}h4v12h-4`}/>
            {findingColumns.map((x, column) => <rect className={row === 1 && column === 3 || row === 3 && column === 1 || row === 4 && column === 4 ? 'plot-point plot-highlight' : 'plot-point'} key={x} x={x} y={y - 3} width="6" height="6" rx="1"/>)}
          </g>)}

          <path className="plot-guide" d="M269 177v25h65M41 250h129m25 0h76"/>
          <circle className="plot-point" cx="269" cy="177" r="2"/>
          <text className="plot-stamp" x="41" y="272">OBSERVE / VALIDATE / TRACE</text>
        </svg>
      </div>
      <div className="hero-specimen">
        <span className="axis-label">[ LOCAL BY DESIGN ]</span>
        <p>Your data stays on your computer.</p>
        <span className="specimen-meta">CSV / NO SIGN-IN REQUIRED</span>
      </div>
    </section>
    <div className="workflow-strip">
      <div className="workflow-step"><span>01</span><strong>Import your CSV</strong><small>Preserve every value</small></div>
      <div className="workflow-step"><span>02</span><strong>Define the rules</strong><small>Make expectations explicit</small></div>
      <div className="workflow-step"><span>03</span><strong>Inspect the findings</strong><small>Export a traceable report</small></div>
    </div>
  </>;
}
