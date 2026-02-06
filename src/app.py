
import streamlit as st
import pandas as pd
import os
import math
from dotenv import load_dotenv
from openai import OpenAI
import plotly.express as px

# 커스텀 모듈
from utils.db_handler import load_from_db, save_to_db, get_ai_context  
from utils.file_handler import process_uploaded_zip, format_df_for_display
from utils.ai_agent import ask_gpt_finance

# 1. 설정 및 초기화
st.set_page_config(page_title="Money AI", page_icon="💰", layout="wide")

# 모바일에서 '앱'처럼 보이게 하는 메타 태그 주입
st.markdown("""
    <link rel="manifest" href="app/static/manifest.json">
    
    <style>
    /* 상단 여백 확보 (안드로이드 상태바 가림 방지) */
    .block-container {
        padding-top: 4rem; 
        padding-bottom: 0rem;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 1.1rem;
        padding-top: 0.5rem;
        padding-bottom: 0.5rem;
    }
    </style>
    
    <meta name="theme-color" content="#ffffff">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    """, unsafe_allow_html=True)

load_dotenv()

# 세션 상태 초기화
if 'cp' not in st.session_state: st.session_state.cp = 1
if "messages" not in st.session_state: st.session_state.messages = []

def reset_cp(): st.session_state.cp = 1

def main():
    # 2. 사이드바 (데이터 관리)
    with st.sidebar:
        st.title("📂 데이터 관리")
        up_file = st.file_uploader("뱅샐 ZIP 업로드", type=None)
        pw = st.text_input("비밀번호", type="password")
        
        # DB 초기화 버튼
        if st.button("DB 전체 삭제"):
            if os.path.exists("data/money_vault.db"): 
                os.remove("data/money_vault.db")
                st.rerun()
        
        st.divider()
        
        # API 키 확인 및 클라이언트 생성
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            st.error("API 키 미설정")
            client = None
        else:
            st.success("AI 엔진 가동 중")
            client = OpenAI(api_key=api_key)

    # 데이터 로드를 탭 생성 전으로 이동
    df = load_from_db()

    # 2. 탭 구성 (리포트 탭 추가)
    tab1, tab2, tab3 = st.tabs(["📊 장부", "💬 AI 비서", "📈 리포트"])

    # --- [탭 1] 자산 장부 ---
    with tab1:
        st.title("💰 Money AI 장부")
        
        # 파일 업로드 처리
        if up_file and pw:
            new_df, error_msg = process_uploaded_zip(up_file, pw)
            
            if new_df is not None:
                try:
                    save_to_db(new_df) 
                    st.success("✅ 저장 성공! 중복된 데이터는 제외하고 등록했습니다.")
                    st.rerun()
                except RuntimeError as e:
                    st.error(e) 
            elif error_msg:
                st.error(error_msg)

        # 데이터 표시
        if df is not None and not df.empty:
            display_df = format_df_for_display(df)
            
            # 필터 UI
            with st.expander("🔍 필터 설정", expanded=False):
                f_content = st.text_input("내용 검색", on_change=reset_cp)
                cats = sorted(display_df['대분류'].unique()) if '대분류' in display_df.columns else []
                f_cat = st.multiselect("대분류 필터", cats, on_change=reset_cp)

            # 필터링 적용
            if f_content: display_df = display_df[display_df['내용'].str.contains(f_content, na=False)]
            if f_cat: display_df = display_df[display_df['대분류'].isin(f_cat)]

            # 페이지네이션
            page_size = 15
            total_pages = max(1, math.ceil(len(display_df) / page_size))
            start = (st.session_state.cp - 1) * page_size

            # 테이블 출력
            st.dataframe(
                display_df.iloc[start:start+page_size], 
                use_container_width=True,
                hide_index=True,
                column_config={
                    "금액": st.column_config.NumberColumn("금액(원)", format="%d"),
                }
            )

            # 페이지네이션 버튼
            c1, c2, c3, c4, c5 = st.columns(5)
            with c2: 
                if st.button("‹") and st.session_state.cp > 1: 
                    st.session_state.cp -= 1; st.rerun()
            with c3: st.write(f"**{st.session_state.cp} / {total_pages}**")
            with c4: 
                if st.button("›") and st.session_state.cp < total_pages: 
                    st.session_state.cp += 1; st.rerun()
        else:
            st.info("데이터를 업로드해주세요.")

    # --- [탭 2] AI 비서 ---
    with tab2:
        st.title("🤖 Money AI 비서")
        st.subheader("💬 무엇이든 물어보세요")
        chat_container = st.container(height=500)
        
        # 대화 기록 표시
        with chat_container:
            for msg in st.session_state.messages:
                st.chat_message(msg["role"]).markdown(msg["content"])

        # 입력 및 응답
        if prompt := st.chat_input("질문을 입력하세요"):
            if not client:
                st.error("OpenAI API 키가 필요합니다.")
            else:
                st.session_state.messages.append({"role": "user", "content": prompt})
                with chat_container:
                    st.chat_message("user").markdown(prompt)
                
                with chat_container:
                    with st.chat_message("assistant"):
                        with st.spinner("분석 중..."):
                            db_context = get_ai_context()
                            answer = ask_gpt_finance(client, prompt, db_context, st.session_state.messages)
                            st.markdown(answer)
                            st.session_state.messages.append({"role": "assistant", "content": answer})

# --- [탭 3] 리포트 ---
    with tab3:
        st.header("이번 달 소비 분석")

        # 데이터가 있는지 확인
        if df is not None and not df.empty:
            
            # (1) 데이터 전처리: 금액을 숫자로 변환 (오류 방지)
            df['금액_수치'] = pd.to_numeric(df['금액'], errors='coerce').fillna(0)
            
            # --- [핵심 수정 로직] ---
            # 1. '지출' 데이터만 필터링 (수입, 이체 제외)
            # 만약 '타입' 컬럼이 없다면(구형 엑셀 등), 전체 데이터를 씁니다.
            if '타입' in df.columns:
                # .copy()를 써야 원본 df에 영향을 주지 않고 안전하게 가공합니다.
                expense_df = df[df['타입'] == '지출'].copy()
            else:
                expense_df = df.copy()

            # 2. 금액을 절대값(양수)으로 변환 (마이너스 부호 제거)
            # -15000 -> 15000
            expense_df['금액_수치'] = expense_df['금액_수치'].abs()
            # -----------------------

            # (2) 카테고리별 집계 (Group By)
            # 필터링된 'expense_df'를 사용합니다.
            category_sum = expense_df.groupby('대분류')['금액_수치'].sum().reset_index()
            
            # 금액이 0보다 큰 것만 남김 (0원짜리 카테고리 제거)
            category_sum = category_sum[category_sum['금액_수치'] > 0]
            
            # 금액이 큰 순서대로 정렬 (시각화 예쁘게 하기 위해)
            category_sum = category_sum.sort_values(by='금액_수치', ascending=False)

            # (3) 파이 차트 그리기
            st.subheader("💳 카테고리별 지출 비중")
            
            if not category_sum.empty:
                fig_pie = px.pie(
                    category_sum, 
                    values='금액_수치', 
                    names='대분류',
                    hole=0.4, # 도넛 차트 스타일
                    title='지출 카테고리 분포'
                )
                # 차트 안에 퍼센트와 라벨 표시
                fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.warning("표시할 '지출' 데이터가 없습니다.")

            # (4) 막대 차트 (일별 지출 흐름)
            st.subheader("📅 일별 지출 흐름")
            daily_sum = expense_df.groupby('날짜')['금액_수치'].sum().reset_index()
            
            if not daily_sum.empty:
                fig_bar = px.bar(
                    daily_sum, 
                    x='날짜', 
                    y='금액_수치',
                    title='일자별 지출 추이',
                    color='금액_수치', # 금액에 따라 색상 진하게
                    color_continuous_scale='Bluyl' # 깔끔한 파란색 계열
                )
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.warning("표시할 데이터가 없습니다.")

        else:
            st.info("데이터가 없습니다. 엑셀 파일을 업로드해주세요.")

# 스크립트 실행 진입점
if __name__ == "__main__":
    main()