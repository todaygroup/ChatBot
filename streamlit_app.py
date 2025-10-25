# app.py
import streamlit as st
from openai import OpenAI

# (옵션) httpx 예외 분기
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
except Exception:
    HTTPStatusError = ConnectError = ReadTimeout = Exception

# -------------------- 기본 설정 --------------------
st.set_page_config(page_title="Chatbot (Two-Answer Select)", page_icon="💬")

st.title("💬 Chatbot (Two-Answer Select)")
st.write(
    "한 번의 질문에 대해 **두 개의 답변 후보**를 생성하고, 사용자가 채택할 수 있는 Streamlit + OpenAI 예시입니다.\n"
    "프로덕션 환경에선 `.streamlit/secrets.toml`의 `OPENAI_API_KEY` 사용을 권장합니다."
)

# -------------------- API 키 --------------------
openai_api_key = st.secrets.get("OPENAI_API_KEY", "")
if not openai_api_key:
    openai_api_key = st.text_input("OpenAI API Key", type="password")

if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
    st.stop()

# -------------------- OpenAI 클라이언트 --------------------
client = OpenAI(api_key=openai_api_key)

# -------------------- 사이드바 설정 --------------------
with st.sidebar:
    st.subheader("⚙️ 설정")
    model = st.selectbox(
        "Model",
        options=["gpt-4o-mini", "gpt-4o", "gpt-5"],  # 환경에 맞게 조정
        index=0,
        help="두 개의 후보를 비스트리밍으로 생성합니다(n=2)."
    )
    temperature = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)
    max_tokens = st.slider("Max output tokens", 128, 4096, 1024, 64)
    history_window = st.slider(
        "History window (messages)", 4, 40, 12, 1,
        help="최근 N개의 대화만 모델에 보냅니다(비용/속도 최적화)."
    )
    if st.button("🧹 대화 초기화"):
        st.session_state.clear()

# -------------------- 세션 상태 --------------------
SYSTEM_PROMPT = (
    "You are a helpful, concise assistant for a consulting/marketing professional. "
    "Answer in Korean unless the user asks for another language."
)

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# 두 후보를 임시로 담아두는 공간
if "candidates" not in st.session_state:
    st.session_state.candidates = None  # List[str] | None

if "awaiting_selection" not in st.session_state:
    st.session_state.awaiting_selection = False

# -------------------- 기존 메시지 렌더링 --------------------
for m in st.session_state.messages:
    if m["role"] == "system":
        continue
    with st.chat_message(m["role"], avatar="🤖" if m["role"] == "assistant" else "👤"):
        st.markdown(m["content"])

# -------------------- 함수: 후보 생성 --------------------
def generate_two_candidates(user_prompt: str):
    """n=2 비스트리밍 호출로 두 개의 답변 후보를 생성"""
    # 전송 페이로드(시스템 + 최근 히스토리)
    sys = [m for m in st.session_state.messages if m["role"] == "system"][:1]
    rest = [
        m for m in st.session_state.messages
        if m["role"] in ("user", "assistant")
    ][-history_window:]
    payload = sys + rest + [{"role": "user", "content": user_prompt}]

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": m["role"], "content": m["content"]} for m in payload],
        temperature=temperature,
        max_tokens=max_tokens,
        n=2,              # ★ 핵심: 두 개의 후보 생성
        stream=False,     # 스트리밍 OFF (n>1 스트리밍은 권장/지원X)
    )

    # choices → 두 개의 텍스트 추출
    candidates = []
    for ch in resp.choices:
        text = (ch.message.content or "").strip()
        candidates.append(text if text else "(빈 응답)")
    return candidates

# -------------------- 입력 처리 --------------------
prompt = st.chat_input("무엇을 도와드릴까요?")

if prompt:
    # 사용자 메시지 화면 표시 & 세션 저장 (아직 모델 호출 전)
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    try:
        # 두 개 후보 생성
        candidates = generate_two_candidates(prompt)
        st.session_state.candidates = candidates
        st.session_state.awaiting_selection = True

    except HTTPStatusError as e:
        st.error(f"API 오류({getattr(e.response, 'status_code', 'unknown')}): {str(e)[:300]}")
    except (ConnectError, ReadTimeout):
        st.error("네트워크 연결 문제로 요청이 실패했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        st.error(f"요청 중 오류가 발생했습니다: {e}")

# -------------------- 후보 선택 UI --------------------
def render_candidate_card(index: int, text: str):
    """후보 카드 UI 출력"""
    with st.container(border=True):
        st.markdown(f"### ✨ 후보 {index+1}")
        st.markdown(text)

# 후보가 준비되어 있으면 선택 UI 표기
if st.session_state.awaiting_selection and st.session_state.candidates:
    st.divider()
    st.subheader("두 개의 답변 후보가 준비되었습니다. 하나를 선택해 주세요.")

    c1, c2 = st.columns(2, vertical_alignment="top")
    with c1:
        render_candidate_card(0, st.session_state.candidates[0])
    with c2:
        render_candidate_card(1, st.session_state.candidates[1])

    st.write("")  # spacing
    choice = st.radio(
        "채택할 답변을 선택하세요",
        options=[0, 1],
        format_func=lambda i: f"후보 {i+1}",
        horizontal=True,
        index=0,
        key="candidate_choice",
    )
    sel_col, regen_col = st.columns([1, 1])
    with sel_col:
        if st.button("✅ 이 답변 채택", type="primary"):
            selected_text = st.session_state.candidates[choice]
            # 채팅에 최종 반영
            with st.chat_message("assistant", avatar="🤖"):
                st.markdown(selected_text)
            st.session_state.messages.append({"role": "assistant", "content": selected_text})
            # 상태 정리
            st.session_state.candidates = None
            st.session_state.awaiting_selection = False
            st.rerun()
    with regen_col:
        if st.button("🔄 후보 다시 생성"):
            # 마지막 사용자 메시지 재사용하여 재생성
            last_user = next((m["content"] for m in reversed(st.session_state.messages) if m["role"] == "user"), None)
            if last_user:
                try:
                    new_candidates = generate_two_candidates(last_user)
                    st.session_state.candidates = new_candidates
                    st.session_state.awaiting_selection = True
                    st.rerun()
                except HTTPStatusError as e:
                    st.error(f"API 오류({getattr(e.response, 'status_code', 'unknown')}): {str(e)[:300]}")
                except (ConnectError, ReadTimeout):
                    st.error("네트워크 연결 문제입니다. 잠시 후 다시 시도해 주세요.")
                except Exception as e:
                    st.error(f"재생성 중 오류: {e}")

# -------------------- 참고: Responses API 전환 가이드(접기) --------------------
with st.expander("📎 참고: Responses API로 전환하고 싶다면"):
    st.markdown(
        "- 위 로직은 **n=2 비스트리밍** Chat Completions를 사용합니다.\n"
        "- Responses API에서도 후보 2개 패턴을 만들 수 있지만, 일반적으로는 **각 후보를 별도 호출**로 생성하는 방식을 권장합니다(비용/성능 고려)."
    )
    st.code(
        '''
# 예시(개념): Responses API로 후보 2개를 따로 생성
def gen_candidate_with_responses_api(prompt: str) -> str:
    r = client.responses.create(
        model=model,
        input=[{"role": "system", "content": SYSTEM_PROMPT},
               {"role": "user", "content": prompt}],
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    return r.output_text  # 라이브러리 버전에 따라 접근자가 다를 수 있음
        ''',
        language="python",
    )
