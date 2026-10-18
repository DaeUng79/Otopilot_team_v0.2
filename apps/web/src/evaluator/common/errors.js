// 공통 · 오류 코드 → 사용자 문구. 서버 문구가 있으면 그대로 쓰고, 없을 때만 코드별 기본 문구를 쓴다.
const MESSAGES = {
  NETWORK: '서버에 연결하지 못했어요. 연결 상태를 확인하고 다시 시도해 주세요.',
  AUTH_REQUIRED: '로그인이 필요해요. 사업 링크로 다시 들어와 주세요.',
  AUTH_FAILED: '이름이나 휴대전화 뒤 4자리를 확인해 주세요.',
  RATE_LIMITED: '여러 번 실패해 잠시 멈췄어요. 10분 뒤 다시 시도해 주세요.',
  ORIGIN_REJECTED: '허용되지 않은 경로의 요청이에요. 사업 링크로 다시 들어와 주세요.',
  ATTENDANCE_REQUIRED: '먼저 참석 확인이 필요해요.',
  NOT_PARTICIPANT: '실제 평가 참여자로 확정된 위원만 할 수 있어요. 담당자에게 문의해 주세요.',
  CHAIR_ONLY: '위원장만 할 수 있어요.',
  NOT_READY: '아직 할 수 없는 단계예요.',
  VERSION_CONFLICT: '다른 곳에서 먼저 저장됐어요. 최신 내용을 불러온 뒤 다시 확인해 주세요.',
  ALREADY_SUBMITTED: '이미 제출돼 바꿀 수 없어요.',
  IDEMPOTENCY_CONFLICT: '같은 요청이 다른 내용으로 다시 들어왔어요. 새로고침 뒤 다시 시도해 주세요.',
  VALIDATION_FAILED: '입력 내용을 확인해 주세요.',
  INPUT_INVALID: '입력 내용을 확인해 주세요.',
  STALE_SOURCE: '평가 시작 때 고정한 문서와 현재 문서 버전이 달라요. 담당자에게 알려 주세요.',
  UPSTREAM_UNAVAILABLE: '연결된 서비스가 응답하지 않아요. 잠시 뒤 다시 시도해 주세요.',
  NOT_FOUND: '찾을 수 없어요.',
  INTERNAL_ERROR: '처리 중 문제가 생겼어요. 담당자에게 알려 주세요.',
};

export function messageFor(error) {
  if (!error) return MESSAGES.INTERNAL_ERROR;
  if (error.name === 'ApiError') {
    if (error.message && error.code !== 'NETWORK' && !error.code.startsWith('HTTP_')) return error.message;
    return MESSAGES[error.code] || error.message || MESSAGES.INTERNAL_ERROR;
  }
  return error.message || MESSAGES.INTERNAL_ERROR;
}

export function fieldMessages(error) {
  return (error && error.name === 'ApiError' && error.fields) ? error.fields : {};
}
