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
st.caption(
    "질문을 입력하면 **한국어/영어 답변**이 즉시 표시됩니다. "
    "한국어 답변에는 **한국어 음성**, 영어 답변에는 **영어 음성**만 노출합니다. "
    "질문 문장도 자동 번역을 함께 보여주며, 번역 언어에 맞는 음성 버튼을 제공합니다."
)

# ================== 세션 상태 ==================
ss = st.session_state
if "history" not in ss:
    # history item: {"role": "user"|"assistant", "lang": "ko"|"en", "title": str|None, "content": str, "is_demo": bool}
    ss.history = []
if "last_error" not in ss:
    ss.last_error = None

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
        "오프라인 데모 모드(실패 시에도 임시 KR/EN/번역 생성)",
        value=True,
        help="API 키 없음·한도 초과·네트워크 오류 시에도 즉시 응답합니다.",
    )

    with st.expander("🔧 디버그", expanded=False):
        st.write({"history_len": len(ss.history), "last_error": ss.last_error})

    if st.button("🧹 초기화(히스토리/에러)"):
        ss.history.clear()
        ss.last_error = None
        st.success("초기화 완료!")
        st.rerun()

# ================== API 키 ==================
secret_key = st.secrets.get("OPENAI_API_KEY", "")
env_key = os.environ.get("OPENAI_API_KEY", "")
typed_key = st.text_input(
    "OpenAI API Key (없어도 데모 모드로 동작)",
    type="password",
    value="" if (secret_key or env_key) else "",
    help="정상 호출을 원하면 API 키를 입력하세요. 미입력 시 데모 모드로 응답합니다.",
)
openai_api_key = (secret_key or env_key or typed_key).strip()

# ================== OpenAI 클라이언트 ==================
client = None
if openai_api_key:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=openai_api_key)
        if not (openai_api_key.startswith("sk-") or openai_api_key.startswith("sk-proj-")):
            st.warning("API 키는 보통 `sk-` 또는 `sk-proj-` 로 시작합니다. 값을 확인해 주세요.")
    except Exception as e:
        ss.last_error = {"code": None, "message": f"OpenAI 클라이언트 초기화 실패: {e}"}

# ================== 유틸: 간단 언어 추정 ==================
def guess_lang(text: str) -> str:
    """
    매우 가벼운 휴리스틱:
    - 한글자모가 20% 이상 → 'ko'
    - 알파벳/숫자가 60% 이상 → 'en'
    - 기본은 'ko'
    """
    if not text:
        return "ko"
    han = len(re.findall(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", text))
    alnum = len(re.findall(r"[A-Za-z0-9]", text))
    ratio_han = han / max(len(text), 1)
    ratio_aln = alnum / max(len(text), 1)
    if ratio_han >= 0.2:
        return "ko"
    if ratio_aln >= 0.6:
        return "en"
    return "ko"

# ================== 답변/번역 생성 ==================
def synth_offline_answers(q: str) -> dict:
    kr = (
        "질문에 대한 간단한 실행 가이드입니다.\n"
        "1) 목표와 제약을 명확히 정의하세요.\n"
        "2) 선택지를 2~3개로 좁히고 효과/리스크를 비교하세요.\n"
        "3) 1주 실행 계획(담당/마감/지표)을 정하고 바로 실행하세요.\n"
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

def synth_offline_translation(text: str, src: str) -> str:
    if src == "ko":
        return "(Demo) English translation is not available offline. Here is a generic hint:\nPlease translate the previous Korean sentence into English."
    else:
        return "(데모) 오프라인 환경에서는 정확한 번역이 불가합니다. 위 영어 문장을 한국어로 번역해 주세요."

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

def get_translation(text: str, src_lang: str) -> str:
    # OpenAI 가능 → 번역, 아니면 오프라인 메시지
    if client is None:
        return synth_offline_translation(text, src_lang)
    tgt = "English" if src_lang == "ko" else "Korean"
    prompt = f"Translate the following text to {tgt} without adding explanations:\n\n{text}"
    resp = client.chat.completions.create(
        model=model, temperature=0.2, max_tokens=600,
        stream=False,
        messages=[{"role": "user", "content": prompt}],
    )
    return (resp.choices[0].message.content or "").strip()

# ================== 브라우저 TTS(JS) — 단일 버튼(언어별), 토글/본문만 ==================
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

  function setIdle() {{ btn.textContent = "🔊 {label}"; }}
  function setPlaying() {{ btn.textContent = "⏹ Stop"; }}

  btn.addEventListener("click", function() {{
    const state = window.__ST_TTS_STATE__;
    const isSpeaking = window.speechSynthesis.speaking;

    if (state["{btn_id}"] && isSpeaking) {{
      window.speechSynthesis.cancel();
      state["{btn_id}"] = null;
      setIdle();
      return;
    }}

    const t = {safe_text};
    if (!t) return;
    const cfg  = window.__ST_TTS_CFG__ || {{}};
    const lang = "{lang}";
    const u = new SpeechSynthesisUtterance(t);
    u.lang   = lang;
    u.rate   = (cfg[lang]?.rate   ?? 1.0);
    u.pitch  = (cfg[lang]?.pitch  ?? 1.0);
    u.volume = (cfg[lang]?.volume ?? 1.0);

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
    # 제목 제거(첫 빈 줄 전) + 간단 마크다운 제거
    if not content:
        return ""
    if "\n\n" in content:
        content = content.split("\n\n", 1)[1]
    content = re.sub(r"[*_`#>]+", "", content).strip()
    return content

def tts_single_button(content: str, lang: str, key_id: str):
    speech_text = cleaned_speech_text(content)
    label = "듣기 (KR)" if lang == "ko" else "Listen (EN)"
    lang_code = "ko-KR" if lang == "ko" else "en-US"
    components.html(tts_button_html(speech_text, lang_code, key_id, label), height=48)

# 설정 주입(매 렌더)
push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume)

# ================== 에러 패널(고정) ==================
if ss.last_error:
    st.error(ss.last_error.get("message", "Unknown error"))

# ================== 대화 기록(UI) ==================
st.divider()
st.markdown("### 📜 대화 기록")

def render_message(role: str, lang: str, title: str | None, content: str, idx_key: str):
    with st.chat_message(role):
        if title:
            st.markdown(f"**{title}**")
        st.write(content)
        tts_single_button(content, lang, key_id=f"tts_{idx_key}")

for i, msg in enumerate(ss.history):
    render_message(msg["role"], msg["lang"], msg.get("title"), msg["content"], f"{i}")

# ================== 입력창 ==================
def add_history(role: str, lang: str, title: str | None, content: str, demo: bool=False):
    t = f"{title} _(데모)_" if (title and demo) else title
    ss.history.append({"role": role, "lang": lang, "title": t, "content": content, "is_demo": demo})

user_query = st.chat_input("궁금한 점을 입력하세요!")
if user_query:
    # 1) 사용자 원문
    src_lang = guess_lang(user_query)
    add_history("user", src_lang, None, user_query, demo=False)

    # 2) 사용자 번역(반대 언어)
    try:
        translated = get_translation(user_query, src_lang) if client else synth_offline_translation(user_query, src_lang)
    except Exception as e:
        translated = synth_offline_translation(user_query, src_lang)
        ss.last_error = {"code": None, "message": f"번역 오류: {e}"}

    tgt_lang = "en" if src_lang == "ko" else "ko"
    trans_title = "User (EN translation)" if tgt_lang == "en" else "사용자 (한국어 번역)"
    add_history("user", tgt_lang, trans_title, translated, demo=(client is None))

    # 3) 답변 생성(KR/EN)
    try:
        if client:
            with st.spinner("답변 생성 중..."):
                ans = get_bilingual_answers_from_openai(user_query)
            ss.last_error = None
            add_history("assistant", "ko", "🇰🇷 Korean Answer", ans.get("kr","").strip(), demo=False)
            add_history("assistant", "en", "🇺🇸 English Answer", ans.get("en","").strip(), demo=False)
        else:
            ss.last_error = {"code": None, "message": "OpenAI 클라이언트가 없어 데모 모드로 응답합니다."}
            demo = synth_offline_answers(user_query)
            add_history("assistant", "ko", "🇰🇷 Korean Answer", demo["kr"], demo=True)
            add_history("assistant", "en", "🇺🇸 English Answer", demo["en"], demo=True)
    except HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        text = getattr(e.response, "text", "")[:500]
        ss.last_error = {"code": code, "message": f"API 오류({code}): {text}"}
        if offline_demo:
            demo = synth_offline_answers(user_query)
            add_history("assistant", "ko", "🇰🇷 Korean Answer", demo["kr"], demo=True)
            add_history("assistant", "en", "🇺🇸 English Answer", demo["en"], demo=True)
    except (ConnectError, ReadTimeout):
        ss.last_error = {"code": None, "message": "네트워크 문제로 실패했습니다. 잠시 후 다시 시도해 주세요."}
        if offline_demo:
            demo = synth_offline_answers(user_query)
            add_history("assistant", "ko", "🇰🇷 Korean Answer", demo["kr"], demo=True)
            add_history("assistant", "en", "🇺🇸 English Answer", demo["en"], demo=True)
    except Exception as e:
        ss.last_error = {"code": None, "message": f"알 수 없는 오류: {e}"}
        if offline_demo:
            demo = synth_offline_answers(user_query)
            add_history("assistant", "ko", "🇰🇷 Korean Answer", demo["kr"], demo=True)
            add_history("assistant", "en", "🇺🇸 English Answer", demo["en"], demo=True)

    # 즉시 반영
    st.rerun()
