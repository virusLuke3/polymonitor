/** Only explicitly public, credential-free source URLs may enter the browser. */
export function publicSource(name: `VITE_PUBLIC_${string}`): string {
  const value = String(import.meta.env[name] || '').trim();
  if (!value) return '';
  if (value.startsWith('/') && !value.startsWith('//')) return value;
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return '';
    if ([...url.searchParams.keys()].some(key => /^(api_?key|token|secret|password|authorization)$/i.test(key))) return '';
    return value;
  } catch {
    return '';
  }
}
