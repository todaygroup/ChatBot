# app.py
import os
import html
import json
import streamlit as st
from openai import OpenAI

# (선택) httpx 예외 세분화
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
except Exception:
    HTTPStatusError = ConnectError = ReadTimeout = Exception

# -------------------- 페이지/초기 설정 --------------------
st.set_page_config(page_title="Chatbot (KR & EN Two Answers) + TTS", page_icon="💬")

st.title("💬 Chatbot (KR & EN Two Answers) + 🔊 TTS")
st.write(
    "한 번의 질문에 대해 **한국어**와 **영어** 두 개의 답변 후보를 동시에 생성하고, "
    "각 답변/대화 메시지를 **음성(브라우저 TTS)** 으로 들을 수 있습니다. "
    "프로덕션에선 `.streamlit/secrets.toml`의 `OPENAI_API_KEY` 사용을 권장합니다."
)

# -------------------- 세션 상태 --------------------
if "history" not in st.session_state:
    st.session_state.history = []         # [{"role": "user|assistant", "content": str}, ...]
if "candidates" not in st.session_state:
    st.session_state.candidates = None    # {"kr": str, "en": str}
if "last_candidate_idx" not in st.session_state:
    st.session_state.last_candidate_idx = None  # 마지막으로 기록한 후보 답변(히스토리 인덱스)

# -------------------- API 키 로딩 --------------------
secret_key = st.secrets.get("OPENAI_API_KEY", "")
env_key = os.environ.get("OPENAI_API_KEY", "")
typed_key = st.text_input(
    "OpenAI API Key",
    type="password",
    value="" if (secret_key or env_key) else "",
    help="앞뒤 공백 없이 정확히 붙여넣어 주세요."
)
openai_api_key = (secret_key or env_key or typed_key).strip()

if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
    st.stop()

if not (openai_api_key.startswith("sk-") or openai_api_key.startswith("sk-proj-")):
    st.warning("API 키는 보통 `sk-` 또는 `sk-proj-`로 시작합니다. 값을 다시 확인해 주세요.")

# -------------------- OpenAI 클라이언트 + 사전 인증 --------------------
try:
    client = OpenAI(api_key=openai_api_key)
    _ = client.models.list()  # 사전 헬스체크
except HTTPStatusError as e:
    code = getattr(e.response, "status_code", None)
    text = getattr(e.response, "text", "")[:500]
    if code == 401:
        st.error(
            "인증 오류(401): API 키가 유효하지 않거나 권한이 없습니다.\n"
            "- 새 키를 발급해 공백 없이 붙여넣어 주세요.\n"
            "- secrets/환경변수에 남은 오래된 키를 제거하고 재시작하세요.\n\n"
            f"세부: {text}"
        )
    elif code == 429:
        st.error("요청 한도를 초과했습니다(429). 잠시 후 다시 시도해 주세요.")
    else:
        st.error(f"API 오류({code}): {text}")
    st.stop()
except (ConnectError, ReadTimeout):
    st.error("네트워크 문제로 인증 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()
except Exception as e:
    st.error(f"알 수 없는 오류(사전 인증 단계): {e}")
    st.stop()

# -------------------- 사이드바 옵션 --------------------
with st.sidebar:
    st.subheader("⚙️ 모델/출력 옵션")
    model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-5"], index=0)
    temperature = st.slider("Temperature", 0.0, 1.0, 0.6, 0.1)
    max_tokens = st.slider("Max Output Tokens", 128, 4096, 800, 50)

    st.subheader("🔊 음성(TTS) 설정")
    kr_rate   = st.slider("한국어 속도 (rate)", 0.5, 1.5, 1.0, 0.05)
    kr_pitch  = st.slider("한국어 피치 (pitch)", 0.5, 2.0, 1.0, 0.05)
    kr_volume = st.slider("한국어 볼륨 (volume)", 0.0, 1.0, 1.0, 0.05)
    en_rate   = st.slider("영어 속도 (rate)", 0.5, 1.5, 1.0, 0.05)
    en_pitch  = st.slider("영어 피치 (pitch)", 0.5, 2.0, 1.0, 0.05)
    en_volume = st.slider("영어 볼륨 (volume)", 0.0, 1.0, 1.0, 0.05)

    if st.button("🧹 초기화(히스토리/후보 삭제)"):
        st.session_state.history.clear()
        st.session_state.candidates = None
        st.session_state.last_candidate_idx = None
        st.success("초기화 완료!")
        st.rerun()

# -------------------- 유틸: 두 후보 생성 --------------------
def generate_two_answers(question: str) -> dict:
    prompt = f"""
User question: {question}

You MUST answer in the following format:

[KR]
(Write a clear, concise answer in Korean.)

[EN]
(Write a clear, concise answer in English.)
"""
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        messages=[
            {"role": "system", "content": "You are a bilingual helpful assistant."},
            {"role": "user", "content": prompt},
        ],
    )
    full = resp.choices[0].message.content

    # 간단 파싱
    kr, en = "", ""
    if "[KR]" in full and "[EN]" in full:
        kr = full.split("[KR]")[1].split("[EN]")[0].strip()
        en = full.split("[EN]")[1].strip()
    else:
        kr = full.strip()  # 포맷 어긋나면 전체를 KR로
    return {"kr": kr, "en": en}

# -------------------- 공통: Web Speech API 버튼(2열 한 줄) --------------------
import streamlit.components.v1 as components

def push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume):
    cfg = {
        "ko-KR": {"rate": kr_rate, "pitch": kr_pitch, "volume": kr_volume},
        "en-US": {"rate": en_rate, "pitch": en_pitch, "volume": en_volume},
    }
    components.html(f"<script>window.__ST_TTS_CFG__ = {json.dumps(cfg)};</script>", height=0)

def tts_button_html(text: str, lang: str, btn_id: str, label: str):
    safe_text = json.dumps(text)
    return f"""
<button id="{btn_id}" style="width:100%;cursor:pointer;border-radius:8px;padding:6px 10px;border:1px solid #444;background:#1f2937;color:#e5e7eb;">
  🔊 {html.escape(label)}
</button>
<script>
(function(){{
  const btn = document.getElementById("{btn_id}");
  if(!btn) return;
  btn.addEventListener("click", function(){{
    try {{
      const t = {safe_text};
      if(!t) return;
      const utter = new SpeechSynthesisUtterance(t);
      const cfg = window.__ST_TTS_CFG__ || {{}};
      const lang = "{lang}";
      utter.lang   = lang;
      utter.rate   = (cfg[lang]?.rate   ?? 1.0);
      utter.pitch  = (cfg[lang]?.pitch  ?? 1.0);
      utter.volume = (cfg[lang]?.volume ?? 1.0);
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utter);
    }} catch(e) {{
      console.error(e);
      alert("브라우저에서 음성 합성을 지원하지 않을 수 있습니다.");
    }}
  }});
}})();
</script>
"""

def tts_row(text: str, key_prefix: str):
    c1, c2 = st.columns(2)
    with c1:
        components.html(tts_button_html(text, "ko-KR", f"{key_prefix}_kr", "Play (KR)"), height=48)
    with c2:
        components.html(tts_button_html(text, "en-US", f"{key_prefix}_en", "Play (EN)"), height=48)

# 매 렌더마다 최신 TTS 설정 반영
push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume)

# -------------------- 1) 대화 기록 먼저 렌더링 --------------------
st.divider()
st.markdown("### 📜 대화 기록")
for idx, msg in enumerate(st.session_state.history):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        tts_row(msg["content"], key_prefix=f"hist_{idx}")

# -------------------- 2) 후보(두 답변) 섹션: 기록 '아래' --------------------
cands = st.session_state.candidates
if cands:
    st.divider()
    st.subheader("🧠 생성된 두 개의 답변")

    # KR 카드
    with st.container():
        st.markdown("#### 🇰🇷 KR Korean Answer [KR]")
        st.write(cands.get("kr") or "_(생성 결과가 비었습니다)_")
        tts_row(cands.get("kr", ""), key_prefix="cand_kr")
        if st.button("✅ 한국어 답변 선택", key="pick_kr"):
            chosen = cands.get("kr", "")
            if chosen and st.session_state.last_candidate_idx is not None:
                st.session_state.history[st.session_state.last_candidate_idx]["content"] = chosen
            st.session_state.candidates = None
            st.rerun()

    # EN 카드
    with st.container():
        st.markdown("#### 🇺🇸 US English Answer [EN]")
        st.write(cands.get("en") or "_(생성 결과가 비었습니다)_")
        tts_row(cands.get("en", ""), key_prefix="cand_en")
        if st.button("✅ English Answer Select", key="pick_en"):
            chosen = cands.get("en", "")
            if chosen and st.session_state.last_candidate_idx is not None:
                st.session_state.history[st.session_state.last_candidate_idx]["content"] = chosen
            st.session_state.candidates = None
            st.rerun()

# -------------------- 3) 입력창: 항상 '맨 아래' --------------------
user_query = st.chat_input("궁금한 점을 입력하세요!")

if user_query:
    # 사용자 메시지 기록
    st.session_state.history.append({"role": "user", "content": user_query})

    # 후보 생성
    try:
        c = generate_two_answers(user_query)
        st.session_state.candidates = c

        # ✅ 기본값: KR 답변을 히스토리에 즉시 추가
        st.session_state.history.append({"role": "assistant", "content": c.get("kr", "")})
        st.session_state.last_candidate_idx = len(st.session_state.history) - 1

    except HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        text = getattr(e.response, "text", "")[:500]
        st.error(f"API 오류({code}): {text}")
    except (ConnectError, ReadTimeout):
        st.error("네트워크 문제로 실패했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        st.error(f"알 수 없는 오류(응답 생성 단계): {e}")

    # 최신 상태 반영
    st.rerun()
