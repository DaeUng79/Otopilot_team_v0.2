const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../src/bindings/common.js'), 'utf8');

function page(screen, search = '', bootstrap = null) {
  const requests = [];
  const location = { href: `http://127.0.0.1:5190/app/${screen}`, origin: 'http://127.0.0.1:5190', search };
  const window = { fetch: async (input, init = {}) => {
    requests.push({ url: input, role: init.headers?.get?.('X-Simsa-Role') });
    if (input === '/api/v2/config') return { ok: true, json: async () => ({ data: {} }) };
    if (input === '/api/v2/bootstrap') return bootstrap
      ? { ok: true, json: async () => ({ data: bootstrap }) }
      : { ok: false, json: async () => ({ error: { message: '로그인이 필요합니다.' } }) };
    return { ok: true, status: 200, json: async () => ({ data: {} }) };
  } };
  const document = { documentElement: {}, addEventListener() {} };
  const context = { window, document, location, URL, URLSearchParams, Headers, Request, fetch: (...args) => window.fetch(...args), sessionStorage: { getItem: () => null }, crypto: { randomUUID: () => 'test-key' } };
  vm.runInNewContext(source, context);
  return { live: window.Live, requests, location };
}

test('department first-password page uses its own session', async () => {
  const { live, requests } = page('SA-00', '?role=department', { actor: { role: 'DEPARTMENT_ADMIN' }, projects: [], must_change_password: true });
  await live.begin('SA-00');
  await live.api('AUTH-04', { current_password: 'Initial1234!', new_password: 'Personal5678!' });
  assert.equal(requests.find(request => request.url === '/api/v2/bootstrap').role, 'DEPARTMENT_ADMIN');
  assert.equal(requests.at(-1).role, 'DEPARTMENT_ADMIN');
});

test('direct administrator login updates the role used for password change', async () => {
  const { live, requests } = page('SA-00');
  await live.begin('SA-00');
  live.setRole('DEPARTMENT_ADMIN');
  await live.api('AUTH-04', { current_password: 'Initial1234!', new_password: 'Personal5678!' });
  assert.equal(requests.at(-1).role, 'DEPARTMENT_ADMIN');
});

test('department session redirect keeps its role on the password page', async () => {
  const { live, location } = page('PM-01', '', { actor: { role: 'DEPARTMENT_ADMIN' }, projects: [], must_change_password: true });
  await assert.rejects(live.begin('PM-01'), /비밀번호를 변경하세요/);
  assert.match(location.href, /SA-00\/design\/login\.html\?change=1&role=department$/);
});
