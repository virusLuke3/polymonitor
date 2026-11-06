import { afterEach, expect, it, vi } from 'vitest';
import { publicSource } from './publicSources';

afterEach(() => vi.unstubAllEnvs());

it('uses only an explicitly configured public endpoint', () => {
  vi.stubEnv('VITE_PUBLIC_TEST_URL', '');
  expect(publicSource('VITE_PUBLIC_TEST_URL')).toBe('');
  vi.stubEnv('VITE_PUBLIC_TEST_URL', 'https://source.example.invalid/data');
  expect(publicSource('VITE_PUBLIC_TEST_URL')).toBe('https://source.example.invalid/data');
  vi.stubEnv('VITE_PUBLIC_TEST_URL', '/data/source');
  expect(publicSource('VITE_PUBLIC_TEST_URL')).toBe('/data/source');
});

it.each(['https://' + 'user:pass@source.example.invalid', 'https://source.example.invalid/?api_key=private',
  'socks5h://source.example.invalid', 'javascript:alert(1)', '//other.example.invalid'])('rejects private or unsafe browser configuration: %s', value => {
  vi.stubEnv('VITE_PUBLIC_TEST_URL', value);
  expect(publicSource('VITE_PUBLIC_TEST_URL')).toBe('');
});
