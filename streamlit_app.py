# app.py
import os
import json
import html
import streamlit as st
from openai import OpenAI

# (선택) httpx 예외 세분화
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
except Exception:
    HTTPStatusError = ConnectError = ReadTimeout = Exception

# -------------------- 페이지/초기 설정 --------------------
st.set_page_config(page_title="Chatbot (KR & EN) + TTS", page_icon="💬")

st.title("💬 Chatbot (KR & EN Two Answers) + 🔊 TTS")
st.write(
    "질문을 입력하면 **한국어 답변**과 **영어 답변**이 즉시 히스토리에 표시됩니다. "
    "각 답변은 **브라우저 TTS** 버튼으로 들을 수 있습니다."
)

# -------------------- 세션 상태 --------------------
ss = st.session_state
if "history" not in ss:
    ss.history = []  # [{"role": "user"|"assistant", "content": str}]

# -------------------- API 키 --------------------
secret_key = st.secrets.get("OPENAI_API_KEY", "")
env_key = os.environ.get("OPENAI_API_KEY", "")
typed_key = st.text_input(
    "OpenAI API Key",
    type="password",
    value="" if (secret_key or env_key) else "",
    help="앞뒤 공백 없이 정확히 붙여넣어 주세요.",
)
openai_api_key = (secret_key or env_key or typed_key).strip()
if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
    st.stop()

# 형식 경고(동작은 계속)
if not (openai_api_key.startswith("sk-") or openai_api_key.startswith("sk-proj-")):
    st.warning("API 키는 보통 `sk-` 또는 `sk-proj-`로 시작합니다. 값을 다시 확인해 주세요.")

client = OpenAI(api_key=openai_api_key)

# -------------------- 사이드바 옵션 --------------------
with st.sidebar:
    st.subheader("⚙️ 모델/출력")
    model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-5"], index=0)
    temperature = st.slider("Temperature", 0.0, 1.2, 0.6, 0.1)
    max_tokens = st.slider("Max Output Tokens", 128, 4096, 900, 50)

    st.subheader("🔊 TTS")
    kr_rate   = st.slider("한국어 속도", 0.5, 1.5, 1.0, 0.05)
    kr_pitch  = st.slider("한국어 피치", 0.5, 2.0, 1.0, 0.05)
    kr_volume = st.slider("한국어 볼륨", 0.0, 1.0, 1.0, 0.05)
    en_rate   = st.slider("영어 속도", 0.5, 1.5, 1.0, 0.05)
    en_pitch  = st.slider("영어 피치", 0.5, 2.0, 1.0, 0.05)
    en_volume = st.slider("영어 볼륨", 0.0, 1.0, 1.0, 0.05)

    if st.button("🧹 초기화(히스토리 삭제)"):
        ss.history.clear()
        st.success("초기화 완료!")
        st.rerun()

# -------------------- OpenAI 호출 --------------------
def get_bilingual_answers(question: str) -> dict:
    """
    [KR], [EN] 두 언어 답변을 생성해 dict로 반환.
    태그 누락 시에도 최소 하나는 반환되도록 안전하게 파싱.
    """
    system = (
        "You are a bilingual assistant for consulting/marketing/planning. "
        "Return two clear answers in Korean and English."
    )
    user_prompt = f"""
User question: {question}

Return EXACTLY in this format:

[KR]
- A clear, actionable answer in Korean (3~6 sentences).

[EN]
- A clear, actionable answer in English (3~6 sentences).
"""

    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
    )

    text = (resp.choices[0].message.content or "").strip()

    # 간단 파싱
    kr, en = "", ""
    if "[KR]" in text and "[EN]" in text:
        part = text.split("[KR]", 1)[1]
        kr = part.split("[EN]", 1)[0].strip()
        en = part.split("[EN]", 1)[1].strip()
    elif "[KR]" in text:
        kr = text.split("[KR]", 1)[1].strip()
    elif "[EN]" in text:
        en = text.split("[EN]", 1)[1].strip()
    else:
        # 포맷 누락: 전체를 KR로
        kr = text

    # 완전 비었으면 최소 안전값
    if not kr and not en:
        kr = "죄송해요, 답변을 생성하지 못했습니다. 질문을 다시 시도해 주세요."

    return {"kr": kr, "en": en}

# -------------------- Web Speech API(TTS) --------------------
import streamlit.components.v1 as components

def push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume):
    cfg = {
        "ko-KR": {"rate": kr_rate, "pitch": kr_pitch, "volume": kr_volume},
        "en-US": {"rate": en_rate, "pitch": en_pitch, "volume": en_volume},
    }
    components.html(
        "<script>window.__ST_TTS_CFG__ = " + json.dumps(cfg) + ";</script>",
        height=0,
    )

def tts_button_html(text: str, lang: str, btn_id: str, label: str) -> str:
    # f-string 대신 .format(), JS 중괄호는 {{ }} 로 이스케이프
    safe_text = json.dumps(text or "")
    return """
<button id="{btn_id}" style="width:100%;cursor:pointer;border-radius:8px;padding:6px 10px;border:1px solid #444;background:#1f2937;color:#e5e7eb;">
  🔊 {label}
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
""".format(
        btn_id=btn_id,
        label=html.escape(label),
        safe_text=safe_text,
        lang=lang,
    )

def tts_row(text: str, key_prefix: str):
    c1, c2 = st.columns(2)
    with c1:
        components.html(tts_button_html(text, "ko-KR", f"{key_prefix}_kr", "Play (KR)"), height=48)
    with c2:
        components.html(tts_button_html(text, "en-US", f"{key_prefix}_en", "Play (EN)"), height=48)

# TTS 설정 주입
push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume)

# -------------------- 1) 대화 기록 (항상 먼저) --------------------
st.divider()
st.markdown("### 📜 대화 기록")
for idx, msg in enumerate(ss.history):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        tts_row(msg["content"], key_prefix=f"hist_{idx}")

# -------------------- 2) 입력창: 맨 아래 --------------------
user_query = st.chat_input("궁금한 점을 입력하세요!")
if user_query:
    # (1) 사용자 메시지 추가
    ss.history.append({"role": "user", "content": user_query})

    # (2) OpenAI 호출 → KR/EN 두 답변 생성 → 히스토리에 즉시 추가
    try:
        with st.spinner("답변 생성 중..."):
            answers = get_bilingual_answers(user_query)
        kr = answers.get("kr", "")
        en = answers.get("en", "")

        # 한국어 답변
        if kr:
            ss.history.append({"role": "assistant", "content": f"🇰🇷 **Korean Answer**\n\n{kr}"})
        # 영어 답변
        if en:
            ss.history.append({"role": "assistant", "content": f"🇺🇸 **English Answer**\n\n{en}"})

        # 두 답변이 모두 비었으면 에러 안내
        if not kr and not en:
            st.error("답변이 생성되지 않았습니다. 질문을 바꿔 다시 시도해 주세요.")
    except HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        text = getattr(e.response, "text", "")[:500]
        st.error(f"API 오류({code}): {text}")
    except (ConnectError, ReadTimeout):
        st.error("네트워크 문제로 실패했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        st.error(f"알 수 없는 오류: {e}")

    # (3) 최신 상태 반영
    st.rerun()
