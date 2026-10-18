// 공통 · 점수 단위 변환과 검증. 서버는 ×10000 정수, 화면은 사람이 읽는 숫자. 검증 규칙은 서버(common/server/scoring.py)와 같다.
export const SCALE = 10000;

/** ×10000 정수 → 표시 문자열 ("12", "12.5"). null 은 빈 문자열. */
export function fromScaled(value) {
  if (value === null || value === undefined || value === '') return '';
  const n = Number(value) / SCALE;
  return Number.isInteger(n) ? String(n) : String(+n.toFixed(4));
}

/** 표시 문자열 → ×10000 정수. 빈 값은 null. 숫자가 아니면 NaN. */
export function toScaled(text) {
  const t = String(text ?? '').trim();
  if (t === '') return null;
  if (!/^-?\d+(\.\d{1,4})?$/.test(t)) return NaN;
  return Math.round(Number(t) * SCALE);
}

/** 입력 검증 문구. 문제없으면 ''. max·step 은 ×10000 정수. */
export function checkInput(text, max, step) {
  const t = String(text ?? '').trim();
  if (t === '') return '';
  const scaled = toScaled(t);
  if (Number.isNaN(scaled)) return '숫자로 써 주세요';
  if (scaled < 0 || scaled > max) return `0~${fromScaled(max)}점 사이로 써 주세요`;
  if (step > 0 && scaled % step !== 0) return `${fromScaled(step)}점 단위로 써 주세요`;
  return '';
}

/** 합계 표시용: ×10000 정수 합 → 문자열. */
export function formatTotal(sumScaled) {
  return fromScaled(sumScaled) || '0';
}

/** HTML input 의 step 속성값. */
export function stepAttr(step) {
  return step > 0 ? fromScaled(step) : 'any';
}
