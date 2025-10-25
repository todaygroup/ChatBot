# app.py
import streamlit as st
from openai import OpenAI

# --------optional: 더 세분화된 예외---------
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
except Exception:
    HTTPStatusError = ConnectError = ReadTimeout = Exception

# -------- Streamlit 기본 설정 --------
st.set_page_config(page_title="Two-Language Answer Chatbot", page_icon="💬")

st.title("💬 Chatbot (KR & EN Two Answers)")
st.write(
    "한 번의 질문에 대해 **한국어**와 **영어** 답변 후보를 동시에 제시하고, "
    "사용자가 선택할 수 있는 Streamlit + OpenAI 예시입니다.\n\n"
    "프로덕션 환경에서는 `.streamlit/secrets.toml`의 `OPENAI_API_KEY` 사용을 권장합니다."
)

# -------- API Key 입력/로드 --------
secret_key = st.secrets.get("OPENAI_API_KEY", "")
typed_key = st.text_input("OpenAI API Key", type="password", value="" if secret_key else "")
openai_api_key = (secret_key or typed_key).strip()

if not openai_api_key:
    st.info("Please add your OpenAI API key to continue.", icon="🗝️")
    st.stop()

# API Key 기본적 형식 검사
if not (openai_api_key.startswith("sk-") or openai_api_key.startswith("sk-proj-")):
    st.warning("API 키는 일반적으로 `sk-` 또는 `sk-proj-`로 시작합니다.")

# -------- OpenAI Client --------
client = OpenAI(api_key=openai_api_key)

# -------- 모델 / 옵션 설정 (사이드바) --------
with st.sidebar:
    st.subheader("⚙️ 옵션")
    model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-5"])
    temperature = st.slider("Temperature", 0.0, 1.0, 0.6, 0.1)
    max_tokens = st.slider("Max Output Tokens", 128, 4096, 800, 50)

# -------- 질문 입력 --------
user_query = st.chat_input("궁금한 점을 입력하세요!")

# -------- 초기 상태 --------
if "history" not in st.session_state:
    st.session_state.history = []

# -------- 모델 호출 --------
if user_query:

    # 대화 기록 저장(원하면 유지)
    st.session_state.history.append({"role": "user", "content": user_query})

    try:
        # 한 번의 호출에서 두 언어를 생성하도록 prompt 조정
        prompt = f"""
User question: {user_query}

You MUST answer in the following format:

[KR]
(Write a good Korean answer, clear and concise.)

[EN]
(Write a good English answer, clear and concise.)
"""

        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,  # 여기선 두 결과를 한 번 출력
            messages=[
                {"role": "system", "content": "You are a bilingual helpful assistant."},
                {"role": "user", "content": prompt},
            ],
        )

        full_text = response.choices[0].message.content

        # ---------------- 파싱 ----------------
        # 단순 split 기반
        kr_part = ""
        en_part = ""
        if "[KR]" in full_text and "[EN]" in full_text:
            kr_part = full_text.split("[KR]")[1].split("[EN]")[0].strip()
            en_part = full_text.split("[EN]")[1].strip()
        else:
            kr_part = full_text

        # -------- 출력 UI --------
        st.subheader("🧠 생성된 두 개의 답변")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🇰🇷 Korean Answer [KR]")
            st.write(kr_part)
            if st.button("✅ 한국어 답변 선택"):
                st.success("한국어 답변을 선택했습니다!")
                st.session_state.history.append({"role": "assistant", "content": kr_part})

        with col2:
            st.markdown("### 🇺🇸 English Answer [EN]")
            st.write(en_part)
            if st.button("✅ English Answer Select"):
                st.success("You selected the English answer!")
                st.session_state.history.append({"role": "assistant", "content": en_part})

    except HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        text = getattr(e.response, "text", "")[:500]
        if code == 401:
            st.error(
                "인증 오류(401): API 키가 유효하지 않거나 권한이 없습니다.\n\n"
                "- 새 키를 발급해 공백 없이 정확히 붙여넣어 주세요.\n"
                "- `.streamlit/secrets.toml` 확인 후 앱을 재시작하세요.\n\n"
                f"{text}"
            )
        else:
            st.error(f"API 오류({code}): {text}")
        st.stop()

    except (ConnectError, ReadTimeout):
        st.error("네트워크 연결 문제로 실패했습니다. 잠시 후 다시 시도해주세요.")
        st.stop()

    except Exception as e:
        st.error(f"알 수 없는 오류: {e}")
        st.stop()

# -------- 히스토리 출력 (옵션) --------
st.divider()
st.markdown("### 📜 대화 기록")
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
