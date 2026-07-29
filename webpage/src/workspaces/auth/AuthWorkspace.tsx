import type { ComponentChildren } from 'preact';
import { useCallback, useEffect, useState } from 'preact/hooks';
import {
  AuthApiError,
  changePassword,
  createApiKey,
  fetchApiKeys,
  fetchAuditLog,
  fetchAuthSession,
  login,
  logout,
  revokeApiKey,
  type AuditEvent,
  type AuthSession,
  type ProductApiKey,
} from '@/services/auth';
import { OperationsWorkspace } from '@/workspaces/operations/OperationsWorkspace';

export function errorMessage(error: unknown) {
  if (error instanceof AuthApiError) {
    return error.requestId ? `${error.message} · Request ${error.requestId}` : error.message;
  }
  return error instanceof Error ? error.message : 'The request could not be completed.';
}

export function AuthFrame({ children }: { children: ComponentChildren }) {
  return (
    <div className="auth-shell">
      <header className="auth-topbar">
        <a className="auth-home-link" href="/">◎ World</a>
        <div className="auth-brand">POLYDATA ACCESS <span>IDENTITY CONTROL PLANE</span></div>
      </header>
      {children}
    </div>
  );
}

export function SignInPanel({ next = '/account' }: { next?: string }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: Event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await login(username, password);
      const safeNext = next.startsWith('/') && !next.startsWith('//') ? next : '/account';
      window.location.assign(session.user?.forcePasswordChange ? '/account' : safeNext);
    } catch (caught) {
      setError(errorMessage(caught));
      setBusy(false);
    }
  };

  return (
    <main className="auth-main auth-login-layout">
      <section className="auth-intro">
        <span className="auth-kicker">Protected workspace / Administrator access</span>
        <h1>Operational truth stays behind a deliberate boundary.</h1>
        <p>
          Sign in to inspect system dependencies, watcher freshness, scoped API keys and the security audit trail.
          Public market intelligence remains available without an account.
        </p>
        <div className="auth-boundary-list" aria-label="Access boundary">
          <span><b>PUBLIC</b> World monitor, markets and data quality</span>
          <span><b>ADMIN</b> Operations, credentials and audit events</span>
          <span><b>API</b> Explicit scope, rate limit and daily quota</span>
        </div>
      </section>
      <form className="auth-card auth-form" onSubmit={submit}>
        <div>
          <span className="auth-card-kicker">Secure session</span>
          <h2>Administrator sign in</h2>
          <p>Sessions expire automatically and the browser never receives a reusable password or API credential.</p>
        </div>
        <label>
          <span>Username</span>
          <input
            autoComplete="username"
            value={username}
            onInput={(event) => setUsername(event.currentTarget.value)}
            placeholder="admin"
            required
          />
        </label>
        <label>
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onInput={(event) => setPassword(event.currentTarget.value)}
            required
          />
        </label>
        {error ? <div className="auth-alert" role="alert">{error}</div> : null}
        <button className="auth-primary" type="submit" disabled={busy}>
          {busy ? 'Verifying…' : 'Enter control plane'}
        </button>
        <small>Protected by an HttpOnly, Secure, SameSite session and CSRF verification.</small>
      </form>
    </main>
  );
}

export function LoadingAccess() {
  return (
    <AuthFrame>
      <main className="auth-main auth-loading">
        <span className="auth-kicker">Identity boundary</span>
        <h1>Checking session…</h1>
      </main>
    </AuthFrame>
  );
}

export function LoginWorkspace() {
  const query = new URLSearchParams(window.location.search);
  return <AuthFrame><SignInPanel next={query.get('next') || '/account'} /></AuthFrame>;
}

export function OperationsAccessWorkspace() {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    fetchAuthSession()
      .then(setSession)
      .finally(() => setReady(true));
  }, []);
  if (!ready) return <LoadingAccess />;
  if (!session?.authenticated || session.user?.role !== 'admin') {
    return <AuthFrame><SignInPanel next="/operations" /></AuthFrame>;
  }
  return <OperationsWorkspace />;
}

export function AccountWorkspace() {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [keys, setKeys] = useState<ProductApiKey[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [newKey, setNewKey] = useState<ProductApiKey | null>(null);
  const [keyName, setKeyName] = useState('operations-read');
  const [keyScope, setKeyScope] = useState('operations:read');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    const nextSession = await fetchAuthSession();
    setSession(nextSession);
    if (nextSession.authenticated && nextSession.user?.role === 'admin') {
      const [nextKeys, nextAudit] = await Promise.all([fetchApiKeys(), fetchAuditLog()]);
      setKeys(nextKeys);
      setAudit(nextAudit);
    }
    setReady(true);
  }, []);

  useEffect(() => {
    refresh().catch((caught) => {
      setError(errorMessage(caught));
      setReady(true);
    });
  }, [refresh]);

  if (!ready) return <LoadingAccess />;
  if (!session?.authenticated) return <AuthFrame><SignInPanel /></AuthFrame>;

  const updatePassword = async (event: Event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      setMessage('Password updated. Other active sessions were revoked.');
      await refresh();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const issueKey = async (event: Event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const item = await createApiKey(keyName, [keyScope]);
      setNewKey(item);
      setMessage('API key issued. Copy it now; the raw value will not be shown again.');
      setKeys(await fetchApiKeys());
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    setBusy(true);
    try {
      await logout();
      window.location.assign('/');
    } catch (caught) {
      setError(errorMessage(caught));
      setBusy(false);
    }
  };

  return (
    <AuthFrame>
      <main className="auth-main auth-account">
        <section className="auth-account-hero">
          <div>
            <span className="auth-kicker">Identity / Role / Credential governance</span>
            <h1>Access Control</h1>
            <p>Signed in as <b>{session.user?.username}</b> with the <b>{session.user?.role}</b> role.</p>
          </div>
          <div className="auth-account-actions">
            <a href="/watchlist">Open Watchlist</a>
            <a href="/briefings">Open Briefings</a>
            {session.user?.role === 'admin' ? <a href="/operations">Open Operations</a> : null}
            <button type="button" onClick={signOut} disabled={busy}>Sign out</button>
          </div>
        </section>

        {session.user?.forcePasswordChange ? (
          <div className="auth-alert is-warning">This bootstrap credential must be replaced before normal use.</div>
        ) : null}
        {message ? <div className="auth-alert is-success">{message}</div> : null}
        {error ? <div className="auth-alert" role="alert">{error}</div> : null}

        <div className="auth-account-grid">
          <form className="auth-card auth-form" onSubmit={updatePassword}>
            <div><span className="auth-card-kicker">Session security</span><h2>Change password</h2></div>
            <label><span>Current password</span><input type="password" autoComplete="current-password" value={currentPassword} onInput={(event) => setCurrentPassword(event.currentTarget.value)} required /></label>
            <label><span>New password</span><input type="password" minLength={12} maxLength={256} autoComplete="new-password" value={newPassword} onInput={(event) => setNewPassword(event.currentTarget.value)} required /></label>
            <button className="auth-primary" type="submit" disabled={busy}>Update password</button>
          </form>

          {session.user?.role === 'admin' ? (
            <form className="auth-card auth-form" onSubmit={issueKey}>
              <div><span className="auth-card-kicker">Machine access</span><h2>Issue scoped API key</h2><p>Choose one read-only boundary. Each key is limited to 60 requests/minute and 5,000/day.</p></div>
              <label><span>Credential name</span><input value={keyName} maxLength={80} onInput={(event) => setKeyName(event.currentTarget.value)} required /></label>
              <label>
                <span>Read-only scope</span>
                <select value={keyScope} onChange={(event) => setKeyScope(event.currentTarget.value)}>
                  <option value="operations:read">operations:read — protected health and freshness</option>
                  <option value="mcp:read">mcp:read — public prediction-market tools</option>
                </select>
              </label>
              <button className="auth-primary" type="submit" disabled={busy}>Create one-time key</button>
              {newKey?.key ? <output className="auth-secret"><span>Copy once</span><code>{newKey.key}</code></output> : null}
            </form>
          ) : null}
        </div>

        {session.user?.role === 'admin' ? (
          <>
            <section className="auth-card auth-table-card">
              <div className="auth-section-head"><div><span className="auth-card-kicker">Credentials</span><h2>API key registry</h2></div><span>{keys.length} total</span></div>
              <div className="auth-table-wrap">
                <table><thead><tr><th>Name</th><th>Prefix</th><th>Scope</th><th>Last used</th><th>Status</th><th /></tr></thead>
                  <tbody>{keys.map((key) => <tr key={key.id}><td>{key.name}</td><td><code>{key.prefix}…</code></td><td>{key.scopes.join(', ')}</td><td>{key.lastUsedAt ? new Date(key.lastUsedAt).toLocaleString() : 'Never'}</td><td>{key.revokedAt ? 'Revoked' : 'Active'}</td><td>{!key.revokedAt ? <button type="button" onClick={() => revokeApiKey(key.id).then(refresh).catch((caught) => setError(errorMessage(caught)))}>Revoke</button> : null}</td></tr>)}</tbody>
                </table>
              </div>
            </section>
            <section className="auth-card auth-table-card">
              <div className="auth-section-head"><div><span className="auth-card-kicker">Security events</span><h2>Audit trail</h2></div><span>{audit.length} latest</span></div>
              <div className="auth-table-wrap">
                <table><thead><tr><th>Observed</th><th>Actor</th><th>Action</th><th>Target</th><th>Result</th></tr></thead>
                  <tbody>{audit.map((event) => <tr key={event.id}><td>{new Date(event.occurredAt).toLocaleString()}</td><td>{event.username || event.actorKind}</td><td>{event.action}</td><td>{event.targetType || '—'}</td><td>{event.result}</td></tr>)}</tbody>
                </table>
              </div>
            </section>
          </>
        ) : null}
      </main>
    </AuthFrame>
  );
}
