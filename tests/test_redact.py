from core import redact


def kinds(text):
    return redact.scrub(text).kinds


def test_phone_email_and_ids_are_scrubbed():
    assert "전화번호" in kinds("010-1234-5678로 연락 주세요")
    assert "이메일" in kinds("abc.def@example.com 입니다")
    assert "주민등록번호" in kinds("981010-1234567")
    assert "사업자등록번호" in kinds("123-45-67890")


def test_ordinary_amounts_and_dates_survive():
    text = "수수료 3,000원, 2026-01-01 신청"
    assert redact.scrub(text).text == text
    assert redact.scrub(text).kinds == ()


def test_the_scrubbed_text_does_not_contain_the_number():
    assert "1234" not in redact.scrub("전화는 010-1234-5678").text
