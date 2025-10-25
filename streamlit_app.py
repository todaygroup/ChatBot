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
    st.session_state.history = []       # [{"role": "user|assistant", "content": str}, ...]
if "candidates" not in st.session_state:
    st.session_state.candidates = None  # {"kr": str, "en": str}

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
    # Web Speech API용 파라미터
    kr_rate = st.slider("한국어 속도 (rate)", 0.5, 1.5, 1.0, 0.05)
    kr_pitch = st.slider("한국어 피치 (pitch)", 0.5, 2.0, 1.0, 0.05)
    kr_volume = st.slider("한국어 볼륨 (volume)", 0.0, 1.0, 1.0, 0.05)
    en_rate = st.slider("영어 속도 (rate)", 0.5, 1.5, 1.0, 0.05)
    en_pitch = st.slider("영어 피치 (pitch)", 0.5, 2.0, 1.0, 0.05)
    en_volume = st.slider("영어 볼륨 (volume)", 0.0, 1.0, 1.0, 0.05)

    if st.button("🧹 초기화(히스토리/후보 삭제)"):
        st.session_state.history.clear()
        st.session_state.candidates = None
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

# -------------------- 공통: Web Speech API 버튼 렌더러 --------------------
#   - Streamlit 컴포넌트로 HTML/JS 삽입하여 브라우저에서 합성
#   - lang: 'ko-KR' 또는 'en-US'
def tts_button(label: str, text: str, lang: str, rate: float, pitch: float, volume: float, key: str):
    import streamlit.components.v1 as components
    safe_text = json.dumps(text)  # 안전한 JS 문자열로 인코딩
    btn_id = f"btn_{key}"
    html_code = f"""
<div style="display:inline-block;margin:4px 0 8px 0;">
  <button id="{btn_id}" style="cursor:pointer;border-radius:8px;padding:6px 10px;border:1px solid #444;background:#1f2937;color:#e5e7eb;">
    🔊 {html.escape(label)}
  </button>
</div>
<script>
  (function(){{
    const btn = document.getElementById("{btn_id}");
    if(!btn) return;
    btn.addEventListener("click", function(){{
      try {{
        const utter = new SpeechSynthesisUtterance({safe_text});
        utter.lang = "{lang}";
        utter.rate = {rate};
        utter.pitch = {pitch};
        utter.volume = {volume};
        window.speechSynthesis.cancel();  // 현재 재생 중이면 중단
        window.speechSynthesis.speak(utter);
      }} catch(e) {{
        console.error(e);
        alert("이 브라우저에서는 음성 합성이 지원되지 않을 수 있습니다.");
      }}
    }});
  }})();
</script>
"""
    components.html(html_code, height=40)

# -------------------- 1) 대화 기록 먼저 렌더링 --------------------
st.divider()
st.markdown("### 📜 대화 기록")
for idx, msg in enumerate(st.session_state.history):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        # 각 메시지에도 음성 버튼 제공: 역할에 따라 언어 추정(간단 규칙)
        # 한국어/영어 자동판별은 과할 수 있으니, 기본: user=입력 언어 미정 → KR 버튼/EN 버튼 둘 다 제공
        tts_button("Play (KR)", msg["content"], "ko-KR", kr_rate, kr_pitch, kr_volume, key=f"hist_kr_{idx}")
        tts_button("Play (EN)", msg["content"], "en-US", en_rate, en_pitch, en_volume, key=f"hist_en_{idx}")

# -------------------- 2) 후보(두 답변) 섹션: 대화 기록 '아래'에 고정 --------------------
cands = st.session_state.candidates
if cands:
    st.divider()
    st.subheader("🧠 생성된 두 개의 답변")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🇰🇷 KR Korean Answer [KR]")
        st.write(cands.get("kr") or "_(생성 결과가 비었습니다)_")
        # 한국어 음성 버튼
        tts_button("한국어로 듣기", cands.get("kr", ""), "ko-KR", kr_rate, kr_pitch, kr_volume, key="cand_kr")
        if st.button("✅ 한국어 답변 선택", key="pick_kr"):
            chosen = cands.get("kr", "")
            if chosen:
                st.session_state.history.append({"role": "assistant", "content": chosen})
            st.session_state.candidates = None
            st.rerun()

    with col2:
        st.markdown("### 🇺🇸 US English Answer [EN]")
        st.write(cands.get("en") or "_(생성 결과가 비었습니다)_")
        # 영어 음성 버튼
        tts_button("Listen in English", cands.get("en", ""), "en-US", en_rate, en_pitch, en_volume, key="cand_en")
        if st.button("✅ English Answer Select", key="pick_en"):
            chosen = cands.get("en", "")
            if chosen:
                st.session_state.history.append({"role": "assistant", "content": chosen})
            st.session_state.candidates = None
            st.rerun()

# -------------------- 3) 입력창: 항상 '맨 아래'에 배치 --------------------
user_query = st.chat_input("궁금한 점을 입력하세요!")

if user_query:
    # 히스토리에 사용자 메시지 추가
    st.session_state.history.append({"role": "user", "content": user_query})
    # 새 후보 생성 후 세션에 저장
    try:
        st.session_state.candidates = generate_two_answers(user_query)
    except HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        text = getattr(e.response, "text", "")[:500]
        st.error(f"API 오류({code}): {text}")
    except (ConnectError, ReadTimeout):
        st.error("네트워크 문제로 실패했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        st.error(f"알 수 없는 오류(응답 생성 단계): {e}")
    # 업데이트 반영
    st.rerun()
