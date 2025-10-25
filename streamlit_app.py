# app.py
import os
import json
import html
import re
import streamlit as st

# (선택) httpx 예외 세분화
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
except Exception:
    HTTPStatusError = ConnectError = ReadTimeout = Exception

# ================== 페이지/초기 설정 ==================
st.set_page_config(page_title="Chatbot (KR & EN) + TTS", page_icon="💬")

st.title("💬 Chatbot (KR & EN Two Answers) + 🔊 TTS")
st.write(
    "질문을 입력하면 **한국어 답변**과 **영어 답변**이 즉시 히스토리에 표시됩니다. "
    "각 답변은 **브라우저 TTS** 버튼(토글: 재생/정지)으로 들을 수 있습니다. "
    "오류가 발생하면 상단 고정 패널에 원인이 표시됩니다."
)

# ================== 세션 상태 ==================
ss = st.session_state
if "history" not in ss:
    ss.history = []  # [{"role": "user"|"assistant", "content": str}]
if "last_error" not in ss:
    ss.last_error = None  # {"code": int|None, "message": str}

# ================== 사이드바 ==================
with st.sidebar:
    st.subheader("⚙️ 모델/출력")
    model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o"], index=0)
    temperature = st.slider("Temperature", 0.0, 1.2, 0.6, 0.1)
    max_tokens = st.slider("Max Output Tokens", 128, 4096, 900, 50)

    st.subheader("🔊 TTS (브라우저)")
    kr_rate   = st.slider("한국어 속도", 0.5, 1.5, 1.0, 0.05)
    kr_pitch  = st.slider("한국어 피치", 0.5, 2.0, 1.0, 0.05)
    kr_volume = st.slider("한국어 볼륨", 0.0, 1.0, 1.0, 0.05)
    en_rate   = st.slider("영어 속도", 0.5, 1.5, 1.0, 0.05)
    en_pitch  = st.slider("영어 피치", 0.5, 2.0, 1.0, 0.05)
    en_volume = st.slider("영어 볼륨", 0.0, 1.0, 1.0, 0.05)

    st.subheader("🧩 안전 장치")
    offline_demo = st.toggle(
        "오프라인 데모 모드(실패 시에도 임시 KR/EN 생성)",
        value=True,
        help="API 키 없음/한도 초과/네트워크 오류 시에도 임시 답변으로 흐름을 유지합니다.",
    )

    with st.expander("🔧 디버그", expanded=False):
        st.write({"history_len": len(ss.history), "last_error": ss.last_error})

    if st.button("🧹 초기화(히스토리/에러)"):
        ss.history.clear()
        ss.last_error = None
        st.success("초기화 완료!")
        st.rerun()

# ================== API 키 입력 ==================
secret_key = st.secrets.get("OPENAI_API_KEY", "")
env_key = os.environ.get("OPENAI_API_KEY", "")
typed_key = st.text_input(
    "OpenAI API Key (없어도 데모 모드로 동작)",
    type="password",
    value="" if (secret_key or env_key) else "",
    help="정상 호출을 원하면 API 키를 입력하세요. 미입력 시 데모 모드로 동작합니다.",
)
openai_api_key = (secret_key or env_key or typed_key).strip()

# ================== OpenAI 클라이언트 (있을 때만) ==================
client = None
if openai_api_key:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_api_key)
        if not (openai_api_key.startswith("sk-") or openai_api_key.startswith("sk-proj-")):
            st.warning("API 키는 보통 `sk-` 또는 `sk-proj-` 로 시작합니다. 값을 다시 확인해 주세요.")
    except Exception as e:
        ss.last_error = {"code": None, "message": f"OpenAI 클라이언트 초기화 실패: {e}"}

# ================== 답변 생성 ==================
def synth_offline_answers(q: str) -> dict:
    """API 실패시 임시로 쓸 오프라인 답변(KR/EN)."""
    kr = (
        "질문에 대한 간단한 실행 가이드입니다.\n"
        "1) 목표와 제약을 명확히 정의하세요.\n"
        "2) 선택지를 2~3개로 좁히고 효과/리스크를 비교하세요.\n"
        "3) 1주 실행 계획(담당/마감/지표)을 적고 바로 시행하세요.\n"
        "4) 하루 1~2개 핵심 지표로 학습하며 개선하세요."
    )
    en = (
        "Here is a short action plan:\n"
        "1) Clarify goals and constraints.\n"
        "2) Narrow to 2–3 options and compare impact vs. risk.\n"
        "3) Draft a one-week plan (owner, deadline, KPI) and execute.\n"
        "4) Track 1–2 key metrics daily and iterate quickly."
    )
    return {"kr": kr, "en": en}

def get_bilingual_answers_from_openai(question: str) -> dict:
    system = (
        "You are a bilingual assistant for consulting/marketing/planning. "
        "Return two clear answers in Korean and English. Be concise and actionable."
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
        stream=False,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()

    kr, en = "", ""
    if "[KR]" in text and "[EN]" in text:
        after_kr = text.split("[KR]", 1)[1]
        kr = after_kr.split("[EN]", 1)[0].strip()
        en = after_kr.split("[EN]", 1)[1].strip()
    elif "[KR]" in text:
        kr = text.split("[KR]", 1)[1].strip()
    elif "[EN]" in text:
        en = text.split("[EN]", 1)[1].strip()
    else:
        kr = text

    if not kr and not en:
        kr = "죄송해요, 답변을 생성하지 못했습니다. 질문을 다시 시도해 주세요."
    return {"kr": kr, "en": en}

# ================== 브라우저 TTS(JS) — 토글 재생/정지, 본문만 읽기 ==================
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
    # 토글 동작: 같은 버튼을 다시 누르면 즉시 정지
    safe_text = json.dumps(text or "")
    return """
<button id="{btn_id}" style="width:100%;cursor:pointer;border-radius:8px;padding:6px 10px;border:1px solid #444;background:#1f2937;color:#e5e7eb;">
  🔊 {label}
</button>
<script>
(function(){{
  const btn  = document.getElementById("{btn_id}");
  if (!btn) return;

  window.__ST_TTS_STATE__ = window.__ST_TTS_STATE__ || {{}};

  function setIdle() {{
    btn.textContent = "🔊 {label}";
  }}
  function setPlaying() {{
    btn.textContent = "⏹ Stop";
  }}

  btn.addEventListener("click", function() {{
    const state = window.__ST_TTS_STATE__;
    const isSpeaking = window.speechSynthesis.speaking;

    // 이미 재생 중이면 → 정지(토글)
    if (state["{btn_id}"] && isSpeaking) {{
      window.speechSynthesis.cancel();
      state["{btn_id}"] = null;
      setIdle();
      return;
    }}

    // 새로 재생
    const t = {safe_text};
    if (!t) return;
    const cfg  = window.__ST_TTS_CFG__ || {{}};
    const lang = "{lang}";
    const u = new SpeechSynthesisUtterance(t);
    u.lang   = lang;
    u.rate   = (cfg[lang]?.rate   ?? 1.0);
    u.pitch  = (cfg[lang]?.pitch  ?? 1.0);
    u.volume = (cfg[lang]?.volume ?? 1.0);

    // 다른 버튼이 재생 중이면 정지 후 시작
    window.speechSynthesis.cancel();
    setPlaying();
    state["{btn_id}"] = u;

    u.onend = u.onerror = function() {{
      state["{btn_id}"] = null;
      setIdle();
    }};

    window.speechSynthesis.speak(u);
  }});
}})();
</script>
""".format(btn_id=btn_id, label=html.escape(label), safe_text=safe_text, lang=lang)

def cleaned_speech_text(content: str) -> str:
    """
    TTS는 '제목(예: 🇰🇷 Korean Answer)'을 읽지 않고 본문만 읽도록 처리.
    - 첫 빈 줄 이전의 헤더/제목은 제거
    - 마크다운 기호(**, *, #, `) 간단 제거
    """
    if not content:
        return ""
    # 1) 제목/헤더 제거: 첫 번째 빈 줄 이후만 사용
    if "\n\n" in content:
        content = content.split("\n\n", 1)[1]
    # 2) 마크다운 기호 제거(가볍게)
    content = re.sub(r"[*_`#>]+", "", content)
    # 3) 이모지/깃발만 남으면 제거
    content = content.strip()
    return content

def tts_row_for_message(content: str, key_prefix: str):
    speech_text = cleaned_speech_text(content)
    # 영어 힌트(선택)
    ascii_ratio = len(re.findall(r"[A-Za-z0-9]", speech_text or "")) / max(len(speech_text or ""), 1)
    if ascii_ratio > 0.6:
        st.caption("Tip: 영어 텍스트입니다. EN 버튼을 사용해 보세요.")
    c1, c2 = st.columns(2)
    with c1:
        components.html(tts_button_html(speech_text, "ko-KR", f"{key_prefix}_kr", "Play (KR)"), height=48)
    with c2:
        components.html(tts_button_html(speech_text, "en-US", f"{key_prefix}_en", "Play (EN)"), height=48)

# 설정 주입(매 렌더)
push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume)

# ================== 에러 패널(고정) ==================
if ss.last_error:
    st.error(ss.last_error.get("message", "Unknown error"))

# ================== 대화 기록 ==================
st.divider()
st.markdown("### 📜 대화 기록")
for idx, msg in enumerate(ss.history):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        tts_row_for_message(msg["content"], key_prefix=f"hist_{idx}")

# ================== 입력창 ==================
def add_answers_to_history(kr: str, en: str, demo: bool = False):
    if kr:
        title = "🇰🇷 **Korean Answer**" + (" _(데모)_" if demo else "")
        ss.history.append({"role": "assistant", "content": f"{title}\n\n{kr}"})
    if en:
        title = "🇺🇸 **English Answer**" + (" _(데모)_" if demo else "")
        ss.history.append({"role": "assistant", "content": f"{title}\n\n{en}"})

user_query = st.chat_input("궁금한 점을 입력하세요!")
if user_query:
    # 사용자 메시지 추가
    ss.history.append({"role": "user", "content": user_query})

    try:
        if client is not None:
            with st.spinner("답변 생성 중..."):
                ans = get_bilingual_answers_from_openai(user_query)
            ss.last_error = None
            add_answers_to_history(ans.get("kr", "").strip(), ans.get("en", "").strip(), demo=False)
        else:
            # 클라이언트 없음 → 에러 저장 + 데모 처리
            ss.last_error = {"code": None, "message": "OpenAI 클라이언트가 초기화되지 않았습니다. 데모 모드로 응답합니다."}
            demo = synth_offline_answers(user_query)
            add_answers_to_history(demo["kr"], demo["en"], demo=True)

    except HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        text = getattr(e.response, "text", "")[:500]
        ss.last_error = {"code": code, "message": f"API 오류({code}): {text}"}
        if offline_demo:
            demo = synth_offline_answers(user_query)
            add_answers_to_history(demo["kr"], demo["en"], demo=True)
    except (ConnectError, ReadTimeout):
        ss.last_error = {"code": None, "message": "네트워크 문제로 실패했습니다. 잠시 후 다시 시도해 주세요."}
        if offline_demo:
            demo = synth_offline_answers(user_query)
            add_answers_to_history(demo["kr"], demo["en"], demo=True)
    except Exception as e:
        ss.last_error = {"code": None, "message": f"알 수 없는 오류: {e}"}
        if offline_demo:
            demo = synth_offline_answers(user_query)
            add_answers_to_history(demo["kr"], demo["en"], demo=True)

    # ✅ 성공/실패 여부와 관계 없이 즉시 반영
    st.rerun()
