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
    "질문 1개에 대해 **한국어(간결/자세) + 영어** 3개의 후보를 만들고, "
    "각 텍스트를 **브라우저 TTS**로 들을 수 있습니다. "
    "선택 없이도 **미리보기** 답변이 히스토리에 먼저 추가됩니다."
)

# -------------------- 세션 상태 --------------------
ss = st.session_state
if "history" not in ss:
    ss.history = []                 # [{"role": "user"|"assistant", "content": str}, ...]
if "candidates" not in ss:
    ss.candidates = {}              # {"kr_short": str, "kr_long": str, "en": str}
if "pending_selection" not in ss:
    ss.pending_selection = False    # 후보 선택 대기
if "turn_id" not in ss:
    ss.turn_id = 0                  # 질문 카운터(미리보기 중복 방지용)

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

# 간단 형식 경고
if not (openai_api_key.startswith("sk-") or openai_api_key.startswith("sk-proj-")):
    st.warning("API 키는 보통 `sk-` 또는 `sk-proj-`로 시작합니다. 값을 다시 확인해 주세요.")

client = OpenAI(api_key=openai_api_key)

# -------------------- 사이드바 옵션 --------------------
with st.sidebar:
    st.subheader("⚙️ 모델/출력 옵션")
    model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-5"], index=0)
    temperature = st.slider("Temperature", 0.0, 1.2, 0.6, 0.1)
    max_tokens = st.slider("Max Output Tokens", 128, 4096, 900, 50)

    st.subheader("🔊 음성(TTS) 설정")
    kr_rate   = st.slider("한국어 속도", 0.5, 1.5, 1.0, 0.05)
    kr_pitch  = st.slider("한국어 피치", 0.5, 2.0, 1.0, 0.05)
    kr_volume = st.slider("한국어 볼륨", 0.0, 1.0, 1.0, 0.05)
    en_rate   = st.slider("영어 속도", 0.5, 1.5, 1.0, 0.05)
    en_pitch  = st.slider("영어 피치", 0.5, 2.0, 1.0, 0.05)
    en_volume = st.slider("영어 볼륨", 0.0, 1.0, 1.0, 0.05)

    st.markdown("**Voice(목소리) 선택**")
    st.caption("브라우저의 음성 목록을 불러와 선택합니다. (지원 브라우저 권장)")
    # 아래에서 HTML/JS로 드롭다운을 만들어 JS 전역에 저장합니다.

    if st.button("🧹 초기화(히스토리/후보 삭제)"):
        ss.history.clear()
        ss.candidates = {}
        ss.pending_selection = False
        ss.turn_id = 0
        st.success("초기화 완료!")
        st.rerun()

# -------------------- 모델 호출: 후보 3개 생성 --------------------
def generate_three_answers(question: str) -> dict:
    """
    KR_SHORT (간결), KR_LONG (자세), EN (영어) 3개를 한 번에 생성.
    """
    prompt = f"""
User question: {question}

Return three answers in this exact labelled format:
[KR_SHORT]
- A concise Korean answer (3~5 sentences).

[KR_LONG]
- A detailed Korean answer (6~10 sentences, structured with short paragraphs or bullets if helpful).

[EN]
- A concise English answer (3~5 sentences).
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

    # 파싱
    def part(label_from, label_to=None):
        if label_from not in full:
            return ""
        seg = full.split(label_from, 1)[1]
        if label_to and label_to in seg:
            seg = seg.split(label_to, 1)[0]
        return seg.strip()

    kr_short = part("[KR_SHORT]", "[KR_LONG]") or ""
    kr_long  = part("[KR_LONG]", "[EN]") or ""
    en_ans   = part("[EN]") or ""

    # 태그가 없을 경우 대비
    if not (kr_short or kr_long or en_ans):
        kr_short = full

    return {"kr_short": kr_short, "kr_long": kr_long, "en": en_ans}

# -------------------- Web Speech API(TTS) 구성 --------------------
import streamlit.components.v1 as components

def push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume):
    cfg = {
        "ko-KR": {"rate": kr_rate, "pitch": kr_pitch, "volume": kr_volume},
        "en-US": {"rate": en_rate, "pitch": en_pitch, "volume": en_volume},
    }
    components.html(f"<script>window.__ST_TTS_CFG__ = {json.dumps(cfg)};</script>", height=0)

# Voice 드롭다운 (JS에서 voices 가져와 select UI 생성, 선택을 window 전역에 저장)
def voice_selectors():
    components.html(
        """
<div style="margin:6px 0;">
  <label style="display:block;margin-bottom:4px;color:#9CA3AF">한국어 Voice</label>
  <select id="voice_ko" style="width:100%;padding:6px;border-radius:6px;"></select>
</div>
<div style="margin:6px 0 12px;">
  <label style="display:block;margin-bottom:4px;color:#9CA3AF">English Voice</label>
  <select id="voice_en" style="width:100%;padding:6px;border-radius:6px;"></select>
</div>
<script>
(function(){
  function populate(){
    const voices = speechSynthesis.getVoices();
    const koSel = document.getElementById('voice_ko');
    const enSel = document.getElementById('voice_en');
    if(!koSel || !enSel) return;

    function fill(sel, filterLang, defaultContains){
      sel.innerHTML = "";
      const list = voices.filter(v => (v.lang||'').startsWith(filterLang));
      list.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.name;
        opt.textContent = v.name + " (" + v.lang + ")";
        sel.appendChild(opt);
      });
      // 기본 선택
      const def = list.find(v => (v.name||'').toLowerCase().includes(defaultContains)) || list[0];
      if(def){ sel.value = def.name; }
    }

    fill(koSel, "ko-KR", "ko");
    fill(enSel, "en", "en");

    // 선택값을 전역에 저장
    window.__ST_TTS_VOICE__ = {
      "ko-KR": koSel.value || "",
      "en-US": enSel.value || ""
    };

    koSel.onchange = function(){
      window.__ST_TTS_VOICE__["ko-KR"] = koSel.value;
    };
    enSel.onchange = function(){
      window.__ST_TTS_VOICE__["en-US"] = enSel.value;
    };
  }

  populate();
  if (typeof speechSynthesis !== "undefined") {
    // 일부 브라우저는 onvoiceschanged 이벤트 필요
    speechSynthesis.onvoiceschanged = populate;
  }
})();
</script>
        """,
        height=120,
    )

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
      const voices = speechSynthesis.getVoices();
      // voice 선택(있으면 적용)
      const pick = (window.__ST_TTS_VOICE__ && window.__ST_TTS_VOICE__[lang]) || "";
      if(pick){
        const v = voices.find(x => x.name === pick);
        if(v) utter.voice = v;
      }
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

# 설정/보이스를 JS 전역으로 주입
push_tts_config(kr_rate, kr_pitch, kr_volume, en_rate, en_pitch, en_volume)
voice_selectors()

# -------------------- 1) 대화 기록 먼저 --------------------
st.divider()
st.markdown("### 📜 대화 기록")
for idx, msg in enumerate(ss.history):
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        tts_row(msg["content"], key_prefix=f"hist_{idx}")

# -------------------- 2) 후보(3개) 섹션: 기록 아래에 고정 --------------------
cand = ss.candidates
if ss.pending_selection and isinstance(cand, dict) and any(cand.values()):
    st.divider()
    st.subheader("🧠 생성된 답변 후보 (3개)")

    # KR_SHORT 카드
    with st.container():
        st.markdown("#### 🇰🇷 KR (간결)")
        st.write(cand.get("kr_short") or "_(생성 결과 없음)_")
        tts_row(cand.get("kr_short", ""), key_prefix="cand_kr_s")
        if st.button("✅ 이 한국어(간결) 답변 선택", key="pick_kr_s"):
            ss.history.append({"role": "assistant", "content": cand.get("kr_short", "")})
            ss.pending_selection = False
            ss.candidates = {}
            st.rerun()

    # KR_LONG 카드
    with st.container():
        st.markdown("#### 🇰🇷 KR (자세)")
        st.write(cand.get("kr_long") or "_(생성 결과 없음)_")
        tts_row(cand.get("kr_long", ""), key_prefix="cand_kr_l")
        if st.button("✅ 이 한국어(자세) 답변 선택", key="pick_kr_l"):
            ss.history.append({"role": "assistant", "content": cand.get("kr_long", "")})
            ss.pending_selection = False
            ss.candidates = {}
            st.rerun()

    # EN 카드
    with st.container():
        st.markdown("#### 🇺🇸 EN (English)")
        st.write(cand.get("en") or "_(생성 결과 없음)_")
        tts_row(cand.get("en", ""), key_prefix="cand_en")
        if st.button("✅ Select this English answer", key="pick_en"):
            ss.history.append({"role": "assistant", "content": cand.get("en", "")})
            ss.pending_selection = False
            ss.candidates = {}
            st.rerun()

# -------------------- 3) 입력창: 항상 맨 아래 --------------------
user_query = st.chat_input("궁금한 점을 입력하세요!")

if user_query:
    # 사용자 메시지 기록
    ss.history.append({"role": "user", "content": user_query})

    # 새로운 턴 시작
    ss.turn_id += 1

    # 후보 생성
    try:
        with st.spinner("답변 후보 생성 중..."):
            candidates = generate_three_answers(user_query)
        ss.candidates = candidates
        ss.pending_selection = True

        # ✅ 미리보기: 가장 유용한 KR_SHORT을 바로 히스토리에 추가(선택과 별개로 남김)
        preview = candidates.get("kr_short") or candidates.get("kr_long") or candidates.get("en") or ""
        if preview:
            ss.history.append({"role": "assistant", "content": f"(미리보기)\n{preview}"})

        st.toast("3개의 답변 후보가 준비되었습니다. 아래에서 선택해 주세요.", icon="🤖")

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
