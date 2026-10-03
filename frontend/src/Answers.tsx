import {useState} from 'react';
import {post, Hit} from './api';

type Answer = {status: string; answer: string | null; message?: string; results: Hit[]; citations: {id: string; path: string; start_line: number; end_line: number; excerpt: string}[]; llm_latency_ms: number; context_tokens?: number};

export function Answers({repository, snapshot, onOpen}: {repository: string; snapshot: string; onOpen: (hit: Hit) => void}) {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function ask(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      setAnswer(null);
      const evidence = await post<{results: Hit[]}>('/search', {repository_id: repository, snapshot_id: snapshot, query: question, strategy: 'ast-aware', k: 20});
      setAnswer({status: 'generating', answer: null, message: 'Code evidence is available while the optional answer is generated.', results: evidence.results, citations: [], llm_latency_ms: 0});
      setAnswer(await post('/answers', {repository_id: repository, snapshot_id: snapshot, query: question}));
    }
    catch (error) {
      setError(String(error));
      setAnswer(previous => previous ? {...previous, status: 'unavailable', message: 'The answer request failed. Retrieved code remains available.'} : null);
    } finally {setBusy(false);}
  }
  return <section><h2>Ask about this repository</h2><form onSubmit={ask}><label>Question<input required value={question} onChange={event => setQuestion(event.target.value)} placeholder="How does a login request reach authentication?"/></label><button disabled={busy || !snapshot}>{busy ? 'Retrieving evidence...' : 'Ask with code evidence'}</button></form>
    {error && <p className="error" role="alert">{error}</p>}
    {answer && <div><p className="muted">{answer.status} · LLM {answer.llm_latency_ms.toFixed(1)} ms</p><p>{answer.message}</p><pre>{answer.answer}</pre>
      {answer.citations.map(citation => <button className="text-button" key={citation.id} onClick={() => {const hit = answer.results.find(hit => hit.id === citation.id); if (hit) onOpen(hit);}}>{citation.path}:{citation.start_line}-{citation.end_line} [{citation.id}]</button>)}
      <details><summary>Retrieved evidence ({answer.results.length} chunks)</summary>{answer.results.map(hit => <button className="text-button" key={hit.id} onClick={() => onOpen(hit)}>{hit.path}:{hit.start_line} · {hit.symbol || 'module code'}</button>)}</details></div>}
  </section>;
}
