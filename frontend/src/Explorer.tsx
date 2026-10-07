import {useEffect, useState} from 'react';
import {request, query, Hit, Symbol, Reference, GraphData, GraphNode} from './api';

export function Explorer({repository, snapshot, hit}: {repository: string; snapshot: string; hit: Hit}) {
  const [file, setFile] = useState<{content: string; total_lines: number} | null>(null);
  const [symbols, setSymbols] = useState<Symbol[]>([]);
  const [references, setReferences] = useState<Reference[]>([]);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [error, setError] = useState('');
  const [line, setLine] = useState(hit.start_line);
  const [column, setColumn] = useState(0);
  const context = {repository_id: repository, snapshot_id: snapshot};

  useEffect(() => {
    // Ignore responses from an old selection after effect cleanup.
    // Source, symbols, and graph all use the same immutable snapshot.
    let active = true;
    setFile(null); setReferences([]); setError(''); setLine(hit.start_line);
    Promise.all([
      request<{content: string; total_lines: number}>(`/files?${query({...context, path: hit.path})}`),
      request<{symbols: Symbol[]}>(`/symbols?${query({...context, path: hit.path})}`),
      request<GraphData>(`/graph?${query({...context, path: hit.path, limit: 40})}`),
    ]).then(([file, symbols, graph]) => {if (active) {setFile(file); setSymbols(symbols.symbols); setGraph(graph);}})
      .catch(error => {if (active) setError(error.message);});
    return () => {active = false;};
  }, [repository, snapshot, hit.id]);

  async function lookup(symbolId?: string) {
    try {
      const result = await request<{definitions: Symbol[]; references: Reference[]}>(`/references?${query({...context, symbol_id: symbolId, path: symbolId ? undefined : hit.path, line, column})}`);
      setSymbols(result.definitions); setReferences(result.references); setError('');
    } catch (error) {setError(String(error));}
  }

  async function expand(node: GraphNode) {
    // External modules have no captured local source to expand.
    if (node.external) return;
    try {setGraph(await request(`/graph?${query({...context, path: node.path || undefined, symbol_id: node.symbol_id || undefined, limit: 40})}`));}
    catch (error) {setError(String(error));}
  }

  return <section className="explorer"><h2>{hit.path}</h2><p className="muted">Captured snapshot source · {file?.total_lines ?? 0} lines</p>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="position"><label>Line<input type="number" min="1" value={line} onChange={event => setLine(Number(event.target.value))}/></label>
      <label>UTF-8 byte column<input type="number" min="0" value={column} onChange={event => setColumn(Number(event.target.value))}/></label><button onClick={() => lookup()}>Find definition and references</button></div>
    <div className="code-view">{file?.content.split('\n').map((text, index) => <div key={index} className={index + 1 >= hit.start_line && index + 1 <= hit.end_line ? 'highlight' : ''}><button className="line-number" onClick={() => setLine(index + 1)}>{index + 1}</button><code>{text || ' '}</code></div>)}</div>
    <div className="columns"><div><h3>Definitions / symbols</h3>{symbols.map(symbol => <button className="text-button" key={symbol.id} onClick={() => lookup(symbol.id)}>{symbol.qualified_name} · {symbol.path}:{symbol.start_line}</button>)}
      <h3>References</h3>{!references.length && <p className="muted">Select a symbol or source position.</p>}{references.map((reference, index) => <p key={index}>{reference.path}:{reference.start_line} · <strong>{reference.status}</strong></p>)}</div>
      <div><h3>Dependency graph</h3>{graph && <DependencyGraph graph={graph} expand={expand}/>}</div></div>
  </section>;
}

function DependencyGraph({graph, expand}: {graph: GraphData; expand: (node: GraphNode) => void}) {
  const positions = new Map(graph.nodes.map((node, index) => [node.id, {x: 210 + 160 * Math.cos(index * 2 * Math.PI / Math.max(1, graph.nodes.length)), y: 160 + 110 * Math.sin(index * 2 * Math.PI / Math.max(1, graph.nodes.length))}]));
  return <><svg viewBox="0 0 420 320" aria-label="Dependency graph" role="img">
    {graph.edges.map((edge, index) => {const source = positions.get(edge.source)!; const target = positions.get(edge.target)!; return <line key={index} x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke={edge.status === 'resolved' ? '#76dab8' : '#68758a'}><title>{edge.kind} · {edge.status}</title></line>;})}
    {graph.nodes.map(node => {const position = positions.get(node.id)!; return <g key={node.id}><circle cx={position.x} cy={position.y} r="8" fill={node.external ? '#68758a' : '#76dab8'}/><text x={position.x} y={position.y - 14} textAnchor="middle" fill="#e3eaf3" fontSize="9">{node.label.slice(-24)}</text></g>;})}
  </svg><p className="muted">Select a node to expand its one-hop neighbors.</p>{graph.nodes.map(node => <button className="text-button" disabled={node.external} key={node.id} onClick={() => expand(node)}>{node.label}{node.external ? ' (external)' : ''}</button>)}
    {graph.truncated && <p>Showing the first 40 edges.</p>}</>;
}
