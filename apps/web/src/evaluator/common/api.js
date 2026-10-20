// 공통 · API 클라이언트 (/api/v2/evaluator). 응답 {data, meta} / {error} 해석, Idempotency-Key·If-Match·CSRF 헤더, 네트워크 오류 변환.
export const API = '/api/v2/evaluator';

export class ApiError extends Error {
  constructor({ code, message, status, fields, retryable, requestId }) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.fields = fields || null;
    this.retryable = !!retryable;
    this.requestId = requestId || null;
  }
}

let csrfToken = null;
export function setCsrfToken(token) { csrfToken = token || null; }

export function newKey() {
  if (globalThis.crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return 'k-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
}

/** fetch 래퍼. raw=true 면 Response 를 그대로 돌려준다(파일·SVG). */
export async function request(method, path, { body, headers, idempotencyKey, ifMatch, raw, signal } = {}) {
  const init = { method, headers: { Accept: 'application/json', 'X-Simsa-Client': 'v2-web', ...(headers || {}) }, credentials: 'same-origin', cache: 'no-store', signal };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  if (idempotencyKey) init.headers['Idempotency-Key'] = idempotencyKey;
  if (ifMatch !== undefined && ifMatch !== null) init.headers['If-Match'] = String(ifMatch);
  if (csrfToken && method !== 'GET' && method !== 'HEAD') init.headers['X-CSRF-Token'] = csrfToken;
  let res;
  try {
    res = await fetch(API + path, init);
  } catch {
    if (signal?.aborted) throw new ApiError({ code: 'ABORTED', message: '요청이 취소되었어요.', status: 0 });
    throw new ApiError({ code: 'NETWORK', message: '서버에 연결하지 못했어요. 연결 상태를 확인하고 다시 시도해 주세요.', status: 0, retryable: true });
  }
  if (raw) {
    if (!res.ok) throw await toError(res);
    return res;
  }
  if (!res.ok) throw await toError(res);
  const payload = await res.json().catch(() => null);
  if (!payload || typeof payload !== 'object') {
    throw new ApiError({ code: 'BAD_RESPONSE', message: '서버 응답을 확인하지 못했어요. 다시 시도해 주세요.', status: res.status });
  }
  return payload;
}

async function toError(res) {
  const payload = await res.json().catch(() => null);
  const err = (payload && payload.error) || {};
  return new ApiError({
    code: err.code || `HTTP_${res.status}`,
    message: err.message || '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.',
    status: res.status,
    fields: err.fields,
    retryable: err.retryable,
    requestId: payload && payload.meta ? payload.meta.request_id : null,
  });
}

export const get = (path, opts) => request('GET', path, opts);
export const post = (path, body, opts) => request('POST', path, { ...(opts || {}), body });
export const put = (path, body, opts) => request('PUT', path, { ...(opts || {}), body });

/** 줄 단위 JSON 스트림. type=done 을 받기 전 연결이 끊기면 오류로 처리한다. */
export async function postStream(path, body, onEvent, { signal } = {}) {
  const res = await request('POST', path, { body, raw: true, signal, headers: { Accept: 'application/x-ndjson' } });
  if (!res.body) throw new ApiError({ code: 'BAD_RESPONSE', message: '스트리밍 응답을 읽을 수 없어요.', status: res.status });
  const reader = res.body.getReader(), decoder = new TextDecoder();
  let pending = '', done = false;
  const handle = (line) => {
    if (!line.trim()) return;
    let event;
    try { event = JSON.parse(line); } catch { throw new ApiError({ code: 'BAD_RESPONSE', message: '답변 형식을 확인하지 못했어요.', status: res.status }); }
    if (event.type === 'error') throw new ApiError({ code: 'STREAM_FAILED', message: event.message || '답변을 이어받지 못했어요.', status: res.status });
    if (event.type === 'done') done = true;
    onEvent(event);
  };
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      pending += decoder.decode(part.value, { stream: true });
      let index;
      while ((index = pending.indexOf('\n')) >= 0) {
        handle(pending.slice(0, index));
        pending = pending.slice(index + 1);
      }
    }
    pending += decoder.decode();
    if (pending.trim()) handle(pending);
    if (!done) throw new ApiError({ code: 'BAD_RESPONSE', message: '답변 연결이 중간에 끊겼어요. 다시 질문해 주세요.', status: res.status });
  } finally { reader.releaseLock(); }
}
