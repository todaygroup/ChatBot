# app.py
import streamlit as st
import os
from openai import OpenAI

# (선택) httpx 예외 세분화
try:
    from httpx import HTTPStatusError, ConnectError, ReadTimeout
except Exception:
    HTTPStatusError = ConnectError = ReadTimeout = Exception

# -------------------- 페이지 설정 --------------------
st.set_page_config(page_title="Chatbot (KR & EN Two Answers)", page_icon="💬")

st.title("💬 Chatbot (KR & EN Two Answers)")
st.write(
    "한 번의 질문에 대해 **한국어**와 **영어** 두 개의 답변 후보를 동시에 생성합니다. "
    "프로덕션 환경에서는 `.streamlit/secrets.toml`의 `OPENAI_API_KEY` 사용을 권장합니다."
)

# -------------------- API 키 로딩 --------------------
# 우선순위: secrets.toml > 환경변수 > 입력창
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

# 간단 형식 경고(가드레일)
if not (openai_api_key.startswith("sk-") or openai_api_key.startswith("sk-proj-")):
    st.warning("API 키는 보통 `sk-` 또는 `sk-proj-`로 시작합니다. 값을 다시 확인해 주세요.")

# -------------------- OpenAI 클라이언트 & 사전 인증 --------------------
# 사전 인증 플래그
auth_ok = False
try:
    client = OpenAI(api_key=openai_api_key)

    # 사전 헬스체크: 권한/키 유효성 검증 (모델 목록)
    # 이 단계에서 401/권한 문제 등 대부분이 걸러집니다.
    _ = client.models.list()
    auth_ok = True

except HTTPStatusError as e:
    code = getattr(e.response, "status_code", None)
    text = getattr(e.response, "text", "")[:500]
    if code == 401:
        st.error(
            "인증 오류(401): API 키가 유효하지 않거나 권한이 없습니다.\n\n"
            "- 새 키를 발급해 공백 없이 정확히 붙여넣어 주세요.\n"
            "- `.streamlit/secrets.toml`/환경변수에 남아있는 오래된 키를 제거하고 앱을 재시작하세요.\n"
            "- `pip install -U openai`로 최신 버전을 사용하세요.\n\n"
            f"세부: {text}"
        )
    elif code == 429:
        st.error(
            "요청이 너무 많거나 한도를 초과했습니다(429). 잠시 후 다시 시도하거나, "
            "요청 빈도/출력 토큰을 낮춰 보세요."
        )
    else:
        st.error(f"API 오류({code}): {text}")
    st.stop()

except (ConnectError, ReadTimeout):
    st.error("네트워크 문제로 인증 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()

except Exception as e:
    st.error(f"알 수 없는 오류(사전 인증 단계): {e}")
    st.stop()

# -------------------- 옵션 (사이드바) --------------------
with st.sidebar:
    st.subheader("⚙️ 옵션")
    model = st.selectbox("Model", ["gpt-4o-mini", "gpt-4o", "gpt-5"], index=0)
    temperature = st.slider("Temperature", 0.0, 1.0, 0.6, 0.1)
    max_tokens = st.slider("Max Output Tokens", 128, 4096, 800, 50)

# -------------------- 세션 상태 --------------------
if "history" not in st.session_state:
    st.session_state.history = []

# -------------------- 입력 --------------------
user_query = st.chat_input("궁금한 점을 입력하세요!")

# -------------------- 응답 생성 --------------------
def generate_two_answers(question: str):
    """
    하나의 호출로 [KR]과 [EN] 섹션을 동시에 생성하고, 문자열 파싱해 반환.
    """
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

    # 단순 파싱
    kr, en = "", ""
    if "[KR]" in full and "[EN]" in full:
        kr = full.split("[KR]")[1].split("[EN]")[0].strip()
        en = full.split("[EN]")[1].strip()
    else:
        # 포맷이 어긋나면 일단 전체를 KR로
        kr = full.strip()
    return kr, en

# -------------------- 메인 로직 --------------------
if auth_ok and user_query:
    st.session_state.history.append({"role": "user", "content": user_query})

    try:
        kr_part, en_part = generate_two_answers(user_query)

        st.subheader("🧠 생성된 두 개의 답변")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 🇰🇷 Korean Answer [KR]")
            st.write(kr_part or "_(생성 결과가 비었습니다)_")
            if st.button("✅ 한국어 답변 선택", key=f"pick_kr_{len(st.session_state.history)}"):
                st.success("한국어 답변을 선택했습니다!")
                st.session_state.history.append({"role": "assistant", "content": kr_part})

        with col2:
            st.markdown("### 🇺🇸 English Answer [EN]")
            st.write(en_part or "_(생성 결과가 비었습니다)_")
            if st.button("✅ English Answer Select", key=f"pick_en_{len(st.session_state.history)}"):
                st.success("You selected the English answer!")
                st.session_state.history.append({"role": "assistant", "content": en_part})

    except HTTPStatusError as e:
        code = getattr(e.response, "status_code", None)
        text = getattr(e.response, "text", "")[:500]
        if code == 401:
            st.error(
                "인증 오류(401): API 키가 유효하지 않거나 권한이 없습니다.\n"
                "새 키를 발급해 정확히 입력하고 다시 시도하세요.\n\n"
                f"{text}"
            )
        elif code == 429:
            st.error("요청 한도를 초과했습니다(429). 잠시 후 다시 시도해 주세요.")
        else:
            st.error(f"API 오류({code}): {text}")
    except (ConnectError, ReadTimeout):
        st.error("네트워크 문제로 실패했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        st.error(f"알 수 없는 오류(응답 생성 단계): {e}")

# -------------------- 대화 기록 --------------------
st.divider()
st.markdown("### 📜 대화 기록")
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
