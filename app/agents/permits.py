# 인허가 유형 레지스트리 — docs/ 마크다운 문서를 코드에서 안정적으로 참조하기 위한 매핑
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

# 에이전트에게 노출되는 가상 경로 접두사. main.py 의 CompositeBackend 라우트와 일치해야 한다.
DOCS_MOUNT = "/docs"
# 실제 마크다운이 위치한 디렉토리 (FilesystemBackend root_dir).
DOCS_DIR = Path(__file__).resolve().with_name("docs")

# docs/ 하위 카테고리 폴더. 처리 절차·체크리스트는 절차 정보, 신청서 서식은 서류 정보로 분리한다.
PROCEDURE_DIR = "인허가 절차 정보"
DOCUMENT_DIR = "서류 정보"


class PermitType(StrEnum):
    """지원하는 인허가 유형 코드."""

    BUILDING = "building"
    MOUNTAIN = "mountain"
    FARMLAND = "farmland"
    ROAD = "road"
    RIVER = "river"
    DEV_ACT = "dev_act"


@dataclass(frozen=True)
class PermitDoc:
    """단일 인허가 유형의 표시명·문서 경로·검색 키워드."""

    code: PermitType
    name: str
    filename: str
    keywords: tuple[str, ...]
    form_filename: str | None = None
    category: str = PROCEDURE_DIR

    @property
    def rel_path(self) -> str:
        """절차 문서의 DOCS_DIR 기준 상대 경로. 예: 인허가 절차 정보/03_농지전용_….md"""
        return f"{self.category}/{self.filename}"

    @property
    def doc_path(self) -> str:
        """에이전트가 read_file 에 쓰는 가상 경로. 예: /docs/인허가 절차 정보/03_농지전용_….md"""
        return f"{DOCS_MOUNT}/{self.rel_path}"

    @property
    def form_rel_path(self) -> str | None:
        """신청서 서식 문서의 DOCS_DIR 기준 상대 경로. 미등록이면 None."""
        if self.form_filename is None:
            return None
        return f"{DOCUMENT_DIR}/{self.form_filename}"

    @property
    def form_doc_path(self) -> str | None:
        """에이전트가 read_file 에 쓰는 서식 가상 경로. 예: /docs/서류 정보/산지전용 허가 신청서.md"""
        rel = self.form_rel_path
        return f"{DOCS_MOUNT}/{rel}" if rel else None


# 6개 인허가 유형 ↔ docs/ 파일 매핑. 새 유형은 docs/ 에 .md 추가 후 여기 1줄 등록한다.
PERMITS: tuple[PermitDoc, ...] = (
    PermitDoc(
        code=PermitType.BUILDING,
        name="건축ㆍ대수선ㆍ용도변경 허가",
        filename="건축ㆍ대수선ㆍ용도변경 허가 신청서.md",
        form_filename="건축ㆍ대수선ㆍ용도변경 (변경)허가 신청서.md",
        keywords=("건축", "신축", "증축", "대수선", "용도변경", "건물"),
    ),
    PermitDoc(
        code=PermitType.MOUNTAIN,
        name="산지전용 허가",
        filename="02_산지전용_허가_체크리스트_프로세스.md",
        form_filename="산지전용 허가 신청서.md",
        keywords=("산지", "산지전용", "임야", "산림"),
    ),
    PermitDoc(
        code=PermitType.FARMLAND,
        name="농지전용 허가",
        filename="03_농지전용_허가_체크리스트_프로세스.md",
        form_filename="농지전용(허가·변경허가) 신청서.md",
        keywords=("농지", "농지전용", "전답", "경작"),
    ),
    PermitDoc(
        code=PermitType.ROAD,
        name="도로점용 허가",
        filename="04_도로점용허가_체크리스트_프로세스.md",
        form_filename="도로 점용 허가 신청서.md",
        keywords=("도로", "도로점용", "점용", "굴착"),
    ),
    PermitDoc(
        code=PermitType.RIVER,
        name="하천점용 허가",
        filename="05_하천점용허가_체크리스트_프로세스.md",
        form_filename="하천 점용 허가 신청서.md",
        keywords=("하천", "하천점용", "홍수관리구역"),
    ),
    PermitDoc(
        code=PermitType.DEV_ACT,
        name="개발행위 허가",
        filename="06_개발행위허가_체크리스트_프로세스.md",
        form_filename="개발행위 허가신청서.md",
        keywords=("개발행위", "형질변경", "토석채취", "공작물"),
    ),
)

# 코드 문자열 → PermitDoc 빠른 조회용 인덱스.
PERMITS_BY_CODE: dict[str, PermitDoc] = {p.code.value: p for p in PERMITS}


def get_permit(code: str) -> PermitDoc | None:
    """유형 코드로 PermitDoc 을 조회한다. 미등록 코드면 None."""
    return PERMITS_BY_CODE.get(code)


def format_land_context(ctx: dict) -> str:
    """대상 필지 정보(dict)를 시스템/대화 주입용 한국어 마크다운 블록으로 렌더한다.

    값이 없는 항목은 생략한다. landUses 는 규제 목록으로, building 은 개발현황으로 펼친다.
    """

    def line(label: str, value: object, unit: str = "") -> str | None:
        if value is None or value == "":
            return None
        return f"- {label}: {value}{unit}"

    parts: list[str] = ["## 대상 필지 정보"]

    basic = [
        line("PNU", ctx.get("pnu")),
        line("주소", ctx.get("address")),
        line("지목", ctx.get("lndcgrCodeNm")),
        line("대지면적", ctx.get("lndpclAr"), " ㎡"),
        line("용도지역", ctx.get("prposArea1Nm")),
        line("용도지역2", ctx.get("prposArea2Nm")),
        line("토지이용상황", ctx.get("ladUseSittnNm")),
        line("도로접면", ctx.get("roadSideCodeNm")),
        line("개별공시지가", ctx.get("pblntfPclnd"), " 원/㎡"),
    ]
    parts.extend(p for p in basic if p)

    building = ctx.get("building") or {}
    if building.get("hasBuilding"):
        parts.append("### 건물 현황")
        bld = [
            line("건물명", building.get("bldNm")),
            line("주용도", building.get("mainPurpsCdNm")),
            line("연면적", building.get("totArea"), " ㎡"),
            line("건폐율", building.get("bcRat"), " %"),
            line("용적률", building.get("vlRat"), " %"),
            line("높이", building.get("heit"), " m"),
            line("지상층수", building.get("grndFlrCnt"), " 층"),
            line("지하층수", building.get("ugrndFlrCnt"), " 층"),
            line("구조", building.get("strctCdNm")),
        ]
        parts.extend(p for p in bld if p)
    elif building:
        parts.append("### 건물 현황\n- 건물 없음(나대지)")

    land_uses = ctx.get("landUses") or []
    if land_uses:
        parts.append("### 토지이용 규제")
        for item in land_uses:
            name = item.get("name") or item.get("code") or ""
            code = item.get("code")
            conflict = item.get("conflictType")
            suffix = f" ({conflict})" if conflict else ""
            code_part = f" [{code}]" if code and code != name else ""
            parts.append(f"- {name}{code_part}{suffix}")

    return "\n".join(parts)


def build_docs_index() -> str:
    """시스템 프롬프트에 주입할 인허가 문서 인덱스 텍스트를 만든다.

    에이전트는 이 인덱스로 '어떤 유형의 어떤 파일이 있는지'만 인지하고,
    실제 내용은 필요한 턴에 read_file(doc_path)로 직접 읽는다.
    """
    lines = [
        f"- {p.code.value} : {p.name} → {p.doc_path}  (키워드: {', '.join(p.keywords)})"
        for p in PERMITS
    ]
    return "\n".join(lines)


def build_forms_index() -> str:
    """시스템 프롬프트에 주입할 신청서 서식 인덱스 텍스트를 만든다.

    유형별 서식 문서 경로만 노출한다. 항목명·작성 양식은 필요한 턴에
    read_file(form_doc_path)로 직접 읽는다.
    """
    lines = [
        f"- {p.code.value} : {p.name} 신청서 → {p.form_doc_path}"
        for p in PERMITS
        if p.form_doc_path
    ]
    return "\n".join(lines)
