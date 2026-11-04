import streamlit as st

# ------------------------------------------------------------
# 5등급제 → 9등급제 성적 로드맵
# 환산 원칙: 9등급제 환산값 = (5등급제 평균 × 2) - 1
# ------------------------------------------------------------

TOTAL_SEMESTERS = 5  # 1-1, 1-2, 2-1, 2-2, 3-1
SEMESTERS = ["1학년 1학기", "1학년 2학기", "2학년 1학기", "2학년 2학기", "3학년 1학기"]

st.set_page_config(
    page_title="내신 로드맵 | 5등급제 → 9등급제",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .block-container {max-width: 1100px; padding-top: 2rem; padding-bottom: 3rem;}
        [data-testid="stSidebar"] {background: #F8FAFC;}
        .hero {padding: 0.3rem 0 1.2rem 0;}
        .hero h1 {font-size: 2.35rem; margin-bottom: .25rem; color: #0F172A;}
        .hero p {font-size: 1.05rem; color: #475569; margin-top: 0;}
        .summary-card {
            position: sticky; top: .5rem; z-index: 100;
            background: linear-gradient(115deg, #173B71 0%, #2563EB 100%);
            border-radius: 18px; padding: 1.15rem 1.4rem; margin: .7rem 0 1.4rem;
            color: white; box-shadow: 0 10px 24px rgba(37, 99, 235, .20);
        }
        .summary-label {font-size: .9rem; opacity: .86; margin-bottom: .25rem;}
        .summary-grade {font-size: 2.15rem; font-weight: 750; line-height: 1.12;}
        .summary-sub {font-size: .88rem; opacity: .88; margin-top: .28rem;}
        .mode-card {
            border: 1px solid #E2E8F0; border-radius: 16px; padding: 1.05rem 1.15rem;
            background: #FFFFFF; min-height: 142px; margin-bottom: .8rem;
        }
        .mode-card h3 {margin: 0 0 .35rem; color: #0F172A; font-size: 1.15rem;}
        .mode-card p {margin: 0; color: #475569; font-size: .93rem;}
        .target-pill {
            display: inline-block; background: #EFF6FF; color: #1D4ED8; border-radius: 999px;
            padding: .25rem .58rem; font-size: .85rem; font-weight: 650; margin-top: .68rem;
        }
        .footnote {color: #64748B; font-size: .84rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def to_nine_grade(five_grade: float) -> float:
    """5등급제 평균을 9등급제의 같은 위치로 간편 환산한다."""
    return max(1.0, min(9.0, 2 * five_grade - 1))


def bounded_plan(required_sum: float, offsets: list[float]) -> list[float]:
    """합계는 유지하면서 1~9등급 범위 안의 계획값을 만든다."""
    count = len(offsets)
    base = required_sum / count
    raw = [base + value for value in offsets]

    # 공통 이동값을 이분 탐색해, 클리핑 후 합계가 required_sum이 되게 한다.
    low, high = -20.0, 20.0
    for _ in range(80):
        shift = (low + high) / 2
        total = sum(min(9.0, max(1.0, value + shift)) for value in raw)
        if total < required_sum:
            low = shift
        else:
            high = shift
    return [min(9.0, max(1.0, value + (low + high) / 2)) for value in raw]


def make_plans(required_sum: float, remaining_count: int) -> list[dict]:
    """세 가지 난이도 분배 방식의 등급 계획을 반환한다."""
    # 오프셋의 합은 0: 목표 달성에 필요한 평균은 모든 모드에서 같다.
    spread = 0.75 if remaining_count >= 3 else 0.55
    even = [0.0] * remaining_count
    late_sprint = [spread - (2 * spread * i / (remaining_count - 1)) for i in range(remaining_count)] if remaining_count > 1 else even
    early_push = [-value for value in late_sprint]

    return [
        {
            "name": "🧭 페이스메이커",
            "description": "남은 학기를 같은 목표 등급으로 안정적으로 채우는 균등 분배 계획",
            "values": bounded_plan(required_sum, even),
        },
        {
            "name": "🚀 후반 스퍼트",
            "description": "초반에는 적응하고, 학년이 올라갈수록 등급을 끌어올리는 상승형 계획",
            "values": bounded_plan(required_sum, late_sprint),
        },
        {
            "name": "🔥 초반 몰아치기",
            "description": "남은 초반에 더 높은 성적을 확보하고, 뒤로 갈수록 부담을 낮추는 선점형 계획",
            "values": bounded_plan(required_sum, early_push),
        },
    ]


st.markdown(
    """
    <div class="hero">
      <h1>🎯 내신 목표 로드맵</h1>
      <p>현재 성적을 9등급제로 간편 환산하고, 3학년 1학기까지의 목표를 학기별로 설계해 보세요.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("성적 입력")
    st.caption("입력값은 모두 5등급제 학기 평균등급입니다.")
    last_completed_label = st.selectbox(
        "성적이 나온 마지막 학기",
        options=SEMESTERS[:4],
        index=1,
        help="선택한 학기까지만 성적 입력칸이 표시됩니다.",
    )
    completed_count = SEMESTERS.index(last_completed_label) + 1

    entered_grades = []
    for semester in SEMESTERS[:completed_count]:
        entered_grades.append(
            st.number_input(
                f"{semester} 평균등급",
                min_value=1.0,
                max_value=5.0,
                value=3.0,
                step=0.1,
                format="%.1f",
                key=f"grade_{semester}",
            )
        )

    st.divider()
    target_five = st.number_input(
        "최종 목표 평균등급 (3학년 1학기까지)",
        min_value=1.0,
        max_value=5.0,
        value=2.0,
        step=0.1,
        format="%.1f",
        help="5개 학기의 단순 평균을 기준으로 계산합니다.",
    )

current_five = sum(entered_grades) / completed_count
current_nine = to_nine_grade(current_five)
target_nine = to_nine_grade(target_five)
remaining_semesters = SEMESTERS[completed_count:]
remaining_count = len(remaining_semesters)
required_sum = target_nine * TOTAL_SEMESTERS - sum(to_nine_grade(value) for value in entered_grades)
required_avg = required_sum / remaining_count

st.markdown(
    f"""
    <div class="summary-card">
        <div class="summary-label">현재 성적 · 9등급제 환산</div>
        <div class="summary-grade">{current_nine:.2f}등급</div>
        <div class="summary-sub">입력한 {completed_count}개 학기 평균 {current_five:.2f}등급(5등급제) · 목표 {target_nine:.2f}등급(9등급제)</div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.subheader("남은 학기 목표 로드맵")

if required_avg < 1.0 - 1e-8 or required_avg > 9.0 + 1e-8:
    direction = "더 낮은(우수한)" if required_avg < 1.0 else "더 높은"
    st.error(
        f"현재 입력값과 목표 조합으로는 남은 {remaining_count}개 학기에서 평균 **{required_avg:.2f}등급**이 필요합니다. "
        f"등급 범위(1.00~9.00)를 벗어나므로 목표를 {direction} 등급 방향으로 조정해 보세요."
    )
else:
    st.info(
        f"목표 달성을 위해 남은 {remaining_count}개 학기 평균은 **{required_avg:.2f}등급**이 필요합니다. "
        "숫자가 작을수록 높은 성적입니다."
    )

    plans = make_plans(required_sum, remaining_count)
    columns = st.columns(3)
    for column, plan in zip(columns, plans):
        with column:
            st.markdown(
                f"""
                <div class="mode-card">
                  <h3>{plan['name']}</h3>
                  <p>{plan['description']}</p>
                  <span class="target-pill">남은 학기 평균 {sum(plan['values']) / remaining_count:.2f}등급</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            roadmap = {
                "학기": remaining_semesters,
                "목표 등급 (9등급제)": [f"{value:.2f}" for value in plan["values"]],
            }
            st.dataframe(roadmap, hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("계산 기준")
    st.markdown(
        """
        - **환산식:** 9등급제 환산값 = `(5등급제 평균등급 × 2) - 1`
        - **최종 목표:** 1학년 1학기부터 3학년 1학기까지 총 5개 학기의 **단순 평균**을 기준으로 계산합니다.
        - 각 모드는 목표 평균은 동일하게 유지하고, 남은 학기별 난이도만 다르게 배분합니다.
        """
    )

st.markdown(
    """
    <p class="footnote">
      ※ 이 앱은 성적 계획을 위한 간편 계산기입니다. 학교·대학·전형별 실제 반영 방식(과목별 단위수, 석차등급, 진로선택 과목 등)은 다를 수 있으므로 공식 모집요강을 함께 확인하세요.
    </p>
    """,
    unsafe_allow_html=True,
)
