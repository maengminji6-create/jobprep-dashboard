"""OpenAI API로 경험별 자소서 어필 코멘트를 만듭니다.

- 키: .env 의 OPENAI_API_KEY (없으면 호출하지 않고, 화면은 규칙 기반 기본 코멘트를 보여 줌)
- 모델: .env 의 AI_MODEL (기본 gpt-5.4-mini). 더 꼼꼼한 코멘트를 원하면 gpt-5.5 등으로 바꿔도 돼요.
- 여러 경험을 한 번의 요청으로 보내고, JSON 스키마(structured outputs)로 형식이 고정된 결과를 받습니다.
"""
import json

import openai
from flask import current_app

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


def api_key() -> str:
    cfg = current_app.config
    return cfg.get("OPENAI_API_KEY") or ""


def enabled() -> bool:
    return bool(api_key())


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
    """OpenAI에 JSON 스키마 고정 응답을 요청하고 dict 로 돌려줍니다. 실패하면 사용자에게 보여 줄 AiError."""
    if not enabled():
        raise AiError("OPENAI_API_KEY 가 설정되지 않았어요.")
    client = openai.OpenAI(api_key=api_key(), timeout=180.0)
    try:
        response = client.chat.completions.create(
            model=current_app.config["AI_MODEL"],
            max_completion_tokens=16000,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        )
    except openai.AuthenticationError:
        raise AiError("API 키가 올바르지 않아요. .env 의 OPENAI_API_KEY 를 확인해 주세요.")
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
        return json.loads(choice.message.content or "")
    except ValueError:
        raise AiError("AI 응답을 읽지 못했어요. 다시 시도해 주세요.")


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


# ── 강점 진단 결과 × 내 경험 연결 ──────────────────────────────────────

STRENGTH_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "core_message": {"type": "string"},
        "strengths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "summary": {"type": "string"},
                    "experiences": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"id": {"type": "integer"}, "how": {"type": "string"}},
                            "required": ["id", "how"],
                            "additionalProperties": False,
                        },
                    },
                    "essay_tip": {"type": "string"},
                },
                "required": ["name", "summary", "experiences", "essay_tip"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "core_message", "strengths"],
    "additionalProperties": False,
}

STRENGTH_PROMPT = """당신은 취업 준비생의 강점 진단 결과와 실제 경험을 연결해 주는 커리어 코치입니다.

입력: 강점 진단 결과지 텍스트, 결과지에서 뽑은 강점 이름, 지원자의 경험 목록(id 포함), 지원 직무.

원칙:
- 결과지의 설명과 경험에 적힌 사실만 근거로 씁니다. 경험에 없는 사건이나 수치를 만들지 않습니다.
- 강점마다 그 강점이 실제로 드러난 경험을 1~3개 고르고(입력의 id 그대로), 그 경험의 어떤 행동이 근거인지 한 문장으로 씁니다.
- 연결할 경험이 없으면 experiences 를 비우고, essay_tip 에 어떤 경험을 정리해 두면 좋을지 적습니다.
- 모두 한국어로, 짧고 바로 쓸 수 있게 씁니다.

출력:
- headline: 이 사람을 한 줄로 표현하는 문장(결과지와 경험을 합쳐서)
- core_message: 지원 직무 자기소개서에서 밀고 갈 핵심 메시지 2~3문장
- strengths[]: name(결과지의 강점 이름), summary(강점 한 줄 설명), experiences[{id, how}], essay_tip(이 강점을 지원 직무 자소서에 쓰는 방법 한 문장)"""

REPORT_CHAR_LIMIT = 30000


def link_strengths_ai(report_text: str, strength_names: list[str], exps: list, role_name: str) -> tuple[dict, bool]:
    """(결과 dict, 결과지가 길어 앞부분만 보냈는지)"""
    truncated = len(report_text) > REPORT_CHAR_LIMIT
    payload = [_experience_block(e, role_name, []) for e in exps]
    prompt = PARA.join([
        f"지원 직무: {role_name}",
        f"결과지에서 뽑은 강점: {', '.join(strength_names) or '(뽑지 못함 — 결과지에서 직접 찾아 주세요)'}",
        "[강점 진단 결과지]" + NL + report_text[:REPORT_CHAR_LIMIT],
        "[경험 목록]" + NL + json.dumps(payload, ensure_ascii=False, indent=1),
    ])
    data = _call(STRENGTH_PROMPT, prompt, STRENGTH_SCHEMA, "strength_links")
    valid = {e.id for e in exps}
    for s in data.get("strengths", []):
        s["experiences"] = [x for x in s.get("experiences", []) if x.get("id") in valid]
    return data, truncated


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
    """chunks: data URL(이미지 조각) 목록 → 공고 구조(dict)."""
    if not enabled():
        raise AiError("이미지 속 공고를 읽으려면 OPENAI_API_KEY 가 필요해요.")
    if not chunks:
        raise AiError("읽을 공고 이미지가 없어요.")
    content = [{"type": "text", "text": f"채용공고 이미지 조각 {len(chunks)}개입니다. 순서대로 이어서 읽어 주세요."}]
    content += [{"type": "image_url", "image_url": {"url": c, "detail": "high"}} for c in chunks]
    client = openai.OpenAI(api_key=api_key(), timeout=240.0)
    try:
        response = client.chat.completions.create(
            model=current_app.config["AI_MODEL"],
            max_completion_tokens=16000,
            messages=[{"role": "system", "content": VISION_PROMPT}, {"role": "user", "content": content}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "posting_image", "strict": True, "schema": VISION_SCHEMA}},
        )
    except openai.AuthenticationError:
        raise AiError("API 키가 올바르지 않아요. .env 의 OPENAI_API_KEY 를 확인해 주세요.")
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
        return json.loads(choice.message.content or "")
    except ValueError:
        raise AiError("AI 응답을 읽지 못했어요. 다시 시도해 주세요.")


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
