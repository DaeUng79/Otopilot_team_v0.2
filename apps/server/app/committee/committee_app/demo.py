from pathlib import Path

from .service import CommitteeService


def seed_demo(path: Path) -> None:
    """Populate only the explicitly selected, separate demonstration database."""
    service = CommitteeService(path)
    if service.list_candidates():
        return
    fields = ["정보시스템", "데이터", "AI", "정보보안", "정보통신", "ICT전략"]
    for index in range(48):
        specialty = fields[index % len(fields)]
        if index % 7 == 0 and specialty != "데이터":
            specialty += ", 데이터"
        service.add_candidate(
            {
                "name": f"합성위원 {index + 1:02d}",
                "organization": ["가상대학교", "예시연구원", "모의공공기관"][index % 3],
                "position": ["교수", "연구원", "팀장"][index % 3],
                "phone": f"0100000{index + 1:04d}",
                "specialty": specialty,
                "email": f"member{index + 1:02d}@example.test",
                "memo": "합성 테스트 자료입니다. 실제 연락에 사용하지 마세요.",
            }
        )
    service.create_project("(합성) 정보화사업 평가과제", ["정보시스템", "데이터", "AI"], 7)
