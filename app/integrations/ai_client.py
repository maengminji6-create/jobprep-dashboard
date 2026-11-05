"""OpenAI API로 경험별 자소서 어필 코멘트를 만듭니다.

- 키: 사용자가 내 공간에 넣은 키, 없으면 운영자 키 OPENAI_API_KEY(배포에서는 무료 횟수 제한, core/ai_quota)
- 모델: .env 의 AI_MODEL (기본 gpt-5.4-mini). 더 꼼꼼한 코멘트를 원하면 gpt-5.5 등으로 바꿔도 돼요.
- 여러 경험을 한 번의 요청으로 보내고, JSON 스키마(structured outputs)로 형식이 고정된 결과를 받습니다.
"""
import json
import re

import openai
from flask import current_app

from ..core import ai_quota

COMMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "summary": {"type": "string"},
                    "appeal_points": {"type": "array", "items": {"type": "string"}},
                    "essay_question": {"type": "string"},
                    "opening_sentence": {"type": "string"},
                    "improve": {"type": "string"},
                },
                "required": ["id", "summary", "appeal_points", "essay_question", "opening_sentence", "improve"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["comments"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """당신은 무역업(해외영업, 무역사무, 관세·통관, 포워딩, SCM 등) 신입 채용 자기소개서를 지도하는 코치입니다.
지원자가 정리한 경험을 읽고, 지정된 직무에 지원할 때 그 경험으로 무엇을 어필하면 좋을지 코멘트합니다.

원칙:
- 경험에 적힌 사실만 근거로 씁니다. 적혀 있지 않은 수치, 성과, 회사 이름을 만들어 내지 않습니다.
- 그 직무의 실무(예: 해외영업이라면 바이어 관리, 오더·선적 흐름, 협상)와 경험을 구체적으로 연결합니다.
- 아르바이트처럼 직무와 거리가 있어 보이는 경험도 옮겨 쓸 수 있는 역량(정확성, 재고 감각, 고객 응대)을 찾아 줍니다.
- 모두 한국어로, 짧고 바로 쓸 수 있게 씁니다.

각 경험마다 다음을 채웁니다.
- summary: 이 경험이 이 직무에서 갖는 가치를 한 문장으로
- appeal_points: 자소서에서 강조할 포인트 2~3개. 각 포인트는 '무엇을 → 직무의 어떤 역량으로' 연결되는지 드러나게 한 문장씩
- essay_question: 이 경험이 가장 잘 맞는 자소서 문항 유형(예: 직무 역량, 지원 동기, 협업·갈등 해결, 도전·극복)
- opening_sentence: 그 문항의 첫 문장 예시. 경험에 있는 사실만 사용
- improve: 설득력을 높이려면 경험 정리에 무엇을 더 적으면 좋은지 한 문장(예: 결과를 숫자로, 본인 역할 구분)"""


NL = "\n"
PARA = "\n\n"


class AiError(Exception):
    pass


def enabled() -> bool:
    """지금 사용자가 AI를 쓸 수 있는지(내 키 · 남은 무료 횟수 · 하루 상한, core/ai_quota)."""
    return ai_quota.available()


def unavailable_message(cost: int = 1) -> str:
    return ai_quota.unavailable_message(cost)


def _open(cost: int, timeout: float):
    """(OpenAI 클라이언트, 운영자 무료 키인지). 쓸 수 있는 키가 없으면 AiError."""
    try:
        key, free = ai_quota.pick_key(cost)
    except ai_quota.QuotaError as exc:
        raise AiError(str(exc))
    return openai.OpenAI(api_key=key, timeout=timeout), free


def _auth_error() -> AiError:
    if ai_quota.own_key():
        return AiError("내 공간에 넣은 OpenAI API 키가 올바르지 않아요. 내 공간에서 키를 다시 넣어 주세요.")
    return AiError("API 키가 올바르지 않아요. 서버의 OPENAI_API_KEY 를 확인해 주세요.")


def check_key(key: str) -> None:
    """사용자가 넣은 키가 실제로 쓸 수 있는지 가볍게 확인(모델 목록 조회). 문제가 있으면 AiError."""
    try:
        openai.OpenAI(api_key=key, timeout=20.0).models.list()
    except openai.AuthenticationError:
        raise AiError("키가 올바르지 않아요. platform.openai.com/api-keys 에서 복사한 키를 그대로 넣어 주세요.")
    except openai.PermissionDeniedError:
        raise AiError("이 키에는 모델을 쓸 권한이 없어요. 키 권한(Permissions)을 확인해 주세요.")
    except openai.APIConnectionError:
        raise AiError("OpenAI 서버에 연결하지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    except openai.APIStatusError as exc:
        raise AiError(f"키를 확인하지 못했어요(HTTP {exc.status_code}). 잠시 뒤 다시 시도해 주세요.")


def _experience_block(exp, role_name: str, hits: list[str]) -> dict:
    fields = {"id": exp.id, "경험": exp.title, "분류": exp.category, "기관": exp.organization or "",
              "기간": exp.period or ""}
    for f in exp.TEXT_FIELDS:
        if getattr(exp, f):
            fields[exp.TEXT_LABELS[f]] = getattr(exp, f)
    if hits:
        fields[f"{role_name} 관련 키워드(분석기가 찾은 것)"] = ", ".join(hits)
    return fields


def _call(system: str, prompt: str, schema: dict, name: str) -> dict:
    """OpenAI에 JSON 스키마 고정 응답을 요청하고 dict 로 돌려줍니다. 실패하면 사용자에게 보여 줄 AiError.
    운영자 무료 키로 성공하면 무료 횟수 1회를 차감합니다(실패한 호출은 세지 않음)."""
    client, free = _open(1, 180.0)
    try:
        response = client.chat.completions.create(
            model=current_app.config["AI_MODEL"],
            max_completion_tokens=16000,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        )
    except openai.AuthenticationError:
        raise _auth_error()
    except openai.PermissionDeniedError:
        raise AiError("이 API 키로는 해당 모델을 쓸 수 없어요. 키 권한이나 AI_MODEL 값을 확인해 주세요.")
    except openai.NotFoundError:
        raise AiError(f"AI_MODEL 에 적힌 모델({current_app.config['AI_MODEL']})을 쓸 수 없어요. 모델 이름을 확인해 주세요.")
    except openai.RateLimitError as exc:
        if "quota" in str(exc).lower():
            raise AiError("OpenAI 크레딧(사용 한도)이 부족해요. platform.openai.com 의 Billing 을 확인해 주세요.")
        raise AiError("요청이 많아 잠시 막혔어요. 1분쯤 뒤에 다시 시도해 주세요.")
    except openai.BadRequestError as exc:
        raise AiError(f"AI 요청 형식 오류: {exc.message}")
    except openai.APIStatusError as exc:
        raise AiError(f"AI 서버 오류(HTTP {exc.status_code}). 잠시 뒤 다시 시도해 주세요.")
    except openai.APIConnectionError:
        raise AiError("AI 서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.")

    choice = response.choices[0]
    if choice.message.refusal:
        raise AiError("AI가 이 요청에 답하지 않았어요. 내용을 조금 고쳐서 다시 시도해 주세요.")
    if choice.finish_reason == "length":
        raise AiError("한 번에 보낸 내용이 너무 많아요. 나눠서 요청해 주세요.")
    try:
        data = json.loads(choice.message.content or "")
    except ValueError:
        raise AiError("AI 응답을 읽지 못했어요. 다시 시도해 주세요.")
    if free:
        ai_quota.charge(1)
    return data


def comment_experiences(items: list[tuple], role_name: str) -> dict[int, dict]:
    """items: [(Experience, 분석기가 찾은 직무 키워드 목록)] → {경험 id: 코멘트 dict}"""
    payload = [_experience_block(exp, role_name, hits) for exp, hits in items]
    prompt = PARA.join([
        f"지원 직무: {role_name}",
        f"아래 경험 {len(payload)}개 각각에 코멘트해 주세요. 결과의 id는 입력의 id를 그대로 씁니다.",
        json.dumps(payload, ensure_ascii=False, indent=1),
    ])
    data = _call(SYSTEM_PROMPT, prompt, COMMENT_SCHEMA, "experience_comments")
    wanted = {exp.id for exp, _ in items}
    return {c["id"]: c for c in data.get("comments", []) if c.get("id") in wanted}


REPORT_CHAR_LIMIT = 30000  # 긴 공고 원문은 앞부분만 보냄


# ── 이미지로 된 채용공고 읽기(비전) ─────────────────────────────────────

_STR_LIST = {"type": "array", "items": {"type": "string"}}
VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "company": {"type": "string"},
        "title": {"type": "string"},
        "period": {"type": "string"},
        "positions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "division": {"type": "string"}, "name": {"type": "string"}, "type": {"type": "string"},
                    "duties": _STR_LIST, "requirements": _STR_LIST, "preferred": _STR_LIST,
                },
                "required": ["division", "name", "type", "duties", "requirements", "preferred"],
                "additionalProperties": False,
            },
        },
        "common": {
            "type": "object",
            "properties": {"requirements": _STR_LIST, "preferred": _STR_LIST},
            "required": ["requirements", "preferred"],
            "additionalProperties": False,
        },
        "process": _STR_LIST,
        "other": _STR_LIST,
    },
    "required": ["company", "title", "period", "positions", "common", "process", "other"],
    "additionalProperties": False,
}

VISION_PROMPT = """당신은 채용공고 이미지를 정확히 옮겨 적는 도우미입니다.
이미지(세로로 긴 공고를 순서대로 자른 조각일 수 있음)에 적힌 내용을 빠짐없이, 적힌 그대로 구조화합니다.

원칙:
- 이미지에 없는 내용은 절대 만들지 않습니다. 요약하거나 다르게 바꿔 쓰지 말고 문구를 그대로 옮깁니다.
- 표(모집부문 / 구분 / 직무내용 / 자격요건)는 행마다 positions 하나로 만듭니다.
  division=모집부문·본부·근무지, name=직무명, type=구분(신입·경력·인턴·채용연계형 등).
- 자격요건 칸 안의 '우대사항' 아래 항목은 preferred 로, 나머지 자격요건은 requirements 로 나눕니다.
- 모든 포지션에 공통인 지원자격·우대사항은 common 에 넣습니다.
- 전형 절차는 process, 접수 기간은 period, 그 밖의 안내(근무조건·복리후생·제출서류 등)는 other 에 한 줄씩.
- 조각끼리 겹치는 부분은 한 번만 적습니다. 읽을 수 없는 글자는 건너뜁니다."""


def read_posting_images(chunks: list[str]) -> dict:
    """chunks: data URL(이미지 조각) 목록 → 공고 구조(dict). 비싼 호출이라 무료 횟수는 AI_VISION_COST회로 셈."""
    if not chunks:
        raise AiError("읽을 공고 이미지가 없어요.")
    cost = current_app.config["AI_VISION_COST"]
    content = [{"type": "text", "text": f"채용공고 이미지 조각 {len(chunks)}개입니다. 순서대로 이어서 읽어 주세요."}]
    content += [{"type": "image_url", "image_url": {"url": c, "detail": "high"}} for c in chunks]
    client, free = _open(cost, 240.0)
    try:
        response = client.chat.completions.create(
            model=current_app.config["AI_MODEL"],
            max_completion_tokens=16000,
            messages=[{"role": "system", "content": VISION_PROMPT}, {"role": "user", "content": content}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "posting_image", "strict": True, "schema": VISION_SCHEMA}},
        )
    except openai.AuthenticationError:
        raise _auth_error()
    except openai.BadRequestError as exc:
        raise AiError(f"이미지를 읽지 못했어요(요청 오류: {exc.message}). 공고 글을 붙여 넣어 주세요.")
    except openai.RateLimitError:
        raise AiError("요청이 많거나 크레딧이 부족해요. 잠시 뒤 다시 시도하거나 platform.openai.com 의 Billing 을 확인해 주세요.")
    except openai.APIStatusError as exc:
        raise AiError(f"AI 서버 오류(HTTP {exc.status_code}). 잠시 뒤 다시 시도해 주세요.")
    except openai.APIConnectionError:
        raise AiError("AI 서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.")
    choice = response.choices[0]
    if choice.message.refusal or choice.finish_reason == "length":
        raise AiError("이미지 내용을 끝까지 읽지 못했어요. 공고 글을 붙여 넣어 주세요.")
    try:
        data = json.loads(choice.message.content or "")
    except ValueError:
        raise AiError("AI 응답을 읽지 못했어요. 다시 시도해 주세요.")
    if free:
        ai_quota.charge(cost)
    return data


# ── 채용공고 × 내 경험·강점·자격증 매칭 리포트 ─────────────────────────

POSTING_SCHEMA = {
    "type": "object",
    "properties": {
        "posting_summary": {"type": "string"},
        "fit_summary": {"type": "string"},
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {"type": "string"},
                    "experience_id": {"type": "integer"},
                    "evidence": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["requirement", "experience_id", "evidence", "why"],
                "additionalProperties": False,
            },
        },
        "strengths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "posting_signal": {"type": "string"},
                               "how_to_show": {"type": "string"}},
                "required": ["name", "posting_signal", "how_to_show"],
                "additionalProperties": False,
            },
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"requirement": {"type": "string"}, "suggestion": {"type": "string"}},
                "required": ["requirement", "suggestion"],
                "additionalProperties": False,
            },
        },
        "essay_strategy": {"type": "string"},
    },
    "required": ["posting_summary", "fit_summary", "matches", "strengths", "gaps", "essay_strategy"],
    "additionalProperties": False,
}

POSTING_PROMPT = """당신은 무역·비즈니스 직무 채용 담당자의 눈으로 지원자를 코칭하는 커리어 코치입니다.
채용공고, 지원자의 경험 목록(id 포함), 자격증, 강점 진단 결과를 보고 무엇을 어떻게 매칭할지 근거와 함께 정리합니다.

원칙:
- 근거 없는 추천을 하지 않습니다. matches 의 requirement 는 공고 문장을 그대로(또는 거의 그대로) 인용하고,
  evidence 는 그 경험에 실제로 적힌 내용을 인용하거나 짧게 요약합니다. 경험에 없는 사실·수치를 만들지 않습니다.
- why 에는 그 경험이 그 요구를 왜 충족하는지(같은 업무·도구·성과·상황) 한두 문장으로 설명합니다.
- 공고 요구 가운데 증명할 경험이 없는 것은 gaps 에 넣고, 지금 할 수 있는 보완 방법을 제안합니다.
- 강점은 결과지에 나온 강점 이름을 쓰고, 공고에서 그 성향을 원한다는 신호(문장)와 보여 줄 방법을 적습니다. 결과지가 없으면 빈 배열.
- 모두 한국어로, 짧고 바로 쓸 수 있게 씁니다.

출력:
- posting_summary: 이 공고가 실제로 원하는 사람 2~3문장
- fit_summary: 지원자와의 적합도 총평 2문장(강한 점·약한 점)
- matches[]: 공고 요구 ↔ 경험 매칭 3~6개 (experience_id 는 입력 id 그대로)
- strengths[]: 공고 신호 ↔ 내 강점
- gaps[]: 부족한 요구와 보완 제안
- essay_strategy: 자기소개서 전체 구성 전략 2~3문장"""


def match_posting_ai(posting_text: str, exps: list, certs: list, strength_profile, role_name: str) -> dict:
    payload = [_experience_block(e, role_name, []) for e in exps]
    cert_lines = [f"{c.name} {c.score or ''}".strip() for c in certs]
    parts = [
        f"공고에서 추정한 직무: {role_name}",
        "[채용공고]" + NL + posting_text[:REPORT_CHAR_LIMIT],
        "[내 경험 목록]" + NL + json.dumps(payload, ensure_ascii=False, indent=1),
        "[자격증·어학]" + NL + (", ".join(cert_lines) or "없음"),
    ]
    if strength_profile is not None:
        names = ", ".join(s["name"] for s in strength_profile.strengths) or "(이름 없음)"
        parts.append("[강점 진단 결과 요약]" + NL + f"강점: {names}" + NL + strength_profile.extracted_text[:6000])
    data = _call(POSTING_PROMPT, PARA.join(parts), POSTING_SCHEMA, "posting_match")
    valid = {e.id for e in exps}
    data["matches"] = [m for m in data.get("matches", []) if m.get("experience_id") in valid]
    return data


# ── 경험 STAR 구조화 초안 ─────────────────────────────────────────────

STAR_SCHEMA = {
    "type": "object",
    "properties": {
        "star_situation": {"type": "string"}, "star_task": {"type": "string"},
        "star_action": {"type": "string"}, "star_result": {"type": "string"},
        "competencies": {
            "type": "array",
            "items": {"type": "object", "properties": {"name": {"type": "string"}, "evidence": {"type": "string"}},
                      "required": ["name", "evidence"], "additionalProperties": False},
        },
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["star_situation", "star_task", "star_action", "star_result", "competencies", "questions"],
    "additionalProperties": False,
}

STAR_PROMPT = """당신은 취업 준비생의 경험 글을 STAR(상황·과제·행동·결과)로 다시 정리해 주는 편집자입니다.

원칙(가장 중요):
- 지원자가 적은 내용만 씁니다. 적혀 있지 않은 사실·성과·숫자·기간·인원·기관명은 절대 만들지 않습니다.
- 지원자의 문장을 옮기거나 짧게 다듬기만 합니다. 과장하거나 새 표현으로 성과를 부풀리지 않습니다.
- 어느 칸에 넣을 내용이 글에 없으면 그 칸은 빈 문자열("")로 둡니다.
- 비어 있거나 모호한 칸은 questions 에 '무엇을 더 적으면 되는지' 묻는 질문으로 적습니다(최대 4개).
  결과에 수치가 없으면 "실제로 잰 값이 있다면" 적어 달라고 묻되, 숫자를 예로 지어내지 않습니다.
- competencies: 글에 근거가 있는 핵심 역량 3~5개. evidence 에는 그 근거가 된 지원자의 문장을 그대로 인용합니다.
- 모두 한국어로 씁니다."""


def structure_experience(exp, role_name: str) -> dict:
    """경험 1개 → STAR 초안 · 역량(근거 인용) · 추가로 물어볼 질문. 화면에서 확인한 뒤 저장합니다."""
    block = _experience_block(exp, role_name, [])
    prompt = PARA.join([f"지원 직무(참고): {role_name}", "경험:", json.dumps(block, ensure_ascii=False, indent=1)])
    data = _call(STAR_PROMPT, prompt, STAR_SCHEMA, "experience_star")
    data["competencies"] = [c for c in data.get("competencies", []) if c.get("name")][:5]
    data["questions"] = [q for q in data.get("questions", []) if q][:4]
    return data


# ── 자소서 답변 초안(고른 경험만 근거) ─────────────────────────────────────

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "missing": {"type": "array", "items": {"type": "string"}}},
    "required": ["answer", "missing"],
    "additionalProperties": False,
}

ANSWER_PROMPT = """당신은 지원자가 직접 겪은 경험만으로 자기소개서 답변 초안을 쓰는 코치입니다.

원칙(가장 중요):
- 아래 '경험'에 적힌 사실만 씁니다. 적혀 있지 않은 성과·숫자·기간·인원·기관·직책·수상은 절대 만들지 않습니다.
- 경험에 결과가 없으면 결과를 꾸며 내지 말고 '(결과를 적어 주세요)'처럼 괄호로 자리를 남기고 missing 에 적습니다.
- 문항이 묻는 것에 답하는 구조로: 첫 문장에 핵심 → 상황·과제 → 내가 한 행동 → 결과·배운 점 → 지원 직무와 연결.
- 글자 수 제한이 있으면 그 안에서 씁니다(공백 포함). 과장된 수식어(최고의, 완벽한 등)는 쓰지 않습니다.
- 공고 요약이 있으면 공고가 원하는 역량과 연결하되, 경험에 없는 역량을 있다고 쓰지 않습니다.
- '확인된 역량·강점'이 있으면 그 이름으로 답변의 핵심을 잡되, 근거는 거기 적힌 근거 문장과 경험 글에서만 가져옵니다.
- 한국어, 지원자 1인칭(저는)."""


def draft_answer(question: str, limit: str, exps: list, posting_text: str, role_name: str,
                 evidence: list | None = None) -> dict:
    """문항 + 고른 경험(최대 3개) → {"answer": 초안, "missing": 사용자가 더 채울 것}. 화면에서 고친 뒤 저장.
    evidence: AI 분석·강점 연결에서 원문 인용이 확인된 역량·강점(applications.services.draft_evidence)."""
    blocks = [_experience_block(e, role_name, []) for e in exps[:3]]
    parts = [f"문항: {question}", f"글자 수 제한: {limit or '없음'}", f"지원 직무: {role_name}",
             f"공고 요약(참고): {(posting_text or '')[:2500]}",
             "경험(이 내용만 근거로):", json.dumps(blocks, ensure_ascii=False, indent=1)]
    if evidence:
        parts += ["확인된 역량·강점(경험 id별, 근거 문장은 경험 글에서 인용한 것):", json.dumps(evidence, ensure_ascii=False, indent=1)]
    prompt = PARA.join(parts)
    data = _call(ANSWER_PROMPT, prompt, ANSWER_SCHEMA, "essay_draft")
    data["missing"] = [m for m in data.get("missing", []) if m][:5]
    return data


# ── 면접 준비: 예상 질문 · 답변 피드백 ───────────────────────────────────

INTERVIEW_Q_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object",
        "properties": {"category": {"type": "string"}, "question": {"type": "string"}, "basis": {"type": "string"}},
        "required": ["category", "question", "basis"], "additionalProperties": False}}},
    "required": ["questions"], "additionalProperties": False,
}

INTERVIEW_Q_PROMPT = """당신은 무역·비즈니스 직무 면접관입니다. 채용공고와 지원자의 경험을 보고 실제로 나올 법한 예상 질문을 만듭니다.

원칙:
- category 는 '직무 역량', '경험', '문제 해결', '지원 동기' 중 하나입니다.
- basis 에는 그 질문을 만든 근거를 공고 문장이나 지원자 경험 글에서 '그대로' 인용합니다(요약·창작 금지). 인용할 근거가 없으면 그 질문은 만들지 않습니다.
- 지원자 경험에 없는 사실을 있다고 가정한 질문(예: 하지 않은 업무)을 만들지 않습니다.
- 꼬리 질문이 나올 만한 구체적인 질문 6~8개, 한국어."""

INTERVIEW_FB_SCHEMA = {
    "type": "object",
    "properties": {
        "good": {"type": "array", "items": {"type": "object", "properties": {"quote": {"type": "string"}, "why": {"type": "string"}},
                                            "required": ["quote", "why"], "additionalProperties": False}},
        "improve": {"type": "array", "items": {"type": "object", "properties": {"quote": {"type": "string"}, "how": {"type": "string"}},
                                               "required": ["quote", "how"], "additionalProperties": False}},
        "follow_up": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["good", "improve", "follow_up"], "additionalProperties": False,
}

INTERVIEW_FB_PROMPT = """당신은 면접 코치입니다. 지원자의 답변만 보고 피드백합니다.

원칙:
- good·improve 의 quote 는 지원자 답변에 실제로 있는 구절을 그대로 인용합니다. 답변에 없는 말을 인용하지 않습니다.
- improve 의 how 는 '이렇게 바꿔 말해 보세요' 수준으로 구체적으로. 경험에 없는 성과·숫자를 넣으라고 권하지 않습니다
  (결과가 없으면 '실제로 있었던 결과가 있다면 덧붙이라'고만 합니다).
- follow_up: 이 답변을 들은 면접관이 할 꼬리 질문 2~3개.
- 각 항목 1~3개, 한국어."""


def interview_questions(posting_text: str, exps: list, company: str, role_name: str) -> list[dict]:
    blocks = [_experience_block(e, role_name, []) for e in exps[:8]]
    prompt = PARA.join([f"회사: {company or '(미입력)'} · 직무: {role_name}", f"채용공고:\n{(posting_text or '')[:6000]}",
                        "지원자 경험:", json.dumps(blocks, ensure_ascii=False, indent=1)])
    return _call(INTERVIEW_Q_PROMPT, prompt, INTERVIEW_Q_SCHEMA, "interview_questions").get("questions", [])


def interview_feedback(question: str, answer: str) -> dict:
    data = _call(INTERVIEW_FB_PROMPT, PARA.join([f"질문: {question}", f"답변:\n{answer}"]), INTERVIEW_FB_SCHEMA, "interview_feedback")
    norm = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731
    src = norm(answer)
    data["good"] = [g for g in data.get("good", []) if norm(g.get("quote")) and norm(g.get("quote")) in src][:3]
    data["improve"] = [g for g in data.get("improve", []) if norm(g.get("quote")) and norm(g.get("quote")) in src][:3]
    data["follow_up"] = [f for f in data.get("follow_up", []) if f][:3]
    return data


# ── 경험 분석(B): 요약·행동·해결 과정·성과·역량 — 모든 항목에 원문 인용 ─────────────────

def _quoted(extra: dict | None = None) -> dict:
    props = {"text": {"type": "string"}, "quote": {"type": "string"}, **(extra or {})}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def analysis_schema(competency_names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"analyses": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "summary": {"type": "string"},
                "actions": {"type": "array", "items": _quoted()},
                "problem_solving": _quoted(),
                "results": {"type": "array", "items": _quoted()},
                "competencies": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "enum": competency_names},
                                   "quote": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["name", "quote", "reason"], "additionalProperties": False}},
                "needs_info": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["id", "summary", "actions", "problem_solving", "results", "competencies", "needs_info"],
            "additionalProperties": False}}},
        "required": ["analyses"],
        "additionalProperties": False,
    }


ANALYSIS_PROMPT = """당신은 취업 준비생의 경험 기록을 읽고 그 안에 드러난 행동·성과·역량을 정리하는 분석가입니다.

원칙(가장 중요):
- 지원자가 적은 글에 있는 사실만 씁니다. 적혀 있지 않은 성과·수치·기간·인원·회사·업무는 절대 만들지 않습니다.
- quote 에는 근거가 된 지원자의 글을 한 글자도 바꾸지 말고 그대로 복사합니다(한 문장 또는 구절, 4자 이상).
  quote 를 원문에서 찾을 수 없는 항목은 버려지니, 요약하거나 고쳐 쓴 문장을 quote 에 넣지 마세요.
- text 는 그 근거를 짧게 정리한 문장입니다. 원문에 없는 숫자를 넣지 않습니다.
- 글에 근거가 없으면 비워 둡니다: actions·results·competencies 는 빈 배열, problem_solving 은 text·quote 모두 "".
- needs_info: 추측하지 말고, 이 경험을 설득력 있게 쓰려면 무엇을 더 적어야 하는지 짧게(최대 4개).
  예: "결과 정보 필요: 행동 뒤에 무엇이 달라졌는지", "본인 역할 구분 필요: 팀이 한 일과 내가 한 일".
- competencies: 아래 목록의 이름만 쓰고, 글에 근거가 있는 것만(역량 최대 5가지). reason 은 그 문장이 왜 그 역량인지 한 문장.
  같은 역량을 보여 주는 서로 다른 문장이 글에 더 있으면 같은 name 으로 한 항목 더 넣습니다(역량마다 최대 2개).
  근거 문장이 하나뿐이면 억지로 늘리지 않습니다.
- 모두 한국어로, 짧게 씁니다.

각 경험마다(id 는 입력 그대로):
- summary: 이 경험의 핵심을 한 문장으로(사실만)
- actions: 지원자가 직접 한 주요 행동(최대 4개)
- problem_solving: 문제 상황과 해결 과정이 글에 있으면 한 항목, 없으면 빈 값
- results: 글에서 확인되는 결과·성과(최대 3개)
- competencies, needs_info"""

EXP_TEXT_LIMIT = 2500  # 경험 1개당 보내는 글 길이(5개 묶음이 한 번의 요청에 들어가도록)


def _source_block(exp) -> dict:
    """분석용 경험 블록: 지원자가 쓴 칸만(분석기 키워드·역량 태그는 넣지 않음 → 인용이 원문에서만 나오게)."""
    block = {"id": exp.id, "경험": exp.title, "유형": exp.category, "기관": exp.organization or "", "기간": exp.period or ""}
    used = 0
    for f in exp.TEXT_FIELDS:
        v = (getattr(exp, f) or "").strip()
        if v and used < EXP_TEXT_LIMIT:
            block[exp.TEXT_LABELS[f]] = v[:EXP_TEXT_LIMIT - used]
            used += len(block[exp.TEXT_LABELS[f]])
    return block


def analyze_experiences(exps: list, competency_names: list[str]) -> dict[int, dict]:
    """경험 여러 개(최대 5개 권장) → {경험 id: 분석 dict}. 인용 검증은 analysis/services 에서 합니다."""
    payload = [_source_block(e) for e in exps]
    prompt = PARA.join([f"경험 {len(payload)}개를 각각 분석해 주세요.", "역량 이름 목록: " + ", ".join(competency_names),
                        json.dumps(payload, ensure_ascii=False, indent=1)])
    data = _call(ANALYSIS_PROMPT, prompt, analysis_schema(competency_names), "experience_analysis")
    wanted = {e.id for e in exps}
    return {a["id"]: a for a in data.get("analyses", []) if a.get("id") in wanted}


# ── 진단 강점 × 경험 연결(C) ─────────────────────────────────────────

LINK_SCHEMA = {
    "type": "object",
    "properties": {"links": {"type": "array", "items": {
        "type": "object",
        "properties": {"strength": {"type": "string"}, "experience_id": {"type": "integer"}, "quote": {"type": "string"},
                       "reason": {"type": "string"}, "evidence": {"type": "string", "enum": ["충분", "보통", "약함"]}},
        "required": ["strength", "experience_id", "quote", "reason", "evidence"], "additionalProperties": False}}},
    "required": ["links"],
    "additionalProperties": False,
}

LINK_PROMPT = """당신은 강점 진단 결과와 지원자의 실제 경험을 비교해, 강점이 실제 행동으로 드러난 경험을 찾는 커리어 분석가입니다.

원칙:
- 강점 진단의 설명과 경험에 적힌 행동이 실제로 맞닿을 때만 연결합니다. 억지로 모든 강점을 연결하지 않습니다.
- quote: 그 강점을 보여 주는 지원자의 글을 한 글자도 바꾸지 말고 그대로 복사합니다(원문에서 찾을 수 없으면 버려집니다).
- reason: 그 행동이 왜 이 강점을 보여 주는지 한 문장. 경험에 없는 사실을 덧붙이지 않습니다.
- evidence: 충분 = 구체적인 행동이 강점 설명과 직접 맞음 / 보통 = 관련 행동은 있으나 한 번·짧게 드러남 /
  약함 = 관련은 있어 보이지만 행동이 모호해 확정하기 어려움.
- strength 는 입력의 강점 이름을 그대로, experience_id 는 입력의 id 그대로 씁니다.
- 한 강점에 경험 최대 3개, 한국어로 짧게."""


def link_strengths_to_experiences(strengths: list[dict], exps: list) -> list[dict]:
    """strengths: [{"name", "summary", "definition"}] → 연결 목록(인용 검증은 analysis/services 에서)."""
    diag = [{"강점": s["name"], "진단 설명": s.get("definition") or s.get("summary") or ""} for s in strengths]
    prompt = PARA.join(["[강점 진단 결과]", json.dumps(diag, ensure_ascii=False, indent=1),
                        "[경험 목록]", json.dumps([_source_block(e) for e in exps], ensure_ascii=False, indent=1)])
    data = _call(LINK_PROMPT, prompt, LINK_SCHEMA, "strength_experience_links")
    return data.get("links", [])
