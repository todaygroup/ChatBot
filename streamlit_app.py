# app.py
import streamlit as st
from openai import OpenAI

# (옵션) httpx 예외를 더 세분화해서 처리하고 싶을 때
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
except Exception:
    HTTPStatusError = ConnectError = ReadTimeout = Exception

# -------------------- 기본 설정 --------------------
st.set_page_config(page_title="Chatbot (Improved)", page_icon="💬")

st.title("💬 Chatbot (Improved)")
st.write(
    "Streamlit + OpenAI 예시 앱입니다. 좌측 사이드바에서 모델/파라미터를 설정하세요.\n"
    "프로덕션 환경에선 `.streamlit/secrets.toml`의 `OPENAI_API_KEY` 사용을 권장합니다."
)

# -------------------- API 키 --------------------
# 1순위: secrets.toml, 2순위: 사용자 입력
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
        options=["gpt-4o-mini", "gpt-4o", "gpt-5"],  # 사용 환경에 맞게 조정
        index=0,
        help="최신 모델 사용을 권장합니다."
    )
    temperature = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)
    max_tokens = st.slider("Max output tokens", 128, 4096, 1024, 64)
    history_window = st.slider(
        "History window (messages)", 4, 40, 15, 1,
        help="최근 N개의 대화만 모델에 보냅니다(비용/속도 최적화)."
    )
    if st.button("🧹 대화 초기화"):
        st.session_state.clear()

# -------------------- 세션/시스템 프롬프트 --------------------
SYSTEM_PROMPT = (
    "You are a helpful, concise assistant for a consulting/marketing professional. "
    "Answer in Korean unless the user asks for another language."
)

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# -------------------- 기존 메시지 렌더링 --------------------
for m in st.session_state.messages:
    if m["role"] == "system":
        continue
    with st.chat_message(m["role"], avatar="🤖" if m["role"] == "assistant" else "👤"):
        st.markdown(m["content"])

# -------------------- 입력 & 스트리밍 응답 --------------------
if prompt := st.chat_input("무엇을 도와드릴까요?"):
    # 1) 사용자 메시지 저장/표시
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    try:
        # 2) 전송 페이로드(시스템 1개 + 최근 history_window개)
        sys = [m for m in st.session_state.messages if m["role"] == "system"][:1]
        rest = [m for m in st.session_state.messages if m["role"] in ("user", "assistant")][-history_window:]
        payload = sys + rest

        # 3) Chat Completions 스트리밍 호출
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": m["role"], "content": m["content"]} for m in payload],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        # 4) 스트림 수신(ChoiceDelta는 dict가 아니라 객체 → .content 사용)
        with st.chat_message("assistant", avatar="🤖"):
            full_text = ""
            placeholder = st.empty()
            for chunk in stream:
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", "") or ""
                if piece:
                    full_text += piece
                    placeholder.markdown(full_text)

        # 5) 세션에 전체 응답 저장
        st.session_state.messages.append({"role": "assistant", "content": full_text})

    except HTTPStatusError as e:
        st.error(f"API 오류({getattr(e.response, 'status_code', 'unknown')}): {str(e)[:300]}")
    except (ConnectError, ReadTimeout):
        st.error("네트워크 연결 문제로 요청이 실패했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        st.error(f"요청 중 오류가 발생했습니다: {e}")

# -------------------- (선택) 참고: Responses API 예시를 접어서 제공 --------------------
with st.expander("📎 참고: Responses API(이벤트 스트리밍) 전환 예시 보기", expanded=False):
    st.markdown(
        "아래 코드는 **Chat Completions** 대신 **Responses API**로 스트리밍하는 패턴입니다. "
        "원하시면 위 호출부(3)~(4)를 아래 코드로 교체하세요."
    )
    st.code(
        '''
with client.responses.stream(
    model=model,
    input=[{"role": "system", "content": SYSTEM_PROMPT}]
          + [{"role": m["role"], "content": m["content"]} for m in rest],
    temperature=temperature,
    max_output_tokens=max_tokens,
) as s:
    full_text = ""
    with st.chat_message("assistant", avatar="🤖"):
        placeholder = st.empty()
        for event in s:
            if event.type == "response.output_text.delta":
                full_text += event.delta
                placeholder.markdown(full_text)
        s.until_done()
st.session_state.messages.append({"role": "assistant", "content": full_text})
        ''',
        language="python",
    )
