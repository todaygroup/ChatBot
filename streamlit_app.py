# app.py
import os
import html
import json
import streamlit as st
from openai import OpenAI

# (옵션) httpx 예외 세분화
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
except Exception:
    HTTPStatusError = ConnectError = ReadTimeout = Exception

# -------------------- 페이지/초기 설정 --------------------
st.set_page_config(page_title="Chatbot (KR & EN Two Answers) + TTS", page_icon="💬")

st.title("💬 Chatbot (KR & EN Two Answers) + 🔊 TTS")
st.write(
    "한 번의 질문에 대해 **한국어**와 **영어** 두 개의 답변 후보를 동시에 생성하고, "
    "각 답변/대화 메시지를 **음성(브라우저 TTS)** 으로 들을 수 있습니다."
)

# -------------------- 세션 상태 --------------------
ss = st.session_state
if "history" not in ss:
    ss.history = []                  # [{"role": "user"|"assistant", "content": str}, ...]
if "candidates" not in ss:
    ss.candidates = {}               # {"kr": str, "en": str}
if "pending_selection" not in ss:
    ss.pending_selection = False     # 후보 선택 대기 여부

# -------------------- API 키 --------------------
secret_key = st.secrets.get("OPENAI_API_KEY", "")
env_key = os.environ.get("OPENAI_API_KEY", "")
typed_key = st.text_input(
    "OpenAI API Key", type="password",
    value="" if (secret_key or env_key) else "",
    help="앞뒤 공백 없이 정확히 붙여넣어 주세요."
)
openai_api_key = (secret_key or env_key or typed_key).strip()
if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
    st.stop()

# 간단 형식 경고(경고만, 동작은 계속)
if not (openai_api_key.startswith("sk-") or openai_api_key.startswith("sk-proj-")):
    st.warning("API 키는 보통 `sk-` 또는 `sk-proj-`로 시작합니다. 값을 다시 확인해 주세요.")

# 클라이언트 생성
client = OpenAI(api_key=openai_api_key)

# -------------------- 사이드바 옵션 --------------------
with st.sidebar:
    st.subheader("⚙️ 모델/출력 옵션")
    model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-5"], index=0)
    temperature = st.slider("Temperature", 0.0, 1.2, 0.6, 0.1)
    max_tokens = st.slider("Max Output Tokens", 128, 4096, 800, 50)

    st.subheader("🔊 음성(TTS) 설정")
    kr_rate   = st.slider("한국어 속도", 0.5, 1.5, 1.0, 0.05)
    kr_pitch  = st.slider("한국어 피치", 0.5, 2.0, 1.0, 0.05)
    kr_volume = st.slider("한국어 볼륨", 0.0, 1.0, 1.0, 0.05)
    en_rate   = st.slider("영어 속도", 0.5, 1.5, 1.0, 0.05)
    en_pitch  = st.slider("영어 피치", 0.5, 2.0, 1.0, 0.05)
    en_volume = st.slider("영어 볼륨", 0.0, 1.0, 1.0, 0.05)

    if st.button("🧹 초기화(히스토리/후보 삭제)"):
        ss.history.clear()
        ss.candidates = {}
        ss.pending_selection = False
        st.success("초기화 완료!")
        st.rerun()

# -------------------- 모델 호출: KR/EN 후보 2개 생성 --------------------
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
    full = (resp.choices[0].message.content or "").strip()

    kr, en = "", ""
    if "[KR]" in full and "[EN]" in full:
        kr = full.split("[KR]")[1].split("[EN]")[0].strip()
        en = full.split("[EN]")[1].strip()
    else:
        # 태그 누락 대비: 전체를 KR로
        kr = full
        en = ""
    return {"kr": kr, "en": en}

# -------------------- Web Speech API(TTS) 구성/버튼 --------------------
import streamlit.components.v1 as components

def push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume):
    cfg = {
        "ko-KR": {"rate": kr_rate, "pitch": kr_pitch, "volume": kr_volume},
        "en-US": {"rate": en_rate, "pitch": en_pitch, "volume": en_volume},
    }
    components.html(f"<script>window.__ST_TTS_CFG__ = {json.dumps(cfg)};</script>", height=0)

def tts_button_html(text: str, lang: str, btn_id: str, label: str):
    safe_text = json.dumps(text or "")
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

# 최신 TTS 설정을 JS 전역에 주입
push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume)

# -------------------- 1) 대화 기록 먼저 렌더링 --------------------
st.divider()
st.markdown("### 📜 대화 기록")
for idx, msg in enumerate(ss.history):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        tts_row(msg["content"], key_prefix=f"hist_{idx}")

# -------------------- 2) 후보(두 답변) 섹션: 기록 아래 고정 --------------------
cand = ss.candidates
if ss.pending_selection and isinstance(cand, dict) and (cand.get("kr") or cand.get("en")):
    st.divider()
    st.subheader("🧠 생성된 두 개의 답변 후보")

    # 2-1. 텍스트
    st.markdown("#### 🇰🇷 KR Korean")
    st.write(cand.get("kr") or "_(생성 결과 없음)_")
    # 2-2. TTS 버튼 (2열)
    tts_row(cand.get("kr", ""), key_prefix="cand_kr")

    st.markdown("#### 🇺🇸 EN English")
    st.write(cand.get("en") or "_(생성 결과 없음)_")
    tts_row(cand.get("en", ""), key_prefix="cand_en")

    # 2-3. 선택 버튼 (2열, TTS 아래)
    b1, b2 = st.columns(2)
    with b1:
        if st.button("✅ 한국어 답변 선택"):
            ss.history.append({"role": "assistant", "content": cand.get("kr", "")})
            ss.pending_selection = False
            ss.candidates = {}
            st.rerun()
    with b2:
        if st.button("✅ English Answer Select"):
            ss.history.append({"role": "assistant", "content": cand.get("en", "")})
            ss.pending_selection = False
            ss.candidates = {}
            st.rerun()

# -------------------- 3) 입력창: 항상 맨 아래 --------------------
user_query = st.chat_input("궁금한 점을 입력하세요!")
if user_query:
    # 사용자 메시지 기록
    ss.history.append({"role": "user", "content": user_query})

    # 후보 생성
    try:
        with st.spinner("답변 후보 생성 중..."):
            candidates = generate_two_answers(user_query)
        ss.candidates = candidates
        ss.pending_selection = True  # 선택 대기 시작
        st.toast("두 개의 답변 후보가 준비되었습니다. 아래에서 선택해 주세요.", icon="🤖")
    except HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        text = getattr(e.response, "text", "")[:500]
        st.error(f"API 오류({code}): {text}")
        ss.candidates = {}
        ss.pending_selection = False
    except (ConnectError, ReadTimeout):
        st.error("네트워크 문제로 실패했습니다. 잠시 후 다시 시도해 주세요.")
        ss.candidates = {}
        ss.pending_selection = False
    except Exception as e:
        st.error(f"알 수 없는 오류(응답 생성 단계): {e}")
        ss.candidates = {}
        ss.pending_selection = False

    # 상태 반영
    st.rerun()
