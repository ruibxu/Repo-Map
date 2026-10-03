import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Repository = { id: string; name: string; source: string; commit_sha: string };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, options);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Request failed.');
  return body;
}

function App() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [kind, setKind] = useState('github');
  const [source, setSource] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const refresh = () => request<Repository[]>('/repositories').then(setRepositories);
  useEffect(() => { refresh().catch(error => setError(String(error.message))); }, []);

  async function importRepository(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await request('/repositories', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({kind, source}) });
      await refresh(); setSource('');
    } catch (error) { setError(error instanceof Error ? error.message : 'Import failed.'); }
    finally { setBusy(false); }
  }

  return <main>
    <header><span className="eyebrow">LOCAL REPOSITORY INTELLIGENCE</span><h1>repoMap</h1><p>Bring your code into focus. Start by importing a repository.</p></header>
    <section><h2>Import a repository</h2><form onSubmit={importRepository}>
      <label>Source type<select value={kind} onChange={event => setKind(event.target.value)} disabled={busy}><option value="github">Public GitHub repository</option><option value="local">Local Git directory</option></select></label>
      <label>{kind === 'github' ? 'Repository URL' : 'Absolute directory path'}<input required value={source} onChange={event => setSource(event.target.value)} placeholder={kind === 'github' ? 'https://github.com/owner/repository.git' : 'D:\\projects\\repository'} disabled={busy}/></label>
      <button disabled={busy}>{busy ? 'Importing…' : 'Import repository'}</button>
    </form>{error && <p role="alert" className="error">{error}</p>}</section>
    <section><h2>Your repositories <small>{repositories.length}</small></h2>
      {!repositories.length && <p>No repositories imported yet.</p>}
      {repositories.map(repository => <article key={repository.id}><h3>{repository.name}</h3><p>{repository.source}</p><code>{repository.commit_sha}</code><p className="status">Imported · Indexing is planned for the next phase</p></article>)}
    </section>
  </main>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
