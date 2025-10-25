import streamlit as st
from openai import OpenAI

st.set_page_config(page_title="Chatbot (Improved)", page_icon="💬")

# --- 헤더 ---
st.title("💬 Chatbot (Improved)")
st.write(
    "Streamlit + OpenAI 예시 앱입니다. 좌측 사이드바에서 모델/파라미터를 설정할 수 있어요.\n"
    "프로덕션에선 `.streamlit/secrets.toml`에 API 키를 저장하는 방식을 권장합니다."
)

# --- API 키 ---
openai_api_key = st.secrets.get("OPENAI_API_KEY", "")
if not openai_api_key:
    openai_api_key = st.text_input("OpenAI API Key", type="password")

if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
    st.stop()

# --- 클라이언트 ---
client = OpenAI(api_key=openai_api_key)

# --- 사이드바 설정 ---
with st.sidebar:
    st.subheader("⚙️ 설정")
    model = st.selectbox(
        "Model",
        options=["gpt-4o-mini", "gpt-4o", "gpt-5"],  # 환경에 맞게 조정
        index=0
    )
    temperature = st.slider("Temperature", 0.0, 1.0, 0.7, 0.1)
    max_tokens = st.slider("Max output tokens", 128, 4096, 1024, 64)
    HISTORY_WINDOW = st.slider("History window (messages)", 4, 40, 15, 1)

    st.caption("Tip: 4o/5 계열 최신 모델 권장. 제품/모델 안내는 OpenAI 문서를 참고하세요.")

    if st.button("🧹 대화 초기화"):
        st.session_state.messages = []

# --- 세션 상태 초기화 ---
SYSTEM_PROMPT = (
    "You are a helpful, concise assistant for a consulting/marketing professional. "
    "Answer in Korean unless the user asks for another language."
)

if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

# --- 기존 메시지 표시 ---
for message in st.session_state.messages:
    if message["role"] == "system":
        continue
    with st.chat_message(message["role"], avatar="🤖" if message["role"]=="assistant" else "👤"):
        st.markdown(message["content"])

# --- 입력 & 응답 ---
if prompt := st.chat_input("무엇을 도와드릴까요?"):
    # 사용자 메시지 저장/표시
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    try:
        # 히스토리 절단(시스템+최근 대화)
        payload = []
        sys = [m for m in st.session_state.messages if m["role"] == "system"][:1]
        rest = [m for m in st.session_state.messages if m["role"] in ("user", "assistant")][-HISTORY_WINDOW:]
        payload.extend(sys + rest)

        # --- (A) Chat Completions 스트리밍 ---
        stream = client.chat.completions.create(
            model=model,
            messages=[{"role": m["role"], "content": m["content"]} for m in payload],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        # --- (B) Responses API 스트리밍을 쓰려면 아래로 교체 ---
        # with client.responses.stream(
        #     model=model,
        #     input=[{"role": "system", "content": SYSTEM_PROMPT}] + [{"role": m["role"], "content": m["content"]} for m in rest],
        #     temperature=temperature,
        #     max_output_tokens=max_tokens,
        # ) as stream_responses:
        #     # 이벤트 루프에서 delta만 추출해 똑같이 full_text로 누적 후 저장

        # 스트림 출력 & 버퍼링
        with st.chat_message("assistant", avatar="🤖"):
            full_text = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.get("content", "")
                if delta:
                    full_text += delta
                    st.write(delta, unsafe_allow_html=True)
        st.session_state.messages.append({"role": "assistant", "content": full_text})

    except Exception as e:
        st.error(f"요청 중 오류가 발생했습니다: {e}")
