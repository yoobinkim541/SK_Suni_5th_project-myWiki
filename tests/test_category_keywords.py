"""카테고리 태그 추출 테스트."""
from __future__ import annotations

from src.categories.keywords import CATEGORY_KEYWORDS, CATEGORY_SLUGS, extract_tags


def test_제목에서_카테고리_키워드를_뽑는다():
    titles = ["SK하이닉스 HBM4 양산", "HBM 수요 급증", "DRAM 가격 반등"]

    tags = extract_tags(titles, "제품·기술")

    assert "HBM" in tags
    assert len(tags) <= 3


def test_빈도가_높은_것부터_나온다():
    titles = ["삼성전자 실적", "삼성전자 투자", "마이크론 증설"]

    tags = extract_tags(titles, "경쟁사")

    assert tags[0] == "삼성전자"


def test_중복_없이_돌려준다():
    """같은 문자열이 두 번 들어가면 React가 중복 key 경고를 낸다."""
    titles = ["HBM HBM HBM 이야기", "HBM 또 나온다"]

    tags = extract_tags(titles, "제품·기술")

    assert len(tags) == len(set(tags))


def test_매칭이_없으면_빈_리스트():
    """카드가 tags.length > 0 가드를 가지고 있어 빈 배열이면 블록을 생략한다."""
    assert extract_tags(["오늘 날씨가 좋다"], "제품·기술") == []
    assert extract_tags([], "제품·기술") == []


def test_영문_키워드는_단어_경계를_지킨다():
    """'AMD'가 'AMDX' 같은 문자열에 걸리면 안 된다."""
    assert "AMD" not in extract_tags(["AMDX 신제품 출시"], "고객·수요산업")
    assert "AMD" in extract_tags(["AMD 신제품 출시"], "고객·수요산업")


def test_한글_키워드는_조사가_붙어도_잡는다():
    """단어 경계를 한글에 적용하면 '메모리가', '수율은' 같은 형태를 전부 놓친다."""
    assert "메모리" in extract_tags(["메모리가 반등했다"], "제품·기술")
    assert "수율" in extract_tags(["수율은 개선됐다"], "공급망·생산")


def test_알_수_없는_카테고리는_빈_리스트():
    assert extract_tags(["HBM4 양산"], "존재하지 않는 분류") == []


def test_키워드_사전과_슬러그가_같은_6종을_덮는다():
    assert set(CATEGORY_KEYWORDS) == set(CATEGORY_SLUGS)
    assert len(CATEGORY_SLUGS) == 6
