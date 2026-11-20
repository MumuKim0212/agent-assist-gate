from serve import departments


def routing_doc():
    return {"cells": ["E2=NO", "F2=팀명", "H2=세부내용",
                      "E3=1", "F3=회원관리팀", "H3=회비 감면 문의", "H4=회원 탈퇴 문의",
                      "E5=2", "F5=교육운영팀", "H5=강사 지원 문의", "H6=회원 교육 문의"]}


def test_table_parse_carries_the_team_forward():
    assert departments.table(routing_doc()) == {
        "회원관리팀": ["회비 감면 문의", "회원 탈퇴 문의"],
        "교육운영팀": ["강사 지원 문의", "회원 교육 문의"]}


def test_every_identifying_word_must_match():
    assert departments.lookup("회비 감면 받을 수 있나요", routing_doc()) == "회원관리팀"
    assert departments.lookup("회비는 얼마인가요", routing_doc()) is None


def test_two_owners_means_no_answer():
    # 회원 + 교육 matches a 교육운영팀 topic, 회원 + 탈퇴 matches a 회원관리팀 one
    assert departments.lookup("회원 탈퇴하고 회원 교육도 문의", routing_doc()) is None


def test_team_names_are_never_matched():
    assert departments.lookup("회원관리팀 바꿔주세요", routing_doc()) is None
