import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {request, post, Repository, Snapshot, Task, Hit} from './api';
import {Explorer} from './Explorer';
import {Answers} from './Answers';
import {Reports} from './Reports';
import './style.css';

function App() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [repository, setRepository] = useState('');
  const repositoryRef = useRef(repository);
  repositoryRef.current = repository;
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [snapshot, setSnapshot] = useState('');
  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;
  const [kind, setKind] = useState('github');
  const [source, setSource] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [task, setTask] = useState<Task | null>(null);
  const [search, setSearch] = useState('');
  const [strategy, setStrategy] = useState('ast-aware');
  const [pathPrefix, setPathPrefix] = useState('');
  const [language, setLanguage] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [selected, setSelected] = useState<Hit | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const refresh = () => request<Repository[]>('/repositories').then(setRepositories);
  const refreshSnapshots = (id: string) => request<Snapshot[]>(`/repositories/${id}/snapshots`).then(items => {
    if (repositoryRef.current !== id) return;
    setSnapshots(items); setSnapshot(items.find(item => item.status === 'ready')?.id || '');
    setHits([]); setSelected(null);
  });
  useEffect(() => {refresh().catch(error => setError(error.message));}, []);
  useEffect(() => {
    setSnapshots([]); setSnapshot(''); setHits([]); setSelected(null);
    if (repository) refreshSnapshots(repository).catch(error => setError(error.message));
  }, [repository]);
  useEffect(() => {
    if (!task || !['queued', 'running'].includes(task.status)) return;
    const timer = setInterval(() => {
      request<Task>(`/tasks/${task.id}`).then(next => {
        setTask(next);
        if (next.status === 'completed' && next.repository_id === repository) refreshSnapshots(repository).catch(error => setError(error.message));
      }).catch(error => {setError(error.message); clearInterval(timer);});
    }, 1000);
    return () => clearInterval(timer);
  }, [task?.id, task?.status, repository]);

  async function importRepository(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {const imported = await post<Repository>('/repositories', {kind, source}); await refresh(); setRepository(imported.id); setSource('');}
    catch (error) {setError(String(error));} finally {setBusy(false);}
  }
  async function index() {
    setError('');
    try {setTask(await post(`/repositories/${repository}/index`, {exclusions: []}));}
    catch (error) {setError(String(error));}
  }
  async function runSearch(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setSelected(null);
    try {const result = await post<{repository_id: string; snapshot_id: string; results: Hit[]; latency_ms: number}>('/search', {repository_id: repository, snapshot_id: snapshot, query: search, strategy, k: 20, language: language || null, path_prefix: pathPrefix || null}); if (result.repository_id === repositoryRef.current && result.snapshot_id === snapshotRef.current) {setHits(result.results); setLatency(result.latency_ms);}}
    catch (error) {setError(String(error));} finally {setBusy(false);}
  }
  const current = snapshots.find(item => item.id === snapshot);
  return <main><header><span className="eyebrow">LOCAL REPOSITORY INTELLIGENCE</span><h1>repoMap</h1><p>Find the implementation. Follow the connections.</p></header>
    {error && <p role="alert" className="error">{error}</p>}
    <section><h2>Repositories</h2><form onSubmit={importRepository} className="columns">
      <label>Source type<select value={kind} onChange={event => setKind(event.target.value)}><option value="github">Public GitHub</option><option value="local">Local Git directory</option></select></label>
      <label>Repository URL or absolute path<input required value={source} onChange={event => setSource(event.target.value)}/></label><button disabled={busy}>Import repository</button>
    </form><hr/><div className="columns"><label>Active repository<select value={repository} onChange={event => setRepository(event.target.value)}><option value="">Select a repository</option>{repositories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Published snapshot<select value={snapshot} onChange={event => {setSnapshot(event.target.value); setSelected(null); setHits([]);}}><option value="">No snapshot selected</option>{snapshots.filter(item => item.status === 'ready').map(item => <option key={item.id} value={item.id}>{item.id.slice(0, 8)} · {item.commit_sha.slice(0, 8)}</option>)}</select></label>
      <button onClick={index} disabled={!repository || !!task && ['queued', 'running'].includes(task.status)}>Index repository</button></div>
      {task && <div role="status"><p>Index task: {task.status} · {Math.round(task.progress * 100)}%</p><progress value={task.progress} max="1"/>{task.error && <p className="error">{task.error}</p>}</div>}
      {current && <details><summary>{current.metrics.files} files · {current.metrics.chunks ?? 0} chunks · {current.metrics.total_seconds?.toFixed(2)} seconds</summary><p>{current.metrics.skipped.length} files skipped</p>{current.metrics.skipped.slice(0, 30).map(item => <p key={item.path}>{item.path}: {item.reason}</p>)}</details>}
    </section>
    <section><h2>Search code</h2><form onSubmit={runSearch}><label>Query<input required value={search} onChange={event => setSearch(event.target.value)} placeholder="Where is authentication implemented?"/></label>
      <div className="columns"><label>Strategy<select value={strategy} onChange={event => setStrategy(event.target.value)}>{['vector-only', 'bm25', 'hybrid', 'ast-aware'].map(item => <option key={item}>{item}</option>)}</select></label>
        <label>Language<select value={language} onChange={event => setLanguage(event.target.value)}>{['', 'python', 'javascript', 'typescript', 'tsx', 'text'].map(item => <option value={item} key={item}>{item || 'All languages'}</option>)}</select></label>
        <label>Path prefix<input value={pathPrefix} onChange={event => setPathPrefix(event.target.value)} placeholder="src/"/></label></div>
      <button disabled={busy || !snapshot}>{busy ? 'Working...' : 'Search'}</button></form>
      {latency !== null && <p className="muted">{hits.length} results · {latency.toFixed(1)} ms</p>}
      {hits.map(hit => <article key={hit.id}><button className="text-button" onClick={() => setSelected(hit)}>{hit.symbol || hit.path}</button><p>{hit.path}:{hit.start_line}-{hit.end_line} · {hit.score.toFixed(5)} · {hit.origins.join(', ')}</p><pre>{hit.excerpt.slice(0, 500)}</pre></article>)}
    </section>
    {snapshot && <Answers key={snapshot} repository={repository} snapshot={snapshot} onOpen={setSelected}/>}
    {selected && <Explorer key={selected.id} repository={repository} snapshot={snapshot} hit={selected}/>}
    <Reports/>
  </main>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/> </React.StrictMode>);
